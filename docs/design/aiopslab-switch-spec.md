# AIOpsLab 切换 Spec

> 状态：草稿（调研结论，待评审后执行）
> 日期：2026-08-15
> 关联文档：`docs/reference/aiopslab-comparison.md`（两者对比）

本文是**将评测后端从"otel-demo flagd chaos"切换到 Microsoft AIOpsLab** 的切换说明。目标不是换 agent，而是**换"评测环境/故障注入/问题编排"这一层**；agent 仍是 ops_pilot 自身，评测门禁与 Langfuse 追踪尽量保留。

---

## 1. 决策记录（ADR 摘要）

- **背景**：当前 Level 4 Chaos Eval 依赖 OTel Demo + flagd 特征开关，只覆盖 13 个 flag、单一故障层面，样本与故障类型都受限于这一个应用。
- **决策**：按"取更成熟、故障注入更真实"的原则，切换到 AIOpsLab 作为评测框架。AIOpsLab 提供多应用（hotel / social / astronomy shop / tidb / flower…）、60+ problem、多层面故障注入（Chaos Mesh / app / OS / 虚拟化 / OTel flag）。
- **保留项**：
  - agent = ops_pilot（DeepAgents + LangGraph），通过 AIOpsLab client 契约接入；
  - 评测门禁（hard gates、sentinel 校准）与 Langfuse 追踪通过 wrapper 接回；
  - 前端（CopilotKit web app）与本切换无关，保持不动。
- **放弃项**：`eval/chaos.py`（flagd client）、`ops_pilot chaos` CLI、`eval/cases/chaos/*.yaml`、`deploy/astronomy-shop/`、otel-demo 集群资源。

---

## 2. 目标架构

```
┌────────────────────────── 本机 / Linux VM (controller) ─────────────────────────┐
│  AIOpsLab 框架（poetry, python3.11）                                              │
│   ├─ Orchestrator + Session（init_problem → start_problem → eval）              │
│   ├─ clients/ops_pilot.py  ← 我们把 ops_pilot 封装成 AIOpsLab client            │
│   └─ 故障注入 + workload + 评测（evaluators）                                     │
│          │ kubectl / helm（指向 Gardener shoot）                                 │
└──────────┼───────────────────────────────────────────────────────────────────────┘
           ▼
┌────────────────────────── Gardener shoot ─────────────────────────┐
│  各 app namespace（hotel-reservation / social-network / ...）       │
│  Chaos Mesh（namespace: chaos-mesh）· Prometheus（自动部署）        │
│  （可选）Jaeger / 其他 telemetry                                    │
└────────────────────────────────────────────────────────────────────┘
```

- **controller**：AIOpsLab 框架跑在 Linux VM / WSL（Windows 本机不适配其 kubectl/SSH/poetry 工作流；见 §5 风险）。
- **目标集群**：Gardener shoot（`garden-cloud--stzoojqj5i-external`）。**资源紧张，强烈建议扩独立 worker 池或另建 shoot**（§5）。

---

## 3. AIOpsLab 侧接入事实（调研结论）

### 3.1 部署与配置

```bash
git clone --recurse-submodules https://github.com/microsoft/AIOpsLab.git   # 含 aiopslab-applications 子模块
cd AIOpsLab
poetry env use python3.11 && poetry install
cp aiopslab/config.yml.example aiopslab/config.yml
# 编辑：k8s_host / k8s_user / ssh_key_path / data_dir / qualitative_eval
```

`config.yml` 关键项（见 `scripts/ansible/templates/config.yml.j2`）：

```yaml
k8s_host: localhost        # kind 用 kind；远端 shoot 用对应主机名或走本地 kubectl context
k8s_user: <user>
ssh_key_path: ~/.ssh/id_rsa
data_dir: data
qualitative_eval: false    # true 则启用 LLM-as-judge
print_session: false
```

### 3.2 Agent 契约（接入点）

AIOpsLab 的 agent 只要求实现两个方法：

```python
class YourAgent:
    def init_context(self, problem_desc: str, instructions: str, apis: dict):
        ...
    async def get_action(self, observation: str) -> str:
        return "Action:\n```\napi_name(args)\n```"   # markdown code block
```

生命周期：`register_agent(agent, name)` → `init_problem(pid)` → `agent.init_context(...)` → `await orchestrator.start_problem(max_steps)`。环境用 `ResponseParser` 解析 action，经 `problem.perform_action(api, *args, **kwargs)` 执行。

### 3.3 环境给 agent 的能力

- **telemetry APIs**（随 task 不同）：Prometheus / Jaeger 查询接口；
- **`exec_shell`**：进入集群的"安全终端"，可跑命令（**这是 Mitigation 任务的基础，也是与本项目"eval 禁改集群"原则冲突点**，见 §4.3）；
- **`submit(...)`**：提交答案（Detection 提交 Yes/No；Localization 提交故障服务列表；Mitigation 提交后等待集群恢复）。

### 3.4 评测

- 内置定量 evaluator：Detection（Accuracy / TTD）、Localization（exact/subset / TTL）、Analysis（RCA 准确率 / TTA）、Mitigation（成功率 / TTM）；
- 可选 LLM-as-judge（`qualitative_eval: true`）；
- 结果：`data/results/<session_id>.json`，可选 W&B。

### 3.5 REST 服务（可选远程模式）

`service.py` 提供 `/health` `/problems` `/agents` `/simulate`，可把 AIOpsLab 跑在远端，agent 通过 HTTP 驱动。

---

## 4. 需要改动/新增/删除的清单（本项目侧）

### 4.1 新增

| 文件/产物 | 内容 |
| --- | --- |
| `aiopslab/clients/ops_pilot.py` | 把 ops_pilot 封装成 AIOpsLab client（§4.2） |
| `aiopslab/clients/registry.py` 注册 `ops_pilot` | 让 `service.py`/`client.py` 能按名调用 |
| 评测 wrapper（位置待定，可在本项目 `ops_pilot/eval/`） | 把 AIOpsLab session 结果接回 Langfuse + 自家 grader + gates |
| controller 部署 runbook | `docs/` 下记录 Linux VM/WSL + config.yml + 依赖安装 |

### 4.2 agent 适配层（核心工作量）

两个候选路线，推荐 **A**：

- **路线 A（推荐）**：把 AIOpsLab 的 action（telemetry APIs、`exec_shell`、`submit`）映射为 ops_pilot runtime 的**工具**，让 ops_pilot 用原生 tool-calling 执行；`get_action` 只需把 ops_pilot 的最终工具调用/文本翻译成 AIOpsLab 的 markdown action 协议。保留 DeepAgents 的规划与 MCP 能力。
- **路线 B**：让 ops_pilot 直接以纯文本"思考+动作"输出，完全走 AIOpsLab 的 `ResponseParser`。改造深、丢 tool-calling 优势，不推荐。

无论哪条，都需要：
- 用 `problem.get_available_actions()` / `get_task_description()` / `get_instructions()` 构造给 ops_pilot 的 system prompt；
- 把 `exec_shell` 能力**白名单化/只读化**（见 §4.3）；
- 处理 AIOpsLab 的 `Session` trace → 转成 ops_pilot `TraceOutput` 或直接对接 Langfuse。

### 4.3 安全/HITL 冲突（必须处理）

- AIOpsLab 的 Mitigation 任务允许 agent 用 `exec_shell` 改集群；本项目原则是 **eval 期间禁止 K8s 变更**（chaos 显式 bypass HITL，故障根因是 flag，改集群无用）。
- **处理**：初期只启用 detection / localization / analysis 任务，禁用 mitigation；或在 `exec_shell` 工具上做命令白名单（只读命令）与危险命令拦截。若将来要跑 mitigation，需在隔离集群 + 显式确认下进行。

### 4.4 删除 / 废弃（otel-demo 相关）

| 位置 | 动作 |
| --- | --- |
| 集群 `otel-demo` namespace + ingress | 删除（需确认；先备份 values/ingress 到 `deploy/` 归档） |
| `deploy/astronomy-shop/` | 归档（保留作参考） |
| `services/agent/src/ops_pilot/eval/chaos.py` | 删除（flagd client / OFREP / port-forward 逻辑） |
| `ops_pilot chaos` CLI（`eval/cli.py` 中 `add_chaos_subcommands`） | 删除 |
| `eval/cases/chaos/*.yaml` | 删除或迁移为 AIOpsLab problem |
| `config/config.yaml` 的 `chaos:` 段 | 删除 |
| MCP 配置（jaeger / prometheus / opensearch 指向 otel-demo） | 重配到 AIOpsLab 的 telemetry，或移除 |
| package.json `eval:chaos` / `eval:sync:chaos` | 替换为新入口 |

### 4.5 保留不动

- `apps/web` 前端（CopilotKit）及其 runtime bridge；
- ops_pilot agent 本体（`agent/runtime.py` 等）、Langfuse 集成、`eval/runner.py` 的门禁/grader 逻辑（作为 wrapper 复用）；
- `eval/dataset.py` 的 `EvalCase` / `InjectSpec` 模型可复用于"自家 grader 输入"。

---

## 5. 风险与未验证项

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| **集群资源不足**（~13 GiB，otel-demo 已占 1 节点近全部内存） | AIOpsLab 默认应用（尤其 social-network）部署会 OOM | 独立 worker 池 / 独立 shoot；先只跑轻量应用子集 |
| **Chaos Mesh 可行性未实测**（Garden Linux containerd 2.2.6 socket 路径、privileged pod） | symptom 级故障注入可能不可用 | 先在 kind 验证，再在 shoot 用独立 namespace 实测 |
| **OS 级故障需 worker SSH**（未配置） | disk I/O 等 OS 故障不可用 | 评估是否给 shoot worker 配置 SSH（改 shoot spec）；否则放弃该层 |
| **Windows 本机不适配 controller**（poetry/ssh/kubectl 工作流偏 Linux） | 本地无法直接跑 | controller 放 Linux VM / WSL |
| **agent 接口适配工作量大**（文本 action 协议 vs ops_pilot tool-calling） | 核心工期 | 路线 A：把 action 映射为工具，尽量复用 |
| **评测口径变化** | 门禁语义改变，历史结果不可直接对比 | 先接回自家 grader/gates；AIOpsLab 定量指标作为附加信息 |
| **Mitigation 与 HITL 冲突** | 安全风险 | 初期禁用 mitigation + exec_shell 白名单 |
| **子模块/镜像体积大**（DeathStarBench 镜像多） | 拉取/部署慢 | 按需只拉所需 app 镜像；`kind/images.txt` 可参考 |

---

## 6. 分阶段计划（里程碑）

- **M0 资源与决策确认**：确认是否扩 worker 池/独立 shoot；准备 Linux VM/WSL；评估 worker SSH 必要性。
- **M1 AIOpsLab 裸跑通（kind/本地）**：`poetry install` 后跑通官方 smoke test（`noop_detection_hotel_reservation-1`，用 DummyAgent，不调 LLM）。
- **M2 Gardener 上跑通**：controller 指向 shoot；验证应用部署 + Chaos Mesh 实测；跑通 1 个非 OTel problem。
- **M3 ops_pilot client 接入**：写 `clients/ops_pilot.py`（路线 A）；在 1 个 problem 上端到端（detection/localization）。
- **M4 评测 wrapper**：AIOpsLab session 结果 → 自家 grader + Langfuse dataset run + gates。
- **M5 清理 otel-demo**：删除集群资源、归档 deploy、删除 chaos.py/CLI/cases、重配 MCP、替换 pnpm 入口。
- **M6 验收**：`eval` 金字塔 Level 4 改为 AIOpsLab 驱动；门禁生效；文档更新。

---

## 7. 验收标准

1. 在 Gardener（或独立环境）上，`ops_pilot` 作为 client 能跑通 AIOpsLab 的 detection / localization problem，并把结果写入 Langfuse。
2. Chaos Mesh 与至少两类故障注入在目标集群实测有效。
3. 硬门禁（`hitl_safety_rate`、`infra_completion_rate`、judge 校准）在 wrapper 下仍然生效；eval 期间无 K8s 变更。
4. otel-demo 资源已清理，`pnpm eval:chaos` 等旧入口已替换/废弃，文档（本文 + comparison）与代码一致。

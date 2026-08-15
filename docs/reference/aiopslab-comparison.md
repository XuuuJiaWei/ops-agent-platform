# AIOpsLab 与 ops-agent-platform Chaos Eval 对比

> 调研日期：2026-08-15。本文回答两个问题：
> 1. [Microsoft AIOpsLab](https://github.com/microsoft/AIOpsLab) 是什么？
> 2. 它和我们基于 OTel Demo 的 chaos 评测有什么不同？

---

## 1. AIOpsLab 是什么

**AIOpsLab**（Microsoft，MIT 协议，MLSys'25 论文）是一个**评估自主 AIOps Agent 的通用研究框架 + 基准测试套件**。它本身不是运维产品，而是一个"评测台"：能自动部署微服务应用、注入故障、生成负载、导出遥测，并**编排 agent 与环境交互、对 agent 求解结果打分**，目标是 building reproducible / standardized / interoperable / scalable benchmarks。

### 核心组成

| 组件 | 说明 |
| --- | --- |
| **被测应用** | `aiopslab-applications` 子模块：HotelReservation、SocialNetwork、AstronomyShop（OTel Demo）、TiDB、Flower 等，通过 Helm 自动部署 |
| **问题模型** | 每个 Problem = `Application + Task + Fault + Workload + Evaluator` 五件套；60+ 问题注册在 `aiopslab/orchestrator/problems/registry.py` |
| **任务类型** | Detection / Localization / Analysis / **Mitigation**（四类，agent 可对集群执行变更去恢复） |
| **故障注入** | 多层面：Chaos Mesh（pod 杀、网络延迟/丢包、容器杀）、应用层（misconfig、认证缺失、权限撤销）、OS/内核（磁盘 I/O `err_inject`）、虚拟化（容器停止、缩容到 0）、K8s operator（TiDB CR）、OTel 特征开关、virtual/mock、no-op |
| **负载生成** | wrk2 负载生成器（rate / distribution / connections / threads / duration / Lua 脚本 / K8s Job） |
| **Agent 契约** | `async get_action(state) -> action` + `submit(solution)`；注册给 `Orchestrator`，Session 记录交互 trace |
| **驱动方式** | 本地 `cli.py`、远程 `service.py`（REST：`/health` `/problems` `/agents` `/simulate`），W&B 可选记录 |
| **评测** | 量化指标（Accuracy、TTD / TTL / TTA / TTM、exact / subset 匹配）+ 可选 LLM-as-judge（`qualitative_eval`），结果 JSON + W&B |
| **集群部署** | 本地 `kind`；远端集群（Ansible / Azure Terraform；Mode A=controller VM 完整故障注入，Mode B=laptop + 远端 kubectl） |

### OTel Demo 相关实现要点

AIOpsLab 也内置 AstronomyShop 应用，注入方式和 OTel Demo 相同的 flagd 特征开关（`paymentFailure`、`adManualGc`、`imageSlowLoad` 等）。它的 `OtelFaultInjector` 通过 **`kubectl` 读取并 patch flagd ConfigMap `demo.flagd.json`** 来改 variant（见 `aiopslab/generators/fault/inject_otel.py`）。

---

## 2. 与 ops-agent-platform chaos 的对比

两者唯一的交集：**都用 OTel Demo + flagd 特征开关注入故障，让 agent 基于真实遥测做 RCA**。其余在定位、规模、技术路线上差异很大。

| 维度 | AIOpsLab | ops-agent-platform chaos |
| --- | --- | --- |
| **定位** | 通用评测框架 + 可扩展 benchmark（研究项目） | 产品（ops_pilot agent 平台）中的一层评测（Eval 金字塔 Level 4） |
| **被测对象** | 6+ 应用 / 60+ 问题，跨服务、跨技术栈 | 单一 OTel Demo（astronomy shop），14 个 chaos case |
| **任务类型** | Detection / Localization / Analysis / **Mitigation**（允许 agent 执行 kubectl/helm 变更去恢复） | 只有 **Diagnosis + Explain** 闭环；eval 期间**禁止 K8s 变更**（HITL 保护） |
| **故障注入层次** | **多层面**（Chaos Mesh / 应用 / OS / 虚拟化 / operator / OTel flag / mock） | **单一层面**：13 个 flagd 特征开关（应用层故意 misbehave），但产生的 trace/指标/日志/K8s 状态是真实的 |
| **OTel Demo 注入方式** | `kubectl` **patch flagd ConfigMap** `demo.flagd.json` | flagd-ui **官方 `/api/write` live-file API** 原子替换 + OFREP 校验 + 注入前后文档全等 |
| **负载生成** | wrk2 合成负载（AstronomyShop 用内置 load generator） | 直接使用 OTel Demo 内置 load generator |
| **Agent 接入** | 自定义 agent 契约（`get_action` / `submit`），自带 Orchestrator / Session / REST | 跑 ops_pilot 自身（DeepAgents + LangGraph + 4 个 MCP），MCP fail-closed 预检 |
| **评测方式** | 量化指标 + 可选 LLM-judge；结果 JSON + W&B | 确定性 grader + LLM-as-judge + sentinel 校准 + 硬门禁（`hitl_safety_rate=1.0`、`infra_completion≥0.95`）；trace 写 Langfuse dataset run；Wilson CI |
| **部署形态** | kind 本地 / 云集群（Terraform+Ansible），研究用 | Gardener Shoot + Helm（`opentelemetry-demo` 0.41.0 + `prometheus-mcp` + jaeger_mcp），认证过的远端 MCP 端点 |
| **HITL/安全** | 无 HITL 概念，agent 可做 Mitigation | 自动 chaos 显式 bypass HITL，且只允许在隔离测试集群跑 |

---

## 3. 关键差异解析

### 3.1 故障覆盖广度 vs 深度

- AIOpsLab 覆盖 Chaos Mesh、OS 级、虚拟化级故障，正好对应我们 `docs/design/agent-eval.md §13` 里记录的两大盲区：**跨服务因果链**、**故障类型覆盖**（当前只覆盖 13 个 flag 的"机制覆盖"）。
- 我们的选择是**在一个目标上深挖**：flagd 故障会产生真实信号，但根因始终在 flag，K8s 动作无法治愈，因此只做诊断闭环。

### 3.2 Mitigation 任务

AIOpsLab 的 MitigationTask 允许 agent 执行 kubectl/helm 恢复动作；我们刻意不做——因为 OTel Demo 的故障根因在特征开关（改集群只是换个读同一 flag 的新 pod），真正的"治愈"是关掉 flag。这是有意的安全取舍（诊断闭环 + HITL 保护）。

### 3.3 Agent 接口标准化

AIOpsLab 把 agent 抽象成统一契约 + REST 服务，方便"换 agent 测同一个 problem"；我们则把 agent 平台和评测耦合，评测直接驱动 ops_pilot 自身。若要支持"外部 agent 参赛"，可借鉴其接口设计。

### 3.4 OTel Demo 注入方式（我们的优势）

我们的 `docs/research/official-integration-alignment.md` 已论证：**放弃 ConfigMap patch**，改用 flagd-ui 官方 `/api/write` + OFREP 连续读校验 + 注入前后文档全等。AIOpsLab 仍走 ConfigMap patch（`inject_otel.py`）。我们的方案更贴近官方 API、可校验、不留 ConfigMap 重放风险。

---

## 4. 借鉴点 / 启示

1. **故障库与 problem 抽象**：后续若扩 chaos 覆盖面，AIOpsLab 的 fault injector 层级（Chaos Mesh、OS、虚拟化）和 problem 五件套是很好的参考蓝本。
2. **统一 agent 契约**：若要让多个 agent（含外部 agent）跑同一套 problem，参考其 `get_action`/`submit` + REST 服务设计。
3. **样本与统计**：双方都受样本量限制；AIOpsLab 的 60+ 问题对缩小置信区间有量上的帮助，但迁移成本高（需在自有集群部署多套应用）。

---

## 5. 参考链接

- 仓库：<https://github.com/microsoft/AIOpsLab>
- 论文：Yinfang Chen et al., "AIOpsLab: A Holistic Framework to Evaluate AI Agents for Enabling Autonomous Clouds", MLSys 2025（<https://arxiv.org/pdf/2501.06706>）
- 相关内部文档：`docs/design/agent-eval.md`、`docs/reference/otel-demo-fault-flags.md`、`docs/research/official-integration-alignment.md`
- **切换计划**：已决定切换到 AIOpsLab 作为评测框架，见 [`docs/design/aiopslab-switch-spec.md`](../design/aiopslab-switch-spec.md)

# ops_pilot — 简历包装文档（秋招 · Agent 开发岗）

> 用途：把本项目写进简历/面试话术。所有量化数字以仓库实测为准（见文末「事实核对」）。
> 定位诚实：这是一个**个人项目 / 工程原型**，非生产系统——请勿写「已上线」「大规模使用」「效果提升 X%」等无法佐证的表述。

---

## 一句话定位

面向企业运维（AIOps）场景的**对话式 Agent 平台**：以协议无关的统一 Agent Runtime 为核心，通过 MCP 动态接入可观测性工具，具备 HITL 安全审批、远程沙箱执行、Langfuse 可观测与「故障注入 → 评测」闭环。

技术栈：Python（DeepAgents / LangGraph / FastAPI）+ React 19 / TypeScript（CopilotKit / AG-UI）。

---

## 招聘方在 Agent 开发岗最看重的能力信号

写简历/准备面试时，围绕这 6 条组织材料（本项目均可对应）：

1. **端到端落地**：不是只调 LLM API，而是可运行、可维护、有错误处理/监控/容错的系统。
2. **Agent 框架与编排**：LangGraph/DeepAgents 的原理 + 工程实现，而非「调包」。
3. **工具调用与协议集成**：MCP、Function Calling、A2A 是高频关键词。
4. **可靠性与安全**：HITL、危险操作审批、超时、降级、沙箱、故障兜底——Agent 接生产的核心不是「会不会答」而是「会不会失控」。
5. **评测与可观测**：dataset、trace、LLM-as-judge、线上回放与问题定位。
6. **工程化与协作**：前后端、测试、模块边界、协议兼容。

---

## 五大亮点（按「业务价值 > 系统复杂度 > 关键机制」排序）

### 1. 协议无关的统一 Agent Runtime
- 单一 `agent factory` 同时对接 **CopilotKit/AG-UI（浏览器流式聊天）** 与 **Google A2A（Agent2Agent JSON-RPC，程序化调用）**，两条协议复用同一套模型、工具、Prompt、可观测配置。
- 体现「Agent 核心层」抽象能力，而非单一前端 demo。

### 2. MCP 动态工具编排
- 支持 **stdio 本地** 与 **streamable_http 远程（带认证）** 两类 MCP 传输。
- 并发加载、per-server 超时、`required`/`optional` 降级（可选服务加载失败不阻断启动）。
- 已接入 Kubernetes / Prometheus / Jaeger / OpenSearch 等可观测性工具。

### 3. 可靠性与安全边界
- **HITL**：对危险工具调用（命令执行、集群操作）走人工审批（`interrupt_on`）。
- **远程沙箱（OpenSandbox）**：Agent 的文件系统与命令执行隔离到受控环境，带 **租约续期** 保障长任务。
- per-call 请求超时、自适应推理策略，控制卡死与成本。

### 4. 评测闭环（最强差异化）
- 基于 **Langfuse dataset** 的评测，集成 **LLM-as-judge** 评分器（rubric judge）+ 确定性布尔评分。
- **Chaos eval**：对每个测试用例自动开启对应的 OpenTelemetry Demo 故障 flag（`kubectl patch` flagd ConfigMap）→ 等信号沉淀 → 跑 Agent（带 trace）→ 自动关闭 flag → 冷却。**串行执行**（flag 是集群级全局状态），且外层 `finally` 全程兜底 reset，崩溃/Ctrl-C 也不会留脏状态。

### 5. 可观测
- Langfuse tracing 贯穿 `/chat` 与 `/a2a` 两条协议链路，凭证缺失时自动降级为无操作，不阻断本地启动。

---

## 简历 Bullet（可直接粘贴 · 中文）

- **基于 DeepAgents / LangGraph 构建协议无关的统一 Agent Runtime 与 agent factory**，让同一后端同时对接 CopilotKit/AG-UI 流式聊天与 Google A2A JSON-RPC，两协议复用同一套模型/工具/Prompt/可观测配置，消除重复实现。
- **实现 MCP（Model Context Protocol）动态工具加载框架**，支持 stdio 本地与 streamable_http 认证远程两类传输，接入 Kubernetes/Prometheus/Jaeger/OpenSearch 等可观测工具；实现并发加载、per-server 超时与 required/optional 降级，提升工具接入的稳定性与可扩展性。
- **为高风险工具调用设计 HITL 审批链路**，对命令执行、集群操作等危险动作强制人工确认；结合 per-call 超时、自适应推理策略与远程沙箱隔离（租约续期），系统性降低 Agent 失控与成本风险。
- **搭建基于 Langfuse dataset 的评测体系**，集成 LLM-as-judge 评分器；设计 chaos eval 流程——按用例自动注入 OpenTelemetry Demo 故障、等待信号稳定、运行 Agent、自动回收故障开关并全程兜底 reset，实现故障场景的可复现回归验证。
- **实现远程沙箱（OpenSandbox）执行层**，将 Agent 的文件系统与命令执行隔离到受控环境，通过租约续期保障长任务稳定；后端 ~5600 行 Python、前端 ~1300 行 TypeScript，覆盖 97 个单元/集成测试用例。

## Resume Bullets (English)

- **Built a protocol-agnostic agent runtime on DeepAgents/LangGraph** with a single agent factory that serves both CopilotKit/AG-UI streaming chat and Google A2A (Agent2Agent) JSON-RPC, reusing one model/tool/prompt/observability config across both surfaces.
- **Implemented a dynamic MCP (Model Context Protocol) tool-loading framework** supporting local `stdio` and authenticated remote `streamable_http` transports (Kubernetes, Prometheus, Jaeger, OpenSearch); added concurrent loading, per-server timeouts, and required/optional degradation.
- **Designed an HITL approval path for high-risk tool calls** (command execution, cluster ops), combined with per-call timeouts, an adaptive reasoning policy, and sandboxed execution to reduce runaway/cost risk.
- **Created a Langfuse-dataset evaluation suite with an LLM-as-judge grader**, plus a *chaos eval* loop that injects one OpenTelemetry-Demo fault flag per case (`kubectl patch` on the flagd ConfigMap), lets signals settle, runs the traced agent, and always resets flags in a `finally` guard for reproducible regression testing.
- **Built a remote sandbox (OpenSandbox) execution layer** isolating agent filesystem/command execution with lease renewal for long tasks; ~5.6k lines of Python backend, ~1.3k lines of TypeScript frontend, 97 tests.

---

## STAR 面试话术（口头展开）

- **S**：企业运维中，Agent 要接多种可观测工具、还要保证安全可控——直接让模型执行 kubectl / 查日志风险极高。
- **T**：构建一个可扩展、可评测、可安全上线的对话式 Agent 平台。
- **A**：用 LangGraph/DeepAgents 抽象统一 runtime；MCP 动态接工具（并发/超时/降级）；危险调用加 HITL；文件/命令进远程沙箱；Langfuse 做 trace；建 dataset + judge + chaos eval 闭环。
- **R**：一套后端两协议复用、工具热插拔、危险操作 100% 走审批、故障场景可自动复现回归；97 个测试覆盖关键链路。

---

## 深挖问题预案（面试大概率会问）

- **为什么用 MCP 而不是自己写 tool schema？** → 标准协议、工具与 Agent 解耦、可复用社区 server；再讲你做的并发加载/超时/降级增强。
- **chaos eval 为什么串行 / max_concurrency=1？** → flag 是集群级全局状态（patch 同一个 ConfigMap），并发会互相踩；串行 + 两层 finally reset 保证隔离与不留脏。
- **HITL 怎么实现的？** → LangGraph `interrupt_on`，对配置为 hitl 的工具名在执行前中断、等前端审批。
- **两协议怎么共享一个 agent？** → factory 只产出 graph/runtime，AG-UI 与 A2A 各自是 adapter，不复制业务逻辑。
- **LLM-as-judge 的可信度？** → 诚实说明：rubric judge 是辅助信号，配合确定性布尔评分；没有人工标注基线时不宣称「提升 X%」。

---

## ⚠️ 必须避免的踩坑 / 夸大

- ❌ 「设计了生产级平台」——本项目无真实用户/权限/灰度/SLA/审计，写「工程原型 / 个人项目」。
- ❌ 「效果提升 XX%」——没有固定基线 + 人工标注 + 对照实验，不要写百分比。
- ❌ 只讲模型能力不讲工程约束——Agent 岗更看重可靠性/降级/超时/HITL/评测。
- ❌ 技术名词堆砌（LangGraph/MCP/A2A/Langfuse/OTel…）——每个都要能说清「为什么用、解决什么」。
- ❌ 把「集成/封装」写成「从零设计」——诚实用词。
- ❌ 过度强调前端——Agent 岗核心是 runtime/工具/可靠性/评测/协议。

---

## 事实核对（写简历时的可佐证数字）

| 指标 | 数值 | 来源 |
| --- | --- | --- |
| 后端代码量 | ~5,600 行 Python | `services/agent/src` |
| 前端代码量 | ~1,300 行 TypeScript | `apps/web/src` |
| 测试用例 | 97 个测试函数 / 21 个测试文件 | `services/agent/tests` |
| 已接入 MCP 工具 | 4（Kubernetes / Prometheus / Jaeger / OpenSearch） | `config/config.example.yaml` |
| 故障注入 flag | 13 个 fault flags | `eval/chaos.py: FAULT_FLAGS` |
| 评测用例 | 18 条（14 运维场景 + 4 冒烟） | `services/agent/eval/cases/*.yaml` |
| 双协议 | CopilotKit/AG-UI + Google A2A | `backend.py` / `a2a/` |

> 面试可如实说明规模：一个约一个月、40+ commit 的个人项目，覆盖 Agent 平台从 runtime、工具、安全、沙箱到评测的完整工程链路。

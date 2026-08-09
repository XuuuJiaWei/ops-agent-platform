# ops_pilot — 简历包装文档（秋招 · Agent 开发岗）

> 用途：把本项目写进简历/面试话术。所有量化数字以仓库实测为准（见文末「事实核对」）。
> 定位诚实：这是一个**个人项目 / 工程原型**，非生产系统——请勿写「已上线」「大规模使用」「效果提升 X%」等无法佐证的表述。

---

## 一句话定位

面向企业运维（AIOps）场景的**对话式 Agent 工程原型**：以协议无关的统一 Agent Runtime 为核心，通过 MCP 动态接入可观测性工具，具备持久化状态、可靠工具执行、HITL 安全审批、远程沙箱、可观测与「故障注入 → 评测」闭环。

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

### 3. 可靠执行与安全边界
- **持久化状态分层**：PostgreSQL 分别保存 LangGraph checkpoint、A2A task、CopilotKit AG-UI event 与 Agent Spaces，支持进程重启后恢复执行状态和浏览器历史。
- **可靠工具执行**：以 `(run_id, tool_call_id)` 建立持久化 journal，通过 PostgreSQL advisory lock 去重并发/重复调用；仅对只读或显式幂等工具执行 bounded retry + exponential backoff + jitter，并记录 attempt。
- **不确定结果治理**：非幂等写操作在“副作用可能成功但响应丢失”时进入 `unknown`，禁止 Agent 盲目重试；按 MCP Server 隔离熔断，避免单一依赖拖垮全部工具。
- **生命周期控制**：run deadline、协作式取消与 Stop 传播，确保取消后不再调度后续危险工具。
- **HITL + 沙箱**：危险工具调用走人工审批（`interrupt_on`）；文件系统与命令执行可隔离到 OpenSandbox，并通过租约续期保障长任务。

### 4. 评测闭环（最强差异化）
- 基于 **Langfuse dataset** 的评测，集成 **LLM-as-judge** 评分器（rubric judge）+ 确定性布尔评分。
- **Chaos eval**：对每个测试用例自动开启对应的 OpenTelemetry Demo 故障 flag（`kubectl patch` flagd ConfigMap）→ 等信号沉淀 → 跑 Agent（带 trace）→ 自动关闭 flag → 冷却。**串行执行**（flag 是集群级全局状态），且外层 `finally` 全程兜底 reset，崩溃/Ctrl-C 也不会留脏状态。

### 5. 可观测
- Langfuse tracing 贯穿 `/chat` 与 `/a2a` 两条协议链路，凭证缺失时自动降级为无操作，不阻断本地启动。

---

## 简历 Bullet（可直接粘贴 · 中文）

- **基于 DeepAgents / LangGraph 构建协议无关的统一 Agent Runtime 与 agent factory**，让同一后端同时对接 CopilotKit/AG-UI 流式聊天与 Google A2A JSON-RPC，两协议复用同一套模型/工具/Prompt/可观测配置，消除重复实现。
- **实现 MCP（Model Context Protocol）动态工具加载框架**，支持 stdio 本地与 streamable_http 认证远程两类传输，接入 Kubernetes/Prometheus/Jaeger/OpenSearch 等可观测工具；实现并发加载、per-server 超时与 required/optional 降级，提升工具接入的稳定性与可扩展性。
- **实现持久化可靠执行层**：以 `(run_id, tool_call_id)` journal + PostgreSQL advisory lock 去重工具调用，按工具幂等属性实施 bounded retry/backoff/jitter，按 MCP Server 熔断；对非幂等写入的模糊失败标记 `unknown` 而非盲目重试，并支持 deadline、取消与 Stop 传播。
- **为高风险工具调用设计 HITL 审批链路**，对命令执行、集群操作等危险动作强制人工确认；结合远程沙箱隔离与租约续期，降低 Agent 失控风险。
- **搭建基于 Langfuse dataset 的评测体系**，集成 LLM-as-judge 评分器；设计 chaos eval 流程——按用例自动注入 OpenTelemetry Demo 故障、等待信号稳定、运行 Agent、自动回收故障开关并全程兜底 reset，实现故障场景的可复现回归验证。
- **构建覆盖前后端的工程化验证链路**，通过 GitHub Actions 执行 Ruff、Pytest、Node test、TypeScript、ESLint 与 Vite build；仓库约 7.8k 行 Python、2.7k 行 TypeScript/JavaScript，包含 130 个测试函数。

## Resume Bullets (English)

- **Built a protocol-agnostic agent runtime on DeepAgents/LangGraph** with a single agent factory that serves both CopilotKit/AG-UI streaming chat and Google A2A (Agent2Agent) JSON-RPC, reusing one model/tool/prompt/observability config across both surfaces.
- **Implemented a dynamic MCP (Model Context Protocol) tool-loading framework** supporting local `stdio` and authenticated remote `streamable_http` transports (Kubernetes, Prometheus, Jaeger, OpenSearch); added concurrent loading, per-server timeouts, and required/optional degradation.
- **Built a durable tool-execution layer** using a `(run_id, tool_call_id)` journal and PostgreSQL advisory locks for deduplication; applied bounded retry/backoff/jitter only to retry-safe tools, isolated circuit breakers per MCP server, and surfaced ambiguous non-idempotent writes as `unknown` instead of retrying blindly.
- **Designed lifecycle and safety controls** including run deadlines, cooperative cancellation/Stop propagation, HITL approval for high-risk tools, and leased remote sandbox isolation.
- **Created a Langfuse-dataset evaluation suite with an LLM-as-judge grader**, plus a *chaos eval* loop that injects one OpenTelemetry-Demo fault flag per case (`kubectl patch` on the flagd ConfigMap), lets signals settle, runs the traced agent, and always resets flags in a `finally` guard for reproducible regression testing.
- **Added secret-free GitHub Actions CI** for Ruff, Pytest, Node tests, TypeScript, ESLint, and Vite builds; the repository contains ~7.8k lines of Python, ~2.7k lines of TypeScript/JavaScript, and 130 test functions.

---

## STAR 面试话术（口头展开）

- **S**：企业运维中，Agent 要接多种可观测工具、还要保证安全可控——直接让模型执行 kubectl / 查日志风险极高。
- **T**：构建一个可扩展、可评测、可安全上线的对话式 Agent 平台。
- **A**：用 LangGraph/DeepAgents 抽象统一 runtime；MCP 动态接工具；以持久化 journal、幂等分类、重试/熔断/deadline/取消约束工具执行；危险调用加 HITL；文件/命令进远程沙箱；Langfuse + chaos eval 建回归闭环。
- **R**：一套后端复用两种协议，关键状态可跨重启恢复，重复 tool call 复用结果，非幂等模糊失败不会盲目重放；130 个测试函数与 CI 覆盖关键链路。

---

## 深挖问题预案（面试大概率会问）

- **为什么用 MCP 而不是自己写 tool schema？** → 标准协议、工具与 Agent 解耦、可复用社区 server；再讲你做的并发加载/超时/降级增强。
- **chaos eval 为什么串行 / max_concurrency=1？** → flag 是集群级全局状态（patch 同一个 ConfigMap），并发会互相踩；串行 + 两层 finally reset 保证隔离与不留脏。
- **HITL 怎么实现的？** → LangGraph `interrupt_on`，对配置为 hitl 的工具名在执行前中断、等前端审批。
- **两协议怎么共享一个 agent？** → factory 只产出 graph/runtime，AG-UI 与 A2A 各自是 adapter，不复制业务逻辑。
- **LLM-as-judge 的可信度？** → 诚实说明：rubric judge 是辅助信号，配合确定性布尔评分；没有人工标注基线时不宣称「提升 X%」。
- **是否实现 Exactly Once？** → 没有夸大。系统实现调用去重、持久化结果和按幂等性分类的重试；跨外部副作用系统无法靠本地 journal 保证数学意义的 Exactly Once，模糊失败进入 `unknown`，生产闭环还需要外部 idempotency key 与 reconciliation。

---

## ⚠️ 必须避免的踩坑 / 夸大

- ❌ 「设计了生产级平台」——本项目无真实用户/权限/灰度/SLA/租户审计，写「生产导向的工程原型 / 个人项目」。
- ❌ 「实现 Exactly Once」——写「幂等去重 + 分类重试 + 不确定结果治理」，并明确外部系统仍需幂等键和对账。
- ❌ 「效果提升 XX%」——没有固定基线 + 人工标注 + 对照实验，不要写百分比。
- ❌ 只讲模型能力不讲工程约束——Agent 岗更看重可靠性/降级/超时/HITL/评测。
- ❌ 技术名词堆砌（LangGraph/MCP/A2A/Langfuse/OTel…）——每个都要能说清「为什么用、解决什么」。
- ❌ 把「集成/封装」写成「从零设计」——诚实用词。
- ❌ 过度强调前端——Agent 岗核心是 runtime/工具/可靠性/评测/协议。

---

## 事实核对（写简历时的可佐证数字）

| 指标 | 数值 | 来源 |
| --- | --- | --- |
| 后端代码量 | ~7,800 行 Python | `services/agent/src` |
| 前端/Runtime 代码量 | ~2,700 行 TypeScript / JavaScript | `apps/web/src`、`apps/copilot-runtime/src` |
| 测试用例 | 130 个测试函数 / 29 个测试文件 | `services/agent/tests`、`apps/**/**.test.mjs` |
| 已接入 MCP Server | 4 类（Kubernetes / Prometheus / Jaeger / OpenSearch） | `config/config.example.yaml` |
| 故障注入 flag | 13 个 fault flags | `eval/chaos.py: FAULT_FLAGS` |
| 评测用例 | 18 条（14 运维场景 + 4 冒烟） | `services/agent/eval/cases/*.yaml` |
| 双协议 | CopilotKit/AG-UI + Google A2A | `backend.py` / `a2a/` |

> 面试可如实说明规模：一个持续迭代、50+ commit 的个人项目，覆盖 Agent 平台从 runtime、状态持久化、可靠工具执行、安全、沙箱到评测的完整工程链路。计数是仓库快照，不要把代码量本身当作质量指标。

---

## 上简历前最后检查

当前已经具备可写入秋招简历的工程深度，但公开展示时还应满足：

- GitHub CI 全绿，README 中明确个人项目边界和 Exactly Once 语义边界。
- 仓库不得包含真实凭证、内部域名、员工邮箱或公司业务数据；发布前扫描当前树和完整 Git 历史。
- 最好再补一张架构图和一个 60–90 秒演示 GIF/视频，展示“发起会话 → MCP 调用 → 失败重试/熔断 → 重启后恢复”。这是当前最值得补的展示材料，不是继续堆功能。
- 面试时能够现场解释一次 `unknown` 状态为什么比自动重试更安全，以及 localStorage、Copilot event log、LangGraph checkpoint 各自保存什么。

# ops_pilot 提升 Roadmap（面向秋招 · Agent 开发岗）

> 目的：把项目从「可演示的高级原型」推进到「有生产工程闭环的 Agent 平台」，最大化面试说服力。
> 依据：LangGraph 官方文档（2025–2026）+ 业界实践 + 本仓库实测缺口。
> 定位诚实：仍是个人项目/工程原型，roadmap 描述的是「工程能力演进」，不是「已上线」。

企业能力基线、招聘样本和本项目差距的完整调研见 [从 Agent 框架应用到可运营生产系统](research/enterprise-agent-production-readiness.md)。

---

## 0. 现状能力盘点

**已扎实：** 协议无关统一 Runtime（CopilotKit/AG-UI + Google A2A 复用 factory）、MCP 动态工具加载（并发/超时/降级）、HITL 审批、Langfuse tracing、Eval 体系（dataset + LLM-as-judge + chaos 故障注入）、OpenSandbox 远程沙箱、Postgres checkpoint/A2A task/AG-UI event 分层持久化、自适应推理 + per-call 超时。

**代码实测原则：** 当前 runtime 优先组合 LangChain、DeepAgents、LangGraph 与 MCP adapter 的官方原语；下游幂等、对账和隔离熔断仍是 roadmap，不包装成已实现能力。

| 缺口 | 位置 | 影响 |
| --- | --- | --- |
| 可靠性指标尚未输出 | 已实现 deadline/cancel 与官方幂等工具 retry | 仍需 retry/cancel latency 的 OTel/Langfuse 信号 |
| 下游业务幂等键未标准化 | Runtime 不伪造 exactly-once；外部 MCP 未统一接收 key | 响应丢失时仍需 reconcile |
| 可靠性故障注入未进 CI | 5 个关键场景已有 deterministic tests | 尚未成为持续 Eval/发布门禁 |
| 无长期记忆 | runtime 注释 "long-term/semantic memory intentionally not configured" | 与普通 chatbot 无本质差别 |
| 无 CI | 无 `.github/workflows` | prompt/工具变更无回归门禁 |
| 前端零测试 | `apps/web` 无 test/spec | 无法保证关键链路 |
| 无上下文压缩/token 预算 | runtime | token 爆炸与成本失控风险 |
| 企业接入控制缺失 | 无鉴权、租户和完整审计 | 真正共享部署前必须补；个人项目暂不作为 P0 |

---

## 1. 三层提升方向（现状 → 目标 → 收益）

### Agent Runtime 层

| 方向 | 现状 → 目标 | 面试收益 | 优先级 |
| --- | --- | --- | --- |
| **统一 deadline + cancel** ⭐ | 首版已落地 AG-UI/A2A run controller → 继续传播剩余预算并补 cancel latency | 长任务可终止、资源可回收、状态可恢复 | P0 |
| **副作用幂等** ⭐ | 未实现 → 推进下游 idempotency key/reconcile contract | 证明恢复不会重复执行危险动作 | P0 |
| **分类重试 + 熔断** ⭐ | 官方 ToolRetryMiddleware 已用于显式幂等工具；依赖级熔断未实现 | 受控恢复与故障隔离 | P0 |
| **分层记忆** | 无 → short-term(checkpointer) + long-term(Store + pgvector 语义检索) | Agent vs Chatbot 分水岭 | P2 |
| 上下文管理 | 无压缩 → 滑动窗口 + 摘要 + 工具输出结构化去重 | 防 token 爆炸 | P1 |
| Token 预算/成本控制 | 仅 per-call timeout → 会话/租户级 token 硬上限 | 成本墙意识 | P2 |
| Guardrails | 仅 HITL → prompt injection 防护 + 越权工具拦截 + 敏感数据过滤 | 「可约束地跑」 | P2 |
| Prompt/tool/workflow 版本化 | 无 → 三者作为一个可回滚版本单元 | 生产行为治理 | P2 |

### 后端层

| 方向 | 现状 → 目标 | 优先级 |
| --- | --- | --- |
| 可靠执行协调 | 协议 adapter 直接调 graph → 统一 execution module | P0 |
| 故障注入 adapter | 只注入业务故障 → model/MCP/sandbox 瞬态故障与半执行故障 | P0 |
| 限流 / 配额 | 无 → 按用户/租户/工具 rate limit + token budget | P1 |
| OTel 标准化 | 仅 Langfuse → OpenTelemetry 统一 trace/log/metric（`telemetry/` 已占位） | P2 |
| 容器化 + 弹性 | 本地脚本 → Worker/API 分离 + durable queue + 沙箱池 | P2 |
| 鉴权 + 多租户 + 审计 | 无 → JWT/OIDC + tenant 隔离 + tool 级权限 + 审计账本 | P3（企业接入扩展） |

### 前端层

| 方向 | 现状 → 目标 | 优先级 |
| --- | --- | --- |
| **CI + Eval 回归门禁** ⭐ | 无 CI → 单测+集成+eval gate+安全扫描 | P0（跨层） |
| Generative UI / agent-native | 聊天窗 → 动态表单/步骤卡/告警树/变更预览 | P1 |
| 工具调用可视化 | 基础 renderers → 展示调用中工具/参数/结果摘要/降级状态 | P1 |
| HITL 交互升级 | 一个按钮 → 变更 diff + 风险等级 + 影响范围 + 回滚建议 | P1 |
| 流式体验 | → 增量输出 + 阶段状态 + 可中断/可恢复 | P2 |
| 前端测试 + a11y | 零测试 → Vitest 组件测试 + Playwright E2E；键盘/屏幕阅读器/焦点 | P1 |
| 性能 | → 长列表虚拟化 + 流式渲染节流 | P3 |

---

## 2. 优先级选择（性价比最高的 4 项）

若时间有限，做这 4 项最大化面试成果：

1. **统一 deadline + 取消传播** ⭐ — 先定义一次 run 如何受控结束，以及 model/tool/sandbox 如何共享剩余预算。
2. **副作用工具幂等** ⭐ — 为写工具增加稳定 idempotency key、执行状态和结果复用；这是安全重试的前提。
3. **分类重试 + 依赖级熔断** ⭐ — 只重试可恢复错误，按 model deployment/MCP server/sandbox 隔离熔断。
4. **可靠性故障注入 + CI Eval 门禁** — 验证不重复副作用、不重置 deadline、取消后可恢复、依赖失效时受控降级。

> 组合建议：把上述能力收敛到协议 adapter 与 graph 之间的统一 execution module，不要在 AG-UI、A2A、MCP 和 sandbox 各自堆重试逻辑。鉴权、多租户和完整审计是共享部署前置条件，但对个人项目降为 P3，先以文档说明边界。

---

## 3. 专项深挖：持久化 checkpoint + 任务恢复

### 3.1 核心概念澄清（LangGraph 官方模型）

LangGraph 有两个**正交**的持久化概念，不是「短期存哪、长期存哪」的二选一：

| 概念 | 存什么 | 键 | 用途 |
| --- | --- | --- | --- |
| **Checkpointer** | 每个 super-step 的**完整 state 快照** | `thread_id` | 会话连续性、HITL、time-travel、**崩溃恢复** |
| **Store (BaseStore)** | 跨 thread 的持久数据（用户偏好、历史工单、故障模式、语义记忆） | `namespace` + key | **long-term memory** |

**关键：Redis 与 Postgres 不是按「短期/长期」分工——checkpointer 和 store 各自都能选 Redis 或 Postgres 后端。**

### 3.2 官方 checkpointer 实现与选型

| 实现 | 包 | 适用 | 生产？ |
| --- | --- | --- | --- |
| `InMemorySaver`/`MemorySaver` | `langgraph-checkpoint` | 实验/调试（当前用的） | ❌ |
| `SqliteSaver`/`AsyncSqliteSaver` | `langgraph-checkpoint-sqlite` | 本地/单进程 | ⚠️ 轻量 |
| `PostgresSaver`/`AsyncPostgresSaver` | `langgraph-checkpoint-postgres` | **官方生产主线（LangSmith 同款）** | ✅ |
| `RedisSaver`/`AsyncRedisSaver`/`ShallowRedisSaver` | `langgraph-checkpoint-redis`（Redis 官方维护） | 会话 state 需 **TTL 自动过期** | ✅ |

### 3.3 关键澄清：checkpoint ≠ 聊天历史（生产分层）

一个常见的直觉困惑：「把会话历史实时写进关系型数据库，听起来很奇怪、会不会有性能问题？」——这个困惑源于把 **checkpoint（执行态）** 和 **聊天历史（业务数据）** 当成了一回事。它们在生产上是**两回事，不该用同一个数据模型**：

| | Checkpoint（执行态） | 聊天历史（业务数据） |
| --- | --- | --- |
| 目的 | 崩溃恢复、断点续跑、time-travel | UI 展示、分页、搜索、审计 |
| 内容 | graph state 快照 + 中间变量 + 路由信息 | 用户/助手消息、工具调用摘要 |
| 读写 | **写多读少**，按 super-step 追加 | **读多写多**，按会话检索/分页 |
| 保留 | 可定期清理（cron 删 N 天前旧 checkpoint） | 长期 / 合规保留 |

**为什么「实时写 DB」并不奇怪：**
- checkpoint 按 **super-step** 写，**不是按 token**。一轮 `model→tool→model` ≈ 2–3 次 checkpoint，比想象中轻得多。
- LangGraph 持久层是两张表：`checkpoints`（每 super-step 一行，`checkpoint` 为 BYTEA 快照）+ `writes`（每个节点输出一行，让同一 super-step 内失败节点可恢复、成功节点不重跑）。

**唯一真正要担心的是「写放大」，而不是「用了 Postgres」：**
- ⚠️ checkpoint **默认写全量 state 快照**。若把不断累积的 `messages` 全塞进 state，快照会越写越大（长对话可达 MB 级）。
- 解法：`DeltaChannel`（`langgraph>=1.2`，beta）对 append-heavy 通道只存增量，把 blob 从 O(N) 降到 O(1)/step；或上下文压缩（摘要 / 滑动窗口，见 §1 上下文管理）。
- 真正的瓶颈公式：**每次写入字节数 × 写入频率 × 并发事务数** —— 几十~几百 QPS 的 step 写入、payload 几十~几百 KB，现代 Postgres 稳妥；上千 QPS + 大 payload + 多索引才需分区/压缩/异步缓冲。

**生产分层（业界通用，大厂聊天产品也不是「一个库存一切」）：**
```
热路径（执行恢复）    → checkpointer（Postgres 权威 / Redis 热状态兜底）
业务历史（展示/审计） → messages 表（独立，读多写多，按会话分页）
长期记忆（检索）      → Store + pgvector
```
> 即使物理上都是同一个 Postgres 集群，也应在 schema / 生命周期 / 读写模式上分离：`checkpoints` 是运行时快照，`messages` / AG-UI events 是产品数据。本项目前端已不再把浏览器 localStorage 当作消息真相源；Copilot Runtime 通过独立的 Postgres 表保存 AG-UI event log，并用同一个 `thread_id` replay UI。localStorage 只保留当前 thread 选择与侧栏轻量元数据。

### 3.4 两条推荐架构

**路径 A：全 Postgres（官方最稳妥、最省事）** ✅ 生产完全可用
- `AsyncPostgresSaver`（checkpoint）+ `AsyncPostgresStore`（long-term，可加 pgvector 语义检索）。
- 官方生产主线、LangSmith 同款；一套后端、统一备份/权限/审计、恢复逻辑统一。
- **唯一前提**：控制 state 体积（别把全量历史塞进 state 每步写回），用 `DeltaChannel` 或上下文压缩即可 —— 这是任何后端都要做的，不是 Postgres 的短板。
- 适合：想快速补齐、不想引入第二套基础设施。**这是默认推荐起点。**

**路径 B：Redis(checkpoint) + Postgres(store)（更能讲工程取舍）**
- **Checkpointer → Redis**：`AsyncRedisSaver`，配 `ttl={"default_ttl": ..., "refresh_on_read": True}` —— 会话 state 自动过期，符合「短期」语义；或用 `ShallowRedisSaver` 只存最近快照省空间。
- **Store（长期记忆）→ Postgres + pgvector**：永久沉淀，语义检索。
- 注意：Redis 作 checkpointer 不是「write-heavy 银弹」——内存成本高、大对象频繁更新有复制/持久化压力、作「唯一真相来源」时故障恢复语义不如关系库清晰。它更适合「热状态 + 有持久化兜底」，而非无脑替代 Postgres。
- 适合：会话 state 有自然过期语义、追求低延迟、且能接受上面的取舍。

> 你的原始直觉「会话进 Redis / 长期进 Postgres」在路径 B 下成立；只需理解它是「checkpointer 用 Redis 后端、store 用 Postgres 后端」，而非「短期长期二选一」。**若只是快速补齐，路径 A 全 Postgres 就够了。**

### 3.5 任务恢复（durable execution）怎么工作

**resume 不靠内存对象续命，而靠「持久化 checkpoint + thread_id 重建执行现场」：**
- 正常执行：每个 super-step 结束写一个 checkpoint。
- 崩溃/重启后：用**同一个 `thread_id`** 再次 invoke 图 → LangGraph 从 checkpointer 读最后一个 checkpoint → 继续执行。
- HITL interrupt 后：thread 的 checkpoint 保留，用同 thread 继续往下跑。

### 3.6 落地步骤（本仓库）

> **状态：已落地（memory / postgres 两档）。** 下面记录实现方式与验证方法。

改动集中在 `services/agent/src/ops_pilot/agent/runtime.py`（checkpointer 工厂）+ `a2a/task_store.py`（A2A task store 工厂）+ `backend.py` / `a2a/app.py`（生命周期接线）。

1. **依赖**：`pyproject.toml` 增 `langgraph-checkpoint-postgres`、`psycopg[binary,pool]`，A2A 加 `postgresql` extra（`a2a-sdk[http-server,postgresql]`，引入 SQLAlchemy asyncpg）。
2. **配置**：`config.yaml` 增 `persistence:` 段（`backend: memory|postgres`、`setup_on_start`）；DSN 走 `.env` 的 `DATABASE_URL`（唯一密钥）。`settings.py` 解析并在 `backend=postgres` 却缺 `DATABASE_URL` 时 fail-fast；`sqlalchemy_database_url()`/`psycopg_database_url()` 两个归一化方法处理 `+asyncpg` 驱动后缀差异（SQLAlchemy 要、psycopg 不要）。
3. **checkpointer 工厂**：`_create_checkpointer(settings)` 返回 `(checkpointer, closer)`。memory→`MemorySaver`；postgres→长生命周期 `AsyncConnectionPool`（`autocommit=True`、`prepare_threshold=0`）+ `AsyncPostgresSaver` + 首启 `setup()` 建 `checkpoints`/`writes` 表。`closer` 在 `AgentRuntime.aclose()` 里关连接池。
4. **A2A task store 工厂**：`create_task_store(settings)` 返回 `(store, closer)`。memory→`InMemoryTaskStore`；postgres→`create_async_engine` + 官方 `DatabaseTaskStore` + `initialize()` 建 `tasks` 表。`closer` 在 app lifespan 关 engine。
5. **生命周期**：连接池/engine 进程级持有（不每请求新建），启动时建表，关闭时释放——`backend.py` 与 `a2a/app.py` 的 lifespan 各自 await closer。`use_memory_checkpointer` 布尔标志重命名为语义更准的 `attach_checkpointer`（graph.py 平台导出、eval 仍传 `False`，各自不挂 continuity checkpointer）。
6. **中间件容器化**：`deploy/postgres/`（`pgvector/pgvector:pg16`，host `127.0.0.1:5433`，healthcheck + 数据卷）。用 pgvector 镜像是为后续长期记忆 Store 复用同一实例。`docker compose up -d` 起库，`config.yaml` 切 `backend: postgres` + `.env` 填 `DATABASE_URL` 即启用。
7. **验证**：起 Postgres → 发消息 → 杀后端 → 同 `thread_id` 重连，对话/任务从 checkpoint 恢复。
8. **前端 / Copilot Runtime 对齐**：前端生成并稳定保存 UUID `threadId`，首次消息后将其标记为可恢复 thread；切换或刷新时由 `CopilotChat` 的 connect 流程 replay 服务端事件，不再 `agent.setMessages(localStorage)`。Copilot Runtime 增加 Postgres `AgentRunner`（`copilotkit_agent_runs` / `copilotkit_run_events` / `copilotkit_thread_locks`），与 LangGraph checkpoint 共用 `threadId` 但分表保存；`persistence.backend: memory` 时继续使用官方 `InMemoryAgentRunner`。
9. **测试**：`tests/unit/config/test_settings.py` 覆盖 persistence 解析/校验/URL 归一化；`tests/unit/agent/test_persistence.py` 覆盖两个工厂的 memory 档，Postgres 档的「写→重开→读恢复」集成测试用 `TEST_DATABASE_URL` 环境变量门禁（默认套件保持零外部依赖）。

### 3.7 生产注意点（官方 + 实践）

- **连接池**：高并发 Agent 服务禁止每请求新建连接；用 async saver 的连接池。
- **sync vs async 别混用**：AG-UI/FastAPI 是 async 栈 → 用 `AsyncPostgresSaver`/`AsyncRedisSaver`。
- **建表/迁移**：首次 `setup()` 建表；生产用受控 migration，不要每次启动 setup。
- **checkpoint 清理**：super-step 细则写库频繁 → Postgres 加 cron 删 N 天前旧 checkpoint；Redis 用 TTL 自动过期。
- **序列化演进**：长期运行 Agent 的 state schema 变更要考虑旧 checkpoint 反序列化兼容。
- **双层持久化**：LangGraph checkpoint 负责执行态恢复；Copilot `AgentRunner` 负责 AG-UI 事件 replay/浏览器重连。两层必须使用同一个稳定 `threadId`，但不能把其中一层误当作另一层。
- **备份恢复演练**：checkpoint 已是「可恢复系统」的一部分，DB 备份策略要和恢复流程一起验。

### 3.8 面试话术

- 「把 runtime 从内存态 demo 升级为可恢复的 durable execution：任务中断后按 checkpoint + thread_id 恢复，支持重试与审计。」
- 「checkpointer 存线程级 state 快照、store 存跨线程长期记忆——两个正交概念；checkpoint 用带 TTL 的 Redis 让会话自动过期，长期记忆用 Postgres+pgvector 做语义检索。」
- 追问「为什么不全用 Postgres？」→ 「全 Postgres 是官方最稳妥路径；我选 Redis 做 checkpoint 是因为会话 state 有自然过期语义，TTL + refresh_on_read 省去手动清理，且读写更快；长期记忆才需要 Postgres 的持久与检索。」

---

## 4. 时间线

| 阶段 | 内容 |
| --- | --- |
| **已完成首版** | run deadline/cancel、官方幂等工具重试、HITL、安全 grader 与 deterministic tests |
| **下一阶段** | 下游 idempotency key/reconcile contract + retry/cancel 指标 + fault adapter |
| **形成闭环** | 把可靠性场景接入 CI Eval；补 OTel 运行指标、上下文预算和 durable queue |
| **企业扩展** | 按真实部署需要增加 Auth/多租户/审计，不作为个人项目近期主线 |

---

## 5. 参考

- LangGraph Persistence / Checkpointers（官方）：checkpointer 存 super-step 快照，`PostgresSaver` 为生产推荐、LangSmith 同款；`setup()` 建表 + cron 清理。
- LangGraph Add Memory（官方）：`AsyncPostgresSaver` + `PostgresStore` 生产用法；checkpointer(short-term) 与 store(long-term) 同时使用。
- langgraph-checkpoint-redis（Redis 官方）：`RedisSaver`/`AsyncRedisSaver`/`ShallowRedisSaver` + TTL（`default_ttl`/`refresh_on_read`）；`RedisStore` 也支持 TTL。
- CopilotKit Threads / AgentRunner（官方）：显式稳定 `threadId` 驱动 history hydration 与 active-run reconnect；自托管 Runtime 必须配置持久 `AgentRunner`，LangGraph checkpointer 与 Copilot thread event history 是共享 ID 的两个独立层。

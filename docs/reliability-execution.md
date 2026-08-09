# Agent Runtime 可靠执行设计

> 实现范围：MCP 工具执行的幂等/分类重试/Server 级熔断，以及 AG-UI/A2A run 的 deadline/取消状态。  
> 核心代码：`services/agent/src/ops_pilot/reliability/`

## 1. 为什么 checkpoint 还不够

LangGraph checkpoint 在 super-step 边界保存 Agent state；节点已开始但未完成时，恢复可能从节点开头重新执行。官方因此要求副作用 task 自身具备幂等性。checkpoint 能恢复 messages、graph position 和 interrupt，但不知道外部系统是否已经完成了 `restart/create/update`。

本项目将状态分为两类：

| 状态 | 存储 | 解决的问题 |
| --- | --- | --- |
| Agent state | LangGraph checkpointer | 推理/图执行从哪里继续 |
| Tool execution state | execution journal | 外部副作用是否已经发生、结果能否复用 |

工具状态机：

```text
running → succeeded
        → failed
        → cancelled
        → unknown
```

`unknown` 是必要状态：连接在请求发出后断开时，客户端无法仅凭异常判断服务端是否已完成副作用。没有下游 idempotency key 或查询/对账能力时，正确策略是停止并核对，而不是自动重试。

## 2. 决策表：Runtime 重试、交给 Agent，还是停止核对

| 场景 | Runtime 行为 | 是否再调用 LLM | 原因 |
| --- | --- | --- | --- |
| 成功结果已写账本，响应随后断开 | 同一 `(run_id, tool_call_id)` 复用结果 | 否 | 这是重复传输，不是新的业务意图 |
| 429、502、503、504，且工具 read-only/idempotent | bounded retry + exponential backoff + jitter | 否 | 瞬态传输故障不需要模型重新规划 |
| 429/5xx，但写操作未声明 retry-safe | 不自动重试；返回错误或进入 `unknown` | 是/人工 | 防止重复副作用 |
| 参数校验、业务规则、工具返回 `isError` | `ToolMessage(status="error")` 返回 Agent | 是 | Agent 可以修参数、补信息或换工具 |
| 401/403、策略拒绝 | 不重试，返回 Agent/用户 | 是 | 重试不会改变权限事实 |
| timeout/connection reset 且副作用可能已提交 | `unknown`，要求 query/reconcile/人工确认 | 否 | 结果不确定，盲重试不安全 |
| 未知程序异常 | 记录 `failed` 并向上抛出 | 否 | 不让 LLM 掩盖实现缺陷 |
| MCP Server 连续瞬态失败 | 只打开该 Server 的 circuit | 可选择其他工具 | 隔离故障，避免全局 Agent 不可用 |

工具是否可自动重试按以下顺序判定：

1. MCP tool annotation 的 `readOnlyHint: true`；
2. MCP tool annotation 的 `idempotentHint: true`；
3. 本地配置中该 Server 的 `retry_tools` 显式声明。

`retry_tools` 不是“想重试的工具”，而是维护者对业务幂等语义的承诺。危险写工具不应仅因为返回 503 就加入列表。

## 3. 实现结构

```text
AG-UI stream ─┐
              ├─ RunController ─ deadline / cancel / terminal status
A2A invoke ───┘                         │
                                        ▼
LangGraph AgentMiddleware ── ReliableToolMiddleware
                                        │
                                        ▼
ReliableToolExecutor.execute(call, operation)
  ├─ execution journal: dedupe / result reuse / recovery
  ├─ retry classifier: retry-safe transient failures only
  └─ dependency circuit breaker: one state per MCP Server
                                        │
                                        ▼
                                  MCP tool handler
```

这个 Module 的公开 interface 很小：`RunController.run/iterate/cancel` 与 `ReliableToolExecutor.execute`。AG-UI、A2A 和 LangChain middleware 都是 adapter；重试顺序、状态迁移、重复抑制和熔断留在 implementation 内。

### Journal 后端

- `persistence.backend: memory`：进程内账本，适合本地开发；重启后不保留工具结果。
- `persistence.backend: postgres`：`ops_pilot_tool_executions` 持久表；结果使用 LangGraph `JsonPlusSerializer`，可恢复 `ToolMessage/Command` 等类型。
- Postgres 以 `(run_id, tool_call_id)` 为主键，并对该键持有 session-level advisory lock。并发重复调用会等待首次执行完成，进程崩溃时锁由连接释放。
- 恢复后若发现遗留 `running`：retry-safe 操作可以继续；非幂等写转为 `unknown`，不会重放。

当前建表沿用项目的 `persistence.setup_on_start`；正式部署应改为受控 migration。

## 4. 配置

```yaml
reliability:
  enabled: true
  run_deadline_seconds: 600
  max_attempts: 3
  initial_backoff_seconds: 0.25
  backoff_multiplier: 2.0
  jitter_ratio: 0.2
  failure_threshold: 5
  recovery_seconds: 30

mcpServers:
  prometheus:
    # ...transport config...
    retry_tools: [query_metrics]
```

重试次数包含第一次执行。backoff 带 jitter，避免多个 run 在依赖恢复时同步重试。circuit 使用 closed/open/half-open 状态，恢复窗口后只放一个 probe；状态按 MCP Server 隔离。

## 5. 五个故障场景的验收

| 场景 | 测试观察点 |
| --- | --- |
| 工具成功、响应返回前断开 | 恢复 executor 后复用第一次结果，副作用计数仍为 1 |
| 第一次 503、第二次成功 | 仅 retry-safe 工具自动重试，最终 `attempt == 2` |
| 同一 tool call 提交两次 | 第二个调用等待并复用第一个结果，handler 只执行一次 |
| 慢 MCP 期间 Stop | 在途 task 收到 cancellation，run=`cancelled`，后续危险动作不执行 |
| 一个 MCP Server 连续失败 | 只打开该 dependency 的 circuit，其他 Server 工具继续成功 |

行为测试位于：

- `services/agent/tests/unit/reliability/test_execution.py`
- `services/agent/tests/unit/reliability/test_run_controller.py`
- `services/agent/tests/unit/reliability/test_reliable_tool_middleware.py`
- Postgres 重开恢复测试：`services/agent/tests/unit/agent/test_persistence.py`（设置 `TEST_DATABASE_URL` 后运行）

## 6. 保证边界

本实现提供的是：

```text
at-least-once delivery
+ stable tool-call identity
+ duplicate suppression
+ persisted result reuse
+ unknown/reconciliation path
≈ effective-once behavior（在已声明的幂等契约内）
```

它不宣称跨任意外部系统的严格 exactly-once。若进程在下游完成写入后、账本写入前崩溃，只有以下方式能消除歧义：

1. 把同一个 idempotency key 传给下游，由下游原子地去重；
2. 用业务唯一键/desired state 设计成天然幂等的 upsert；
3. 提供 `get/status/reconcile` 工具查询结果；
4. 对不可核对的危险写操作进入人工处理。

当前 circuit 和 run snapshot 是单进程状态；Postgres 工具账本是跨进程状态。多副本部署若需要全局 circuit，应由共享 resilience store、service mesh 或网关承载。当前 deadline 会取消 Python/LangGraph/MCP await 链，但 MCP cancellation 是协作式协议：Server 可以已经完成，也可以忽略取消，所以取消不能替代副作用幂等。

## 7. 实践依据

- [LangGraph Functional API / idempotency](https://docs.langchain.com/oss/python/langgraph/functional-api#idempotency)：未完成 task 恢复时可能再次运行，副作用必须幂等。
- [LangGraph error handling](https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph)：瞬态错误由 Runtime retry；可由 LLM 修复的错误进入 state 返回模型；用户可修复错误使用 interrupt。
- [MCP cancellation](https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/cancellation)：取消是协作式 notification，必须处理“取消到达时请求已经完成”的竞态。
- [MCP tool error semantics](https://modelcontextprotocol.io/specification/2025-06-18/schema)：工具执行错误以 `isError` 结果返回，让模型能够自我修正；协议错误与工具错误需区分。
- [AWS Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)：稳定 client request ID、语义等价响应，以及 timeout 后的结果核对。
- [AWS Timeouts, retries and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)：bounded retry、backoff、jitter，以及重试放大故障的风险。
- [Stripe idempotency](https://stripe.com/blog/idempotency)：响应丢失后用相同 key 返回已缓存成功结果。
- [Azure Circuit Breaker pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker)：closed/open/half-open、恢复探针与依赖隔离。

# MCP、Langfuse 与 Chaos 官方实现对齐

本文记录 2026-08-15 的一次删除式重构。目标不是为 SDK 再包一层，而是明确每个生命周期由谁拥有。

## 结论

| 领域 | 官方能力 | 本项目保留 | 已删除 |
| --- | --- | --- | --- |
| MCP | `MultiServerMCPClient.get_tools()`；每次工具调用创建 session；`isError` 默认作为错误 ToolMessage 返回模型 | 配置解析、并发发现、required/optional、allowlist、HITL/retry 策略映射 | persistent session manager、generation/reconnect proxy、session owner/close 聚合、启动重试 |
| 工具重试 | LangChain `ToolRetryMiddleware` | 仅对 `retry_tools` 启用有界退避；run deadline/cancel | 自研 execution journal、Postgres advisory lock、retry middleware、circuit breaker、serde |
| HITL | DeepAgents `interrupt_on` + checkpointer；LangGraph v2 `result.interrupts` / `Command(resume=...)` | 生产 runtime 使用 HITL；自动 eval/chaos 显式 bypass；v2 结果遇 interrupt 不会被当最终回答 | 把 v1 `__interrupt__` 前的模型过渡文本当最终输出的隐式行为 |
| Langfuse | `get_client()` 单例、LangChain `CallbackHandler`、原生 async task/evaluator、SDK trace 传播 | 本地 YAML 同步为 dataset mirror；SDK experiment 与 evaluator；进程边界 flush/shutdown | 多 client、手工 OTel provider 引用计数、手工 span 包装、`run_coroutine_threadsafe` 跨 loop 桥 |
| OTel Demo chaos | flagd-ui `/feature/api/read` 与 `/feature/api/write` 完整文档 API；OFREP 数据面 | 每个 case 一个有界 port-forward、完整文档 lease、OFREP 连续稳定读、串行 case、精确恢复 | ConfigMap/live file 双写、kubectl 重试状态机、主动执行 MCP “健康探针”、重复恢复检查 |

## 为什么 MCP 不需要本地长连接层

LangChain MCP adapter 的官方示例明确说明：`get_tools()` 返回的工具在每次调用时建立新的
`ClientSession`；只有服务确实需要跨调用的有状态 session 时，才显式使用
`async with client.session(name)`。本项目的 Kubernetes、Prometheus、Jaeger、OpenSearch
工具调用不依赖跨调用 session 状态，因此采用默认生命周期更简单，也不会把工具绑定到创建
runtime 的 event loop。

来源：[langchain-mcp-adapters README](https://github.com/langchain-ai/langchain-mcp-adapters#multiple-mcp-servers)

## 为什么 Langfuse 不需要线程桥和私有 OTel 管理

Langfuse Experiment SDK 原生接受 async task 和 async evaluator，并通过 `max_concurrency`
控制并发。SDK v3+ 使用 `get_client()` 单例，LangChain 集成由官方 `CallbackHandler` 完成。
因此 eval task 可以直接是 async 函数；SDK 选择执行 loop，本项目不再把 coroutine 派发回
runtime 创建 loop，也不直接 shutdown 全局 OpenTelemetry provider。

来源：

- [Langfuse Experiments via SDK](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk)
- [Langfuse LangChain integration](https://langfuse.com/docs/integrations/langchain/tracing)

## 为什么 Chaos 只写 flagd-ui

OTel Demo 的 flagd-ui 官方 README 把 `/feature/api/read` 和 `/feature/api/write` 定义为供程序化
使用的 REST API，并说明 write 会替换完整配置。Kubernetes chart 的 ConfigMap 是部署输入，
运行中的 flagd 消费共享 live file。实验同时修改两者会把短期故障写进部署基线，还制造两个
需要回滚的一致性源。

现在的状态机只有一个权威运行态：

```text
load all MCPs → validate live catalog without mutation
  → for each serial case (one SDK-owned event loop and port-forward):
      read pre-case document → write clean baseline → OFREP confirms all faults off
      → write one fault → OFREP stable → run agent
      → finally restore exact pre-case document and original OFREP variant
```

Helm ConfigMap 从不在实验中修改；若 flagd Pod 重启，会回到部署基线，而不是重放实验故障。

来源：

- [OTel Demo flagd-ui programmatic API](https://github.com/open-telemetry/opentelemetry-demo/blob/main/src/flagd-ui/README.md#programmatic-use-through-the-api)
- [OTel Demo feature flags](https://opentelemetry.io/docs/demo/feature-flags/)

## 边界与未宣称能力

- 本项目没有 exactly-once 工具执行。非幂等写入需要下游幂等键或查询/对账接口。
- 自动 chaos 会 bypass HITL 以避免 experiment 悬停，所以只能用于隔离测试集群；
  `hitl_tools` 的 grader 是事后质量门禁，不等同于执行前阻断。
- MCP “加载成功”只证明 initialize/list tools 完成。case 的真实工具调用才验证运行期查询；
  runner 不再额外调用业务工具冒充健康探针。
- OFREP 证明 flag 已生效，不证明遥测已经入库。当前仍保留最小 warmup；下一步应为每类 fault
  增加具体 signal predicate。

## 验证策略

本次只运行离线 lint、类型检查和单元测试。按用户要求，没有启动 dev、eval 或真实 chaos，
也没有修改远程集群或 Langfuse 数据。

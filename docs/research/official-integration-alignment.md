# MCP、Langfuse 与 Chaos 官方实现对齐

本文记录 2026-08-15 的一次删除式重构。目标不是为 SDK 再包一层，而是明确每个生命周期由谁拥有。

## 结论

| 领域 | 官方能力 | 本项目保留 | 已删除 |
| --- | --- | --- | --- |
| MCP | `MultiServerMCPClient.get_tools()`；每次工具调用创建 session；`isError` 默认作为错误 ToolMessage 返回模型 | 配置解析、并发发现、required/optional、allowlist、HITL/retry 策略映射 | persistent session manager、generation/reconnect proxy、session owner/close 聚合、启动重试 |
| 运行保护 | LangChain `ModelCallLimitMiddleware`、`ToolCallLimitMiddleware`、`ToolRetryMiddleware` | 仅对 `retry_tools` 重试；协议级 run deadline/cancel | 自研 execution journal、Postgres advisory lock、retry middleware、circuit breaker、serde、无输入来源的 system-message 补丁 |
| HITL | DeepAgents `interrupt_on` + checkpointer；LangGraph v2 `result.interrupts` / `Command(resume=...)` | 生产 runtime 使用 HITL；自动 eval/chaos 显式 bypass；v2 结果遇 interrupt 不会被当最终回答 | 把 v1 `__interrupt__` 前的模型过渡文本当最终输出的隐式行为 |
| Langfuse | `get_client()` 单例、无参数 `CallbackHandler()`、原生 async task/evaluator、SDK trace 属性传播 | 本地 YAML 同步为 dataset mirror；SDK experiment 与 evaluator；短进程边界 flush | 多 client、手工 OTel provider 引用计数、手工 span 包装、`run_coroutine_threadsafe` 跨 loop 桥、共享 client 提前 shutdown |
| OTel Demo chaos | flagd-ui `/feature/api/read` 与 `/feature/api/write` 完整文档 API；OFREP 数据面 | 每个 case 一个有界 port-forward、完整文档 lease、OFREP 连续稳定读、串行 case、精确恢复 | ConfigMap/live file 双写、kubectl 重试状态机、主动执行 MCP “健康探针”、重复恢复检查 |

## 为什么 MCP 不需要本地长连接层

LangChain MCP adapter 的官方示例明确说明：`get_tools()` 返回的工具在每次调用时建立新的
`ClientSession`；只有服务确实需要跨调用的有状态 session 时，才显式使用
`async with client.session(name)`。本项目的 Kubernetes、Prometheus、Jaeger、OpenSearch
工具调用不依赖跨调用 session 状态，因此采用默认生命周期更简单，也不会把工具绑定到创建
runtime 的 event loop。

来源：[langchain-mcp-adapters README](https://github.com/langchain-ai/langchain-mcp-adapters#multiple-mcp-servers)

需要注意文档版本差异：DeepAgents customization 页面当前示例仍写成
`async with MultiServerMCPClient(...)`，但本项目锁定的 `langchain-mcp-adapters 0.3.1`
已经明确让 `__aenter__` 抛出 `NotImplementedError`，`get_tools()` 的 docstring 则明确每次
tool call 创建新 session。因此实现以已安装 adapter 的公开接口为准，不重新引入 context
manager 或本地 session owner。

## DeepAgents customization 审计

`create_deep_agent` 已经内置 filesystem、subagent、summarization、dangling tool-call repair、
prompt caching、skills、memory 与 HITL 的固定 middleware stack。项目不应复制这些能力。
本轮进一步做了两类替换：

- 删除 `NormalizeSystemMessagesMiddleware`。仓库没有任何生产代码向历史消息插入额外
  `SystemMessage`，它只有自己的构造型单测；DeepAgents 内置 middleware 已通过
  `request.system_message` 组合提示词。
- 使用官方 `ModelCallLimitMiddleware` 与 `ToolCallLimitMiddleware` 限制一次 run 的 model/tool
  调用次数；`ToolRetryMiddleware` 配置直接采用官方字段，并只重试显式 `retry_tools` 的
  `TimeoutError` / `ConnectionError`。

仍保留的 `RunController` 不是 agent middleware 的重复实现：它属于 CopilotKit/A2A 协议 seam，
负责外部 run id、整体 wall-clock deadline 和用户取消。远程 sandbox 的租约、工作区映射和 skill
上传同样没有 DeepAgents 的一一对应组件；底层文件/执行能力已经直接使用官方
`OpensandboxBackend`。

来源：

- [DeepAgents customization](https://docs.langchain.com/oss/python/deepagents/customization)
- [LangChain prebuilt middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)
- [DeepAgents production guardrails](https://docs.langchain.com/oss/python/deepagents/going-to-production)

## OpenSandbox provider 验证

本项目锁定并实际安装的 `deepagents-opensandbox 1.0.2` 提供
`OpensandboxProvider`，但它属于 `cli` extra，默认安装不会导出该类。进一步核对已安装源码后，
当前 provider 不能无损替换本项目的 sandbox 创建 seam：

- `get_or_create()` / `aget_or_create()` 将 `timeout` 强制转换为 `timedelta`，不支持
  OpenSandbox SDK 原生允许的 `timeout=None`。
- provider 只转发 resource limits，不转发 resource requests、entrypoint 和
  `disable_metrics`。
- 引入 provider 需要额外安装 `deepagents-cli`，而本项目不使用 DeepAgents CLI。

因此暂不增加这个依赖，也不保留“provider + direct SDK”双路径。项目继续使用官方
`SandboxSync.create()` 创建资源，并将其交给官方 `OpensandboxBackend`；项目代码只拥有
provider 尚未覆盖的 scope、workspace projection、skills sync、TTL renew 与资源参数策略。
如果 provider 后续覆盖这些能力，再用一次替换式迁移删除 direct lifecycle。

## 为什么 Langfuse 不需要线程桥和私有 OTel 管理

Langfuse Experiment SDK 原生接受 async task 和 async evaluator，并通过 `max_concurrency`
控制并发。SDK 使用 `get_client()` 单例，LangChain 集成由无参数 `CallbackHandler()` 完成。
因此 eval task 可以直接是 async 函数；SDK 选择执行 loop，本项目不再把 coroutine 派发回
runtime 创建 loop，也不直接 shutdown 全局 OpenTelemetry provider。

数据模型按官方约定收敛为：一次 agent 请求/一次 eval item 是一条 trace；model call 是
`generation`，tool call 是 `tool`，由 LangChain callback 自动嵌套；`thread_id` / A2A context
映射为 `session_id`。trace name 与 tags 保持稳定，environment 由 Langfuse client 的专用
`environment` 属性设置，不再同时塞进 tag 和普通 metadata。SDK callback 会把
`langfuse_session_id`、`langfuse_user_id`、`langfuse_trace_name`、`langfuse_tags` 转换为
trace-level attributes 并传播给所有 observations。

evaluation 保持官方三层语义：本地 YAML 是可审查的测试源，Langfuse Dataset 是协作镜像，
`run_experiment` 负责 offline experiment；item evaluators 产生 item scores，run evaluators 只做
聚合。线上 trace evaluator 不混入离线 chaos runner。

来源：

- [Langfuse Experiments via SDK](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk)
- [Langfuse LangChain integration](https://langfuse.com/docs/integrations/langchain/tracing)
- [Langfuse data model](https://langfuse.com/docs/observability/data-model)
- [Langfuse trace best practices](https://langfuse.com/docs/observability/best-practices)
- [Langfuse evaluation overview](https://langfuse.com/docs/evaluation/overview)

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

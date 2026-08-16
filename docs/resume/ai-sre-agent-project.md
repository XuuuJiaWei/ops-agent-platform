# OpsPilot：Eval 驱动的云原生故障诊断 Agent

## 项目定位

OpsPilot 解决的不是“如何跑一个 benchmark”，而是云原生故障调查中的真实工程
问题：on-call 需要在 Metrics、Logs、Traces、Kubernetes Events、Alerts 和
Topology 之间反复切换，依赖个人经验提出假设，容易产生重复查询、错误归因和
不可复核结论。项目构建可恢复的 SRE Agent Runtime Harness，由场景化 Skills、
分层 Memory 和只读可观测工具形成证据驱动调查链，再用 RCA100 作为离线验收环境。

项目名建议：`OpsPilot｜Eval 驱动的云原生故障诊断 Agent`

关键词：`Agent Runtime Harness`、`Context Engineering`、`Skills`、`Memory`、
`LangGraph Persistence`、`Tool Calling`、`Agent Observability`、`Agent Evaluation`、
`AIOps`、`Kubernetes`。

## 可直接写入简历

**项目简介**：面向 Kubernetes 微服务告警，构建可恢复、可观测、可评测的 SRE
故障诊断 Agent。将碎片化遥测转化为根因实体、故障类型、传播路径和数值证据，
并通过场景化 Skills、分层 Memory 与 Eval 门禁形成知识候选、验证、激活/回滚闭环。

**项目亮点**：

1. **Agent Runtime Harness**：基于 DeepAgents/LangGraph 官方生命周期统一组合模型、
   Tools、Middleware、Checkpointer、Store、Sandbox 与 Trace；将通用 runtime 与
   Web/RCA100/SRE domain 解耦，资源由 FastAPI lifespan/运行入口显式创建和关闭，
   支持 thread checkpoint、任务取消、断点续跑和执行回放。
2. **场景化 Skills 与分层 Memory**：从 RCA100 故障空间抽象 7 条可迁移调查路径，
   覆盖请求失败、延迟、资源饱和、依赖连通性、Kubernetes 可用性、流量异常和变更
   回归；通过 DeepAgents `SKILL.md` 渐进披露降低上下文噪声，并将 working、semantic、
   episodic、procedural memory 按生命周期分层，长期知识只读、版本化且经 Eval 后发布。
3. **AI-Ready 可观测工具**：建设 9 个基于 LangChain `@tool` + Pydantic Schema 的只读
   查询工具，统一 Metrics/Logs/Traces/Events/Alerts/Topology 的时间窗、实体和错误
   envelope；修复空值指标、非有限数值和越界时间窗导致的 worker 崩溃，将错误转化为
   可判定、不可重试的 observation，避免依靠提高 recursion limit 掩盖无限调用。
4. **可恢复 Benchmark Harness**：每个 case 作为独立故障域原子落盘，artifact 绑定
   dataset root、任务集 SHA 和知识 variant；`--resume` 跳过成功项、只重跑失败项，
   模型异常保留有界诊断，避免分组中断后重复消耗全部 Token。
5. **Eval 驱动反馈闭环**：记录逐轮模型/工具调用、Token、耗时及参数/结果指纹，按
   Entity/Fault/Process/Final 与执行成本做同组对照；失败 Trace 只生成候选知识，
   必须满足完成、解析、评分 100% 且质量分量不回退才激活，支持 hold/rollback 和版本复现。
6. **量化验证**：在 6 个跨场景 RCA100 case 上完成 12 次 baseline/candidate 对照，
   两组完成率、解析率、评分覆盖率均为 **100%**。场景知识使平均模型调用下降
   **20.19%**、工具调用下降 **14.66%**、Token 下降 **33.16%**、时延下降
   **27.42%**，Fault/Process 分别提升 **16.67/2.78 个百分点**；同时门禁发现
   Entity 下降 **16.67 个百分点**、Final 下降 **0.83 个百分点**，自动判定回滚，
   阻止“成本优化但质量退化”的知识版本上线。

## 面试时如何讲这组结果

这不是一组“全都变好”的包装数据，而是一次完整的 Agent 工程闭环：

- baseline 和 candidate 使用相同模型、system prompt、工具、任务顺序和 timeout；
  唯一变量是 Skills/Memory profile。
- candidate 的平均成本显著下降，说明渐进披露和场景 SOP 缩短了搜索路径；但知识也
  让 t103 走向错误的因果分支，导致总体质量轻微回退。
- Evaluator 没有因为 Token 更低就激活候选，而是按质量分量给出 `rollback`。
- 根据失败 Trace 形成 context-v2 候选；它使 t103 从 v1 的 0% 恢复到 26.67%，但仍
  低于 baseline 40%，所以再次回滚。这说明闭环能工作，也说明后续必须用独立 holdout，
  不能继续对 smoke set 过拟合。

因此最有价值的百分比不是虚构的“准确率大幅提升”，而是：**100% 可恢复完成，成本
下降 14.66%～33.16%，并由 Eval 门禁准确拦截 0.83 pp 的总体质量回退。** 这对应生产
Agent 的真实痛点——知识更新需要可追踪、可验证、可回滚，而不是让模型在线自改 prompt。

## 六例对照明细

| 指标 | Baseline | context-v1 | 变化 |
| --- | ---: | ---: | ---: |
| Completion / Parse / Eval coverage | 100% / 100% / 100% | 100% / 100% / 100% | 持平 |
| Entity F1 | 50.00% | 33.33% | -16.67 pp |
| Fault score | 0.00% | 16.67% | +16.67 pp |
| Process score | 0.00% | 2.78% | +2.78 pp |
| Final score | 20.00% | 19.17% | -0.83 pp |
| Mean model calls | 17.33 | 13.83 | -20.19% |
| Mean tool calls | 38.67 | 33.00 | -14.66% |
| Mean total tokens | 565,461 | 377,970 | -33.16% |
| Mean elapsed | 77.93 s | 56.56 s | -27.42% |

实验任务为 `t001/t065/t073/t084/t091/t103`，只代表六例跨场景工程验证，不宣称
RCA100 全量准确率或生产 MTTR。answer key 位于 Agent 进程之外，只有 Agent 退出后
Evaluator 才读取；Skills/Memory 不含 task id、服务名、答案标签或精确 checkpoint。

## 设计依据

- [Google SRE：AI Engineering for Reliable Operations](https://sre.google/resources/practices-and-processes/ai-engineering-reliable-operations/)：
  用服务知识、历史事件、当前上下文与可观测数据降低故障调查认知负担。
- [Google SRE：Effective Troubleshooting](https://sre.google/sre-book/effective-troubleshooting/)：
  从观测建立可证伪假设，区分相关性、传播影响与真正原因。
- [DeepAgents Skills](https://docs.langchain.com/oss/python/deepagents/skills)：
  通过元数据发现和按需读取实现过程知识渐进披露。
- [DeepAgents Memory](https://docs.langchain.com/oss/python/deepagents/memory)：
  使用 `AGENTS.md` 持久化语义记忆，并按作用域和写入时机管理长期知识。
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：
  通过 thread/checkpoint/store 支持恢复、回放和跨线程记忆。
- [LangSmith Evaluation](https://docs.langchain.com/langsmith/evaluation)：
  将生产 Trace 回流数据集，对候选版本执行离线、在线和对照评测。
- [Anthropic：Context Engineering for Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)：
  以有限上下文、少量高价值工具、结构化记录和渐进披露减少上下文腐化。

## 可核验证据

| 主张 | 代码/产物 |
| --- | --- |
| Host-neutral runtime 与生命周期 | `services/agent/src/ops_pilot/agent/runtime.py` |
| SRE 知识 profile 与只读 backend | `services/platform/src/ops_pilot_platform/sre/knowledge.py` |
| 7 个场景 Skills / 分层 Memory | `services/platform/src/ops_pilot_platform/sre/knowledge/` |
| 9 个观测工具与结构化错误 | `services/platform/src/ops_pilot_platform/benchmarks/rca100_tools.py` |
| 原子 checkpoint / resume | `benchmarks/rca100/src/rca100_benchmark/runner.py` |
| 确定性比较与激活门禁 | `benchmarks/rca100/src/rca100_benchmark/feedback.py` |
| 六例原始结果 | `artifacts/rca100/2026-08-17-six-{baseline,context-v1}.json` |
| 对照与 rollback 决策 | `artifacts/rca100/2026-08-17-six-comparison.json` |

`artifacts/` 默认不提交，避免把大体积 Trace 或环境信息带入仓库；实验命令和指标口径
保存在架构文档与 benchmark README 中，可以在相同 dataset/task/variant 上复现。

## 下一轮正确方向

1. 将 RCA100 划为 candidate-generation、validation 和 holdout，禁止同一 case 既归因
   又决定激活；六例 smoke 只验证系统闭环，不继续人工调参。
2. 将失败 Trace 归一为脱敏 incident record，按环境/服务作用域去重；只有跨 case
   复现的规律进入 semantic/episodic memory 候选。
3. 增加 trajectory evaluator，评价工具选择、参数有效率、重复查询率和证据充分性，
   让“为什么分数变化”比只看 final answer 更可解释。
4. 全量 103 例运行后再报告均值、P50/P95、bootstrap 置信区间和按场景分层指标；接入
   生产后改用 MTTR、误报率、人工接管率和无效查询率验证业务价值。

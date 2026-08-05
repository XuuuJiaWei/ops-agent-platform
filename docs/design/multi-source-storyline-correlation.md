# 多源关联故障叙事（Storyline）设计方案

> 状态：设计草案（Draft）
> 作者：ops_pilot 团队
> 最后更新：2026-08-04
> 关联能力：Dynatrace Managed（指标/事件/问题，只读）+ Kibana/Elasticsearch（日志，只读）

## 1. 背景与目标

### 1.1 一句话定义

给定一个故障线索（一个 Dynatrace problem、一个受影响的 service/pod，或一段时间窗），agent 自动从 **Dynatrace（指标、事件、问题）** 与 **Kibana（应用日志）** 两个只读数据源拉取信号，**在同一时间窗内、围绕同一批实体对齐**，产出一条按因果/时间排序的**故障叙事（storyline）**：从最早的诱因，到中间的连锁反应，到最终对用户可见的告警，并附上每一步的证据链。

### 1.2 为什么做这个

- 对标 GitHub AIOps 趋势中 keephq/keep、HolmesGPT 的核心卖点：**事件关联（alert correlation）+ LLM 根因叙事**，而非单点告警。
- 命中秋招 JD 反复出现的关键词：**事件关联、告警收敛、根因分析、多源数据对齐**。
- 复用 ops_pilot 已有骨架（DeepAgents runtime + MCP 工具加载 + HITL + Langfuse），把"能接工具的 agent 平台"收敛成"一个能做多源根因分析的 SRE Copilot"。

### 1.3 关键约束（来自真实环境验证）

以下结论来自 2026-08-04 对 Frankfurt Dynatrace Managed 环境（`scv2-emea02-cns-p1`，v1.328.0）的真实调用：

| 约束 | 事实 | 对设计的影响 |
|---|---|---|
| **全部只读** | 可用 scope：`ReadLogContent, ReadEvents, ReadProblems, ReadSecurityProblems, ReadSLO, DataExport, ReadConfig, ReadSyntheticData` | storyline 只做"感知→关联→分析"，**不做执行/自愈**；任何写操作走 HITL 人工确认（当前不在范围内）。 |
| **Dynatrace 日志查询被拒** | 尽管 scope 含 `ReadLogContent`，实际 `query_logs` 返回 **403 Forbidden** | **日志源只能用 Kibana**。这不是设计选择，是权限现实——Dynatrace 负责指标/事件/问题，Kibana 负责日志，分工天然清晰。 |
| **Kibana 已可用（临时 cookie）** | Kibana 9.2.4 / ECS 8.0.0，55 个 data view，经 Console proxy 实拉验证 `filebeat-*`、`istio.mesh.access_logs*` 等索引可查（详见 §2.3） | Kibana 从"待接入"升级为"已验证"。日志字段结构已确认，`trace.id`、`kubernetes.labels.app`、`availability_zone` 等关联锚点真实存在。cookie 为临时凭证，正式只读权限到位后仅需换凭证，不改架构。 |
| **数据量巨大** | 10028 problems / 1,035,471 events / 2826 services（单环境、近期） | 关联**必须先收敛再分析**：先用时间窗 + 实体选择器把候选集缩到几十条，再交给 LLM，绝不能把百万级 events 灌给模型。 |

---

## 2. 输入（Input）

storyline 支持三种触发入口，对应用户答复中确认的"实体为轴 + 时间窗，也支持 problem 时间轴"：

### 2.1 触发模式

| 模式 | 触发输入 | 典型用户话术 | 主轴 |
|---|---|---|---|
| **A. 实体为轴**（主） | `entityId` 或 `serviceName` + 时间窗 | "event-service 最近半小时出什么事了？" | 锁定实体 → 拉该实体在窗内的所有信号 |
| **B. Problem 为轴** | `problemId`（如 `P-26081079`） | "P-26081082 到底怎么回事？" | 以 problem 为起点 → 顺 evidence/相关实体展开 |
| **C. 时间窗为轴** | 只给时间窗（+可选 managementZone/tag） | "13:00 到 13:15 集群发生了什么？" | 框定窗口 → 窗内所有信号堆叠 → 聚类分组 |

### 2.2 统一输入契约

无论哪种模式，内部归一化为同一个查询上下文：

```python
@dataclass(frozen=True)
class StorylineQuery:
    # 时间窗（三选一转成绝对区间）
    time_from: str            # ISO 或相对，如 "now-30m"
    time_to: str              # 通常 "now"

    # 实体范围（模式 A 必填；模式 B/C 可由展开推导）
    entity_ids: tuple[str, ...] = ()       # Dynatrace entityId，如 SERVICE-00043C842DF531B3
    service_names: tuple[str, ...] = ()    # 便于 Kibana 侧按服务名过滤

    # 收敛过滤器（对齐 Dynatrace 真实字段）
    management_zones: tuple[str, ...] = ()  # 如 "critical-component"
    entity_tags: tuple[str, ...] = ()       # 如 "critical-component:event-service"

    # 起点（模式 B）
    seed_problem_id: str | None = None

    # 预算控制
    max_problems: int = 50
    max_events: int = 200
    max_log_lines: int = 100
```

### 2.3 各数据源的真实输入形态

#### Dynatrace（已验证可用）

时间窗用相对语法（`now-30m` / `now`）或 epoch ms。实体用 entitySelector（**每次查询只能含一个 entity type**）：

```
# 模式 A：锁定实体的问题
list_problems(entitySelector='entityId("SERVICE-00043C842DF531B3")',
              from="now-30m", to="now", status="OPEN", sort="-startTime")

# 模式 C：按 managementZone 框定
list_problems(mzSelector='mzName("critical-component")', from="now-30m")

# 事件（K8s 层信号：容器重启、探针失败、镜像拉取、HPA 打满）
list_events(entitySelector='entityId("...")', from="now-30m", to="now")

# 问题详情（含 evidenceDetails + correlationId + rootcause 标记）
get_problem_details(problemId="-6147706316040825713_1785848524236V2")

# 指标（佐证：GC 时间、响应时间、CPU）
query_metrics_data(metricSelector="builtin:service.response.time",
                   entitySelector='entityId("...")', from="now-30m", resolution="1m")
```

#### Kibana / Elasticsearch（已验证可用 — v9.2.4，ECS 8.0.0）

2026-08-05 通过 Kibana Console proxy 实拉验证：环境为 **Kibana 9.2.4**，空间 `cxm-sales-and-service-cloud-monitoring`，共 55 个 data view。经采样确认，对 storyline 最有价值的三个索引及其**真实字段结构**如下。

**① `filebeat-*`（K8s 容器/应用日志 — 实体轴对齐主索引）**

真实文档字段（采样自 `.ds-filebeat-9.2.4-*`）：

| 字段 | 样例值 | 用途 |
|---|---|---|
| `@timestamp` | `2026-08-05T02:09:52.023Z`（ISO8601） | 时间轴对齐 |
| `message` | 业务日志正文（当前被 `[DROP]` 脱敏，后续放开给 LLM） | 叙事/根因证据 |
| `kubernetes.labels.app` | `flags-favorites-tags-service` | **按服务名过滤（实体轴）** |
| `kubernetes.pod.name` | `flags-favorites-tags-service-775695dd4-7lkgt` | Pod 级定位 |
| `kubernetes.container.name` | `flags-favorites-tags-service` | 容器定位 |
| `kubernetes.namespace` | `cxm-app` | 命名空间 |
| `kubernetes.node.name` | `ip-10-2-111-184.eu-central-1.compute.internal` | 节点定位 |
| `availability_zone` | `eu-central-1b` | **对齐 Dynatrace `AZAnomalyIdentified`** |
| `labels.kubernetes.cluster` | `prod-frankfurt` | 集群区分（prod vs pre-prod）|
| `stream` | `stdout` / `stderr` | 粗分级（stderr 常为错误）|
| `container.image.name` | `.../flags-favorites-tags-service:6ee2d55...` | 关联部署/变更 |

> ⚠️ **没有独立的 `log.level` 字段**（应用日志的 level 往往内嵌在 `message` 里）。所以严重度分级不能靠 `terms: log.level`，需 **①按 `stream:stderr` 粗筛 + ②对 `message` 做正则/LLM 抽取 level**。这是与原设计假设的关键差异。
>
> 🔗 **两源物理锚点**：filebeat 文档里存在 `kubernetes.namespace_labels.dynakube_internal_dynatrace_com/instance: "dynakube"` —— 证明**同一批 Pod 同时被 Dynatrace（dynakube OneAgent）和 filebeat 采集**。两源天然指向同一实体，实体轴对齐有物理基础，而非靠名字模糊匹配。

**② `com.sap.cxm.istio.mesh.access_logs*`（istio 网格调用日志 — trace 贯通 + 服务依赖）**

真实字段（采样自 `.ds-com.sap.cxm.istio.mesh.access_logs-*`）：

| 字段 | 样例值 | 用途 |
|---|---|---|
| **`trace.id`** | `75ce2c274babe666236d3126a3db626b` | **贯通 Dynatrace 调用链的关键锚点** |
| `traceparent` | `00-75ce2c27...-c79441b81848d33f-01`（W3C） | 分布式追踪上下文 |
| `kubernetes.labels.app` | `event-consumer` | **正是 Dynatrace `LongJAVAGCTime` 根因的同一服务** |
| `kubernetes.pod.name` | `event-consumer-129` | Pod 定位 |
| `authority` / `upstream_cluster` | `change-history-svc:50051` / `outbound\|50051\|\|change-history-svc...` | **服务依赖拓扑** |
| `response_code` / `response_flags` | `200` / `-` | 调用成败（5xx / `UF`/`UO` 等标志定位失败）|
| `duration` / `bytes_sent` | `7`（ms） | 延迟佐证 |
| `method` / `path` / `protocol` | `POST` / `/...EventService/notify` / `HTTP/2` | 调用语义 |
| `traffic_direction` | `outbound` / `inbound` | 调用方向 |

> 🔗 **trace.id 是原设计"假设"的能力，现已确认真实存在**。它让日志-调用链关联从"靠时间邻近猜"升级为"靠 trace.id 精确贯通"，关联置信度大幅提升。

**统一查询形态**（ES `_search` DSL，实拉验证可用）：

```json
POST /filebeat-*/_search
{
  "size": 100,
  "sort": [{ "@timestamp": "asc" }],
  "query": {
    "bool": {
      "filter": [
        { "range": { "@timestamp": { "gte": "2026-08-04T13:00:00Z", "lte": "2026-08-04T13:15:00Z" } } },
        { "terms": { "kubernetes.labels.app": ["event-consumer"] } },
        { "term":  { "labels.kubernetes.cluster": "prod-frankfurt" } }
      ]
    }
  },
  "_source": ["@timestamp", "message", "stream", "kubernetes.pod.name",
              "kubernetes.container.name", "availability_zone"]
}
```

istio 网格日志按 trace.id 精确捞（服务依赖 + 失败调用）：

```json
POST /com.sap.cxm.istio.mesh.access_logs*/_search
{
  "size": 100, "sort": [{ "@timestamp": "asc" }],
  "query": { "bool": { "filter": [
    { "range": { "@timestamp": { "gte": "...", "lte": "..." } } },
    { "terms": { "kubernetes.labels.app": ["event-consumer"] } }
  ] } },
  "_source": ["@timestamp", "trace.id", "authority", "upstream_cluster",
              "response_code", "response_flags", "duration", "kubernetes.pod.name"]
}
```

> **时间窗对齐**：Dynatrace 的 `startTime` 是 **epoch 毫秒**（`1785848524236`），Kibana `@timestamp` 是 **ISO8601**。适配层归一到 **UTC epoch ms**（istio 日志的 `sort` 值本身就是 epoch ms，如 `1785895795658`），左右各留 ±30s 缓冲吸收时钟偏移。

**其它相关 data view**（备用/扩展）：`com.sap.cxm.access-log*`（应用访问日志）、`com.sap.cxm.eventservice.metrics*`（event-service 专属指标）、`jenkins-logs*` / `container.image.name`（关联部署变更）、`traces-apm*`（APM 调用链，可与 istio trace.id 互补）。

### 2.4 真实跨源关联样例（event-consumer，实拉验证）

> 本节是 2026-08-05 用真实数据跑通的验证记录，非虚构。目的是证明"Dynatrace problem/event + Kibana istio trace.id 在同窗同实体对齐"的关联逻辑成立，并暴露真实的边界。所有 ID / trace.id / 时间戳均为环境真实值。

#### 验证步骤（可复现）

1. **实体发现**：`discover_entities(entityName.contains("event-consumer"))` → Dynatrace 侧 2 个 SERVICE、多个 CLOUD_APPLICATION；Kibana 侧 `kubernetes.labels.app: "event-consumer"`（StatefulSet，pod 名形如 `event-consumer-56`）。两源命中同一逻辑服务。
2. **框定时间窗**：Dynatrace `list_problems` 发现 `2026-08-05 01:47:11` 起一批 `LongJAVAGCTime`（20min 窗口）。取窗口 `01:47–02:22`。
3. **Kibana 同窗捞失败调用**（先做噪声收敛）：event-consumer 在窗内非-200 调用共 **132 条**，聚合后发现 **126 条是 401/404 打向 `169.254.169.254`（云元数据服务）——SDK 探测噪声，应过滤**；真正的故障信号是 **6 条 503**。
4. **锁定 6 条 503**：`01:48:25–01:51:34`，三个 pod（`event-consumer-56/19/144`）`POST /event-consumer/refresh` 到内部 `:8080`，全部 `503`，`response_flags: URX,UF`（UF = Upstream Failure，上游连接失败），各带独立 `trace.id`（如 `e98ddcdf2fe934599f100a1abefd1335`）。
5. **对齐**：503 起始 `01:48:25` 落在 LongJAVAGCTime 窗口（`01:47:11` 起）内 → **时间对齐成立**；同属 event-consumer → **实体对齐成立**。

#### 关联结果（真实节点）

| ts (UTC) | 源 | 信号 | 证据 | role |
|---|---|---|---|---|
| 01:47:11 | dynatrace_problem | LongJAVAGCTime（20min） | correlationId, `is_rootcause_relevant:true` | trigger（候选）|
| 01:48:25 | kibana_log | 503 `URX,UF` `/event-consumer/refresh` | trace `e98ddcdf...`, pod `event-consumer-56` | propagation |
| 01:49:27 | kibana_log | 503 `URX,UF` | trace `aadf0309...`, pod `event-consumer-19` | propagation |
| 01:51:34 | kibana_log | 503 `URX,UF` | trace `dea6ae86...`, pod `event-consumer-144` | propagation |

**叙事（示意）**：01:47 event-consumer 集群出现长 GC 停顿；约 1 分钟后，多个 event-consumer pod 的 `/event-consumer/refresh` 上游调用因连接失败（URX,UF）返回 503，且横跨 3 个 pod → 指向共性的上游依赖不可达 / GC 停顿导致的连接超时，而非单 pod 问题。

#### 这次验证证明了什么

- ✅ **两源能在同窗同实体对齐**：Dynatrace problem 时间窗 + Kibana 按 `kubernetes.labels.app` 过滤，时间与实体双维度都对得上。
- ✅ **trace.id 真实可用**：每条失败调用都带 trace.id，可反查整条调用链（验证中用 `18bd6745...` 反查，命中同 trace 的多跳）。
- ✅ **`response_flags` 是强信号**：`URX,UF` 直接点出"上游连接失败"，比纯文本日志更结构化、更适合确定性打分。

#### 这次验证暴露的真实边界（已写入 §8/§9）

- ⚠️ **噪声收敛是刚需**：132 条非-200 里 95% 是元数据服务探测噪声。**必须先按 `authority` / `path` / `response_code` 过滤**，否则 LLM 会被噪声淹没。这印证了"先收敛再分析"不是可选优化。
- ⚠️ **两源保留期不一致**：07-25 那批**确有 event-consumer Dynatrace problem** 的窗口，istio 日志已因 retention 滚掉（仅剩 2 条）。**Dynatrace problem 保留远长于 Kibana 热日志**——关联窗口受限于较短的一方，超出范围时日志侧只能标 `gap`。
- ⚠️ **Dynatrace 实体粒度 ≠ pod 粒度**：同窗的 LongJAVAGCTime 受影响实体是 `ana-data-service`（CLOUD_APPLICATION），event-consumer 的 503 需靠**时间+管理域（`critical-component` / `Event Service and Consumer`）**关联，而非直接实体 ID 相等。关联打分必须支持"拓扑/管理域邻近"，不能只做 entityId 精确匹配。

### 2.5 真实故障级联样例（GC 级联，实拉验证 + 端到端跑通）

> 本节是 2026-08-05 用真实数据 + 真实 SAP AI Core 模型**端到端跑通**的验证记录。相比 §2.4（单一实体、Kibana 为主），本例是一条**多问题、跨层级、跨源**的完整因果级联，也是驱动 workflow 关联能力从"entityId 精确匹配"升级到"因果分层 + 跨粒度链接"的 target case。

#### 黄金窗口：`2026-08-05 01:45–03:00 UTC`

Dynatrace 侧在此窗口炸出一条教科书式的级联，与 Kibana 侧 `document-scan-worker-service` 的 **168 条业务 503（集中在 02:00）** 时间精确对齐：

| 时间 (UTC) | 信号 | 源 | 层级 | 因果角色 |
|---|---|---|---|---|
| 01:27 | KafkaPartitionStuck | dynatrace | INFRA | context |
| 01:32–01:47 | **LongJAVAGCTime** ×多个 | dynatrace | INFRA | **trigger（根因）** |
| 01:44 | High CPU throttling | dynatrace | INFRA | propagation |
| 01:48 | Response time degradation | dynatrace | SERVICES | propagation |
| 02:00 | **document-scan-worker 168×503** | kibana | — | propagation |
| 02:10 | Failure rate increase（持续到 04:37） | dynatrace | SERVICES | propagation |
| 01:47 | LongJAVAGCTime → **ENVIRONMENT** | dynatrace | ENV | symptom |

**端到端结果**（`run_storyline`，真实工具 + 真实模型）：45 节点（15 Dynatrace problem + 30 Kibana log），root_cause 正确判定为 **LongJAVAGCTime（causal_tier=0）**，角色分布 1 trigger / 39 propagation / 5 symptom，LLM 叙事从"GC 内存压力"讲起。

#### 这次验证驱动的三项能力升级（已实现）

1. **Dynatrace adapter 重写**：真实 MCP server 的 `list_problems` 返回**人类可读文本**（非 JSON）、且**强制要求 `environment_alias`**（我们用 `ALL_ENVIRONMENTS`）。改为两段式：解析文本列表 → 对候选调 `get_problem_details` 取 JSON 富字段（affectedEntities / managementZones / entityTags / evidenceDetails）。**这修复了之前 Dynatrace 侧一直 0 problem 的真 bug**（缺 `environment_alias` 参数导致每次校验失败）。
2. **因果分层选根因**：signal 按故障级联分 4 层（资源耗尽 → 基础设施连锁 → 服务错误 → 环境表征）。trigger 由**因果位置**决定，而非"最早"或 Dynatrace 自己标的 `is_rootcause_relevant`——因为 Dynatrace 会把晚发的 kafka-lag 也标成 rootcause，纯信它会误判。`is_rootcause_relevant` 只用于**同层内**打破平局。
3. **候选截断按 tier 而非时间**：`max_problems` 上限截断前，先按因果层排序保留最接近根因的信号，**杜绝 GC 根因被更晚、更多的下游 problem（kafka-lag / mongo alert）挤出候选集**。

#### 这次验证暴露的真实边界（诚实记录）

- ⚠️ **两源未必在同一 service 显现**：GC 级联的内部影响（处理停顿）不一定体现在 istio **出向调用** 5xx 上——`c4cadapter-replication-service` 有 GC problem 但只有 6 条业务 5xx。"同窗同 service 双源都有信号"是可遇不可求的，多数真实故障要靠**因果类型 + 时间邻近**跨源关联，而非硬要求两源指向同一实体。
- ⚠️ **`/metrics` 抓取失败是假阳性**：`GET /metrics` 的 `503 URX,UF`（`upstream_cluster: inbound|9090`）是 **Prometheus 抓取 sidecar 被拒**的运维噪声，**不是业务故障**。收敛时应排除 `path:/metrics` 的 inbound 探测，否则会把监控噪声误当故障链。
- ⚠️ **tier 归类的边界**：`Atlas MongoDB CPU High` 同时含 `cpu`（tier0）和 `mongodb`（tier3），当前"首个匹配 tier 胜出"会把它归 tier0。不影响 root 判定与整体结构，但更精细的归类需要带优先级的规则（§9 待办）。


---

## 3. 输出（Output）

### 3.1 核心数据结构：Storyline

```python
@dataclass(frozen=True)
class StorylineNode:
    """时间线上的一个信号（来自任一数据源，归一化后）。"""
    ts: int                     # UTC epoch ms（统一时间基准）
    source: str                 # "dynatrace_problem" | "dynatrace_event" | "kibana_log" | "dynatrace_metric"
    kind: str                   # 语义类型，如 "LongJAVAGCTime" / "KubeHpaMaxedOut" / "log.ERROR"
    title: str                  # 人类可读一句话
    entity_id: str | None       # 归属实体（用于实体轴对齐）
    entity_name: str | None     # 如 "event-service"
    severity: str               # "info" | "warn" | "error" | "critical"
    role: str                   # "trigger"(诱因) | "propagation"(连锁) | "symptom"(表征) | "context"
    evidence: dict              # 原始证据（problemId / eventId / correlationId / 日志原文 / 指标值）
    deep_link: str | None       # 回跳 Dynatrace/Kibana UI 的链接

@dataclass(frozen=True)
class Storyline:
    query: StorylineQuery
    window: tuple[int, int]           # 实际对齐的时间窗 (from_ms, to_ms)
    entities: tuple[str, ...]         # 卷入的实体
    nodes: tuple[StorylineNode, ...]  # 按 ts 升序的时间线
    root_cause: StorylineNode | None  # LLM 判定的最可能诱因
    narrative: str                    # LLM 生成的自然语言故障叙事
    confidence: float                 # 0-1，关联/根因置信度
    gaps: tuple[str, ...]             # 明确标注"哪些源没数据/没权限"，杜绝假完整
```

### 3.2 真实样例（基于当天 13:02–13:11 的真实数据）

从真实环境拉到的信号，storyline 应拼成：

```jsonc
{
  "window": [1785848520000, 1785849070000],   // 13:02:00 – 13:11:10 UTC
  "entities": ["event-service", "event-consumer-svc", "istio-proxy"],
  "nodes": [
    {
      "ts": 1785848524236, "source": "dynatrace_problem", "kind": "LongJAVAGCTime",
      "title": "event-consumer-2 出现 2 次 >300ms 的 G1 Young GC",
      "entity_name": "event-service", "severity": "critical", "role": "trigger",
      "evidence": { "problemId": "P-26081079", "correlationId": "c1ea1ceff32c0898",
                    "is_rootcause_relevant": true }
    },
    { "ts": 1785848731497, "source": "dynatrace_problem", "kind": "KubeHpaMaxedOut",
      "title": "HPA 达到最大副本数，无法继续扩容", "severity": "warn", "role": "propagation",
      "evidence": { "problemId": "P-26081080" } },
    { "ts": 1785848760000, "source": "dynatrace_problem", "kind": "Backoff event",
      "title": "Pod 进入 CrashLoopBackoff", "severity": "error", "role": "propagation",
      "evidence": { "problemId": "P-26081081" } },
    { "ts": 1785849051000, "source": "dynatrace_event", "kind": "startup_probe_failed",
      "title": "istio-proxy 启动探针失败：15021/healthz/ready connection refused",
      "severity": "error", "role": "propagation",
      "evidence": { "eventId": "2053638900758833146_1785849051000" } },
    // ↓ 权限就绪后由 Kibana 补齐的日志佐证（当前为 gap）
    // { "ts": 178584..., "source": "kibana_log", "kind": "log.ERROR",
    //   "title": "OutOfMemoryError: GC overhead limit exceeded", ... }
    { "ts": 1785849061688, "source": "dynatrace_problem", "kind": "AZAnomalyIdentified",
      "title": "可用区级异常，环境影响面扩大", "severity": "critical", "role": "symptom",
      "evidence": { "problemId": "P-26081082", "impactLevel": "ENVIRONMENT" } }
  ],
  "root_cause": { "kind": "LongJAVAGCTime", "entity_name": "event-service" },
  "narrative": "13:02，event-service 的 event-consumer-2 Pod 连续出现超过 300ms 的 Young GC，触发 LongJAVAGCTime 告警（根因）。GC 停顿导致处理能力下降，13:05 HPA 已扩容至上限仍无法消化积压，13:06 Pod 进入 CrashLoopBackoff，13:10 istio-proxy sidecar 启动探针连接被拒，最终在 13:11 升级为可用区级异常（环境影响面）。建议优先排查 event-consumer 的堆内存配置与消息积压。",
  "confidence": 0.78,
  "gaps": ["Kibana 日志源未接入（权限未就绪）——无法用应用日志佐证 GC/OOM 根因"]
}
```

> **`gaps` 字段是刻意设计**：对标趋势里"No silent caps"原则——某个源没数据/没权限，必须显式告诉用户，绝不让"看起来覆盖全了"的假象误导决策。

---

## 4. 关联算法（Correlation）

分四阶段：**收敛 → 对齐 → 关联 → 叙事**。前三阶段是确定性代码（便宜、可复现），只有最后叙事和根因判定交给 LLM。

### 4.1 阶段一：收敛（Gather & Narrow）—— 确定性

目标：把百万级信号缩到几十条候选。

1. 归一时间窗为 `[from_ms, to_ms]`（±30s 缓冲吸收时钟偏移）。
2. 按触发模式确定实体集合：
   - 模式 A：直接用给定 entity。
   - 模式 B：`get_problem_details(seed)` → 取 `affectedEntities` + `impactedEntities` + `managementZones`。
   - 模式 C：用 `mzSelector`/`tag` 框定，先 `list_problems` 取 top-N 严重的，反推实体。
3. 用 entitySelector/mzSelector 拉取窗内：problems（≤50）、events（≤200）、metrics（关键指标）。
4. Kibana：用实体名 + 时间窗拉 ERROR/WARN 日志（≤100 行）。

### 4.2 阶段二：对齐（Align）—— 确定性

把所有源的信号归一成 `StorylineNode`（统一 `ts` 为 UTC epoch ms、统一 severity 分级），合并进一条按 `ts` 升序的时间线。这一步是纯数据变换，无 LLM。

### 4.3 阶段三：关联打分（Correlate）—— 确定性 + 可解释

对时间线上的节点两两计算关联强度，用**加权信号**而非黑盒：

| 关联信号 | 依据（来自真实数据） | 权重 |
|---|---|---|
| **实体一致** | 同一 `entityId` 或存在拓扑关系（`get_entity_relationships`） | 高 |
| **correlationId 相同** | Dynatrace evidence 里的 `correlationId`（如 `c1ea1ceff32c0898`） | 最高（Dynatrace 已认定同源）|
| **managementZone/tag 重合** | 如同属 `critical-component:event-service` | 中 |
| **时间邻近** | `ts` 差 < 阈值（如 5min）；越近权重越高 | 中 |
| **因果类型先验** | GC→HPA打满→Backoff→探针失败→AZ异常 的常见因果模板 | 中 |
| **trace.id 贯通** | Kibana istio 网格日志的 `trace.id`（已验证真实存在，如 `75ce2c27...`）能与 Dynatrace 调用链对应 | 高 |

对每个节点标注 `role`：最早且 `is_rootcause_relevant=true` 的 → `trigger`；`impactLevel=ENVIRONMENT` 的表征 → `symptom`；中间 → `propagation`。

### 4.4 阶段四：叙事与根因（Narrate）—— LLM

只把**收敛后的时间线（几十个节点）**喂给 LLM，要求：
1. 判定最可能根因（结合 `role=trigger` + 关联强度），给置信度。
2. 生成因果叙事（中文/英文），每句话可回指具体证据节点。
3. **不确定就说不确定**，并把缺失源写进 `gaps`。

> 用 DeepAgents 现有 runtime 承载；LLM 走 SAP AI Core。关联打分建议做成一个内部工具/子图，避免让主模型即兴推理关联——**确定性的归确定性，语言的归 LLM**。

### 4.5 Workflow 编排：用 LangGraph Graph API（StateGraph）

四阶段**不交给 deep agent 的 ReAct 主循环即兴编排**——那正是"LLM 编造关联"的来源，也丢了可复现性。它是一段**固定流程的确定性管道**，用 LangGraph 的 **Graph API（`StateGraph`）** 显式建图，只在 `narrate` 一个节点里出现 LLM。

#### 为什么是 Graph API，不是 Functional API / 裸 async

结合 LangGraph 官方文档与 2026 实践，LangGraph 内部有两种风格，选型如下：

| | **Graph API（`StateGraph`）✅ 选它** | Functional API（`@entrypoint`/`@task`） | 裸 async Python |
|---|---|---|---|
| 写法 | 显式 state + node + edge | 普通函数 + 装饰器，手写 `asyncio.gather` | 全手工 |
| 并行 fan-out | **声明式**：两条边出 START，join 节点自动 barrier | 命令式 `gather` | 手工 |
| 每步可观测 | **每个 node 是命名 span** → Langfuse 直接分段 | 整函数一个黑盒 | 需手工埋点 |
| 可复现 / replay | 每 node 一个 checkpoint，可任意步重放 | 有 checkpoint 但状态在函数作用域 | 自己造 |
| 适合 | **固定流程的确定性管道（正是本场景）** | 控制流复杂、动态分支多 | 无编排诉求 |

三个针对本项目的决定性理由：

1. **可观测性是刚需**（§5.2 要用 Langfuse 记录收敛量/打分明细/根因置信度）。Graph API 每个 node 是命名 span，Langfuse trace 里能看到 `gather_dt → align → correlate → narrate` 各段的耗时与输入输出；Functional API 会把这层结构糊成一个函数。
2. **流程是死的**（收敛→对齐→关联→叙事，无动态分支），正是官方点名的 "linear pipeline / deterministic ETL-style flow"——Graph API 主场。Functional API 的卖点是"控制流复杂时省掉画图"，这里没有复杂控制流可省。
3. **并行 fan-out 声明式更安全**：两个 gather 写**不同 state key**（`raw_dynatrace` / `raw_kibana`），无需 reducer 即并发安全；`align` 有两条入边，LangGraph 自动当 barrier 等两边完成。

#### 图的形状（节点 = 四阶段）

```python
# services/agent/src/ops_pilot/correlation/orchestrator.py
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

class StorylineState(TypedDict, total=False):
    query: StorylineQuery
    raw_dynatrace: list      # gather 阶段写入（独立 key，并发安全）
    raw_kibana: list
    nodes: list              # align 阶段写入（StorylineNode）
    scored: list             # correlate 阶段写入
    storyline: Storyline     # narrate 阶段写入（最终产物）

builder = StateGraph(StorylineState)
builder.add_node("gather_dt", gather_dynatrace)   # 确定性，直接 await MCP 工具
builder.add_node("gather_kb", gather_kibana)      # 确定性
builder.add_node("align", align_nodes)            # 纯数据变换，无 LLM
builder.add_node("correlate", correlate_scores)   # 确定性打分，可解释
builder.add_node("narrate", narrate_llm)          # ← 唯一的 LLM 节点

builder.add_edge(START, "gather_dt")
builder.add_edge(START, "gather_kb")              # 两源并行 fan-out
builder.add_edge("gather_dt", "align")
builder.add_edge("gather_kb", "align")            # align 两条入边 → 自动 barrier
builder.add_edge("align", "correlate")
builder.add_edge("correlate", "narrate")
builder.add_edge("narrate", END)

storyline_graph = builder.compile()
```

#### 集成缝：gather 节点直接调用已加载的 MCP 工具（不经 LLM）

Dynatrace/Kibana 工具已在 `mcp_registry.tools`（LangChain tool 对象）。gather 节点**确定性地 `await tool.ainvoke(...)`**，而非让模型决定调哪个工具：

```python
async def gather_dynatrace(state: StorylineState) -> dict:
    q = state["query"]
    problems = await dt_list_problems.ainvoke({
        "entitySelector": f'entityId("{q.entity_ids[0]}")',
        "from": q.time_from, "to": q.time_to,
    })
    return {"raw_dynatrace": problems}   # 只写自己的 key
```

`narrate` 节点用 `create_chat_model(settings)`（与主 agent 同一个 SAP AI Core 模型），输出 `Storyline`。

---

## 5. 技术架构

### 5.1 数据流

```text
用户提问（chat / A2A）
  → StorylineQuery 归一化（三种触发模式 → 统一契约）
  → Correlation Orchestrator（新增，services/agent/src/ops_pilot 下）
      ├─ Dynatrace Adapter ── MCP: dynatrace-managed（problems/events/metrics/entities）✅ 已通
      └─ Kibana Adapter ───── MCP: kibana（_search: filebeat-* / istio.mesh.access_logs*）✅ 已验证
  → [阶段一收敛] → [阶段二对齐] → [阶段三关联打分]  （确定性 Python）
  → [阶段四叙事] LLM via SAP AI Core（DeepAgents runtime）
  → Storyline 对象
  → 输出渲染（CopilotKit chat 时间线 / A2A JSON-RPC / Langfuse trace）
```

### 5.2 与现有代码的契合点

- **MCP 工具加载**：已有 [`mcp/loader.py`](../../services/agent/src/ops_pilot/mcp/loader.py) + [`config/mcp_schema.py`](../../services/agent/src/ops_pilot/config/mcp_schema.py)。Dynatrace server 已配置且验证可用；Kibana 只需在 config 增加一个 MCP server 条目 + `allow_tools` 收敛到查询类工具。
- **HITL / allowlist**：`allow_tools` 把 Dynatrace 收敛到只读查询工具；本能力全程只读，无需 `hitl_tools`。
- **可观测性自证**：用 Langfuse 记录每次 storyline 的收敛量、关联打分、根因判定与置信度——既是 debug 手段，也是 eval 数据来源（对应"可量化根因命中率"）。
- **eval**：已有 [`eval/`](../../services/agent/eval/)。把真实故障场景（如本文 13:02–13:11 这条）做成固定 case，度量 root_cause 命中率。

### 5.3 新增模块（建议）

```
services/agent/src/ops_pilot/correlation/
  __init__.py
  query.py          # StorylineQuery 归一化（三模式）
  models.py         # StorylineNode / Storyline 数据结构
  adapters/
    dynatrace.py    # 封装 Dynatrace MCP 工具调用 + 字段归一（epoch ms）
    kibana.py       # 封装 Kibana _search + 字段归一（@timestamp → epoch ms）
  gather.py         # 阶段一：收敛
  align.py          # 阶段二：对齐
  correlate.py      # 阶段三：关联打分（确定性、可解释）
  narrate.py        # 阶段四：LLM 叙事 + 根因
  orchestrator.py   # 串联四阶段，产出 Storyline
```

### 5.4 两层夹心 + 双交互入口

storyline 逻辑**只写一遍**（`orchestrator.py` 里那张 `StateGraph`），对外有**两层封装、两个入口**：

```text
        ┌─────────────────────────────────────────┐
        │  内层：storyline_graph (StateGraph)       │  ← 确定性编排
        │  gather → align → correlate → narrate     │     每 node 一个 Langfuse span
        └─────────────────────────────────────────┘
                          ▲
        ┌─────────────────┴───────────────────────┐
        │  外层：@entrypoint run_storyline(query)    │  ← 干净入口，JSON in/out
        │  归一化 query → ainvoke 图 → 返回 Storyline │     checkpoint/replay 统一在这层
        └─────────────────┬───────────────────────┘
              ┌───────────┴────────────┐
     对话式入口                      工作流式入口
  build_storyline @tool          langgraph.json 导出 storyline graph
  （挂进 deep agent tools）        （A2A / FastAPI / eval / 定时巡检）
```

**内层 Graph API、外层 Functional API** 是官方推荐组合：内层要节点级可观测（Langfuse 分段），外层要干净入口（JSON in/out、checkpoint/replay 统一）。二者各司其职，不是二选一。

后端因此有**两种交互形式，共享同一张图**：

| | 对话式（现有） | 工作流式（新增入口） |
|---|---|---|
| 本质 | deep agent ReAct 图 | 直接调 `storyline_graph` |
| 谁决定做什么 | LLM 按对话判断要不要拉、拉哪个实体 | 调用方给死参数（problemId / entity + 窗口） |
| 顶层有无 LLM | 有（主循环推理） | **无**（顶层纯确定性，LLM 只在 narrate 节点内） |
| 输出 | 自然语言 + 面板 | 结构化 `Storyline` JSON |
| 典型场景 | CopilotKit 里人探索 | A2A 程序化 / eval 固定 case / 定时巡检 |
| 挂载 | `build_storyline` 工具加进 `runtime.py` 的 tools | `langgraph.json` 增加一个平级 graph 导出 |

```python
# 外层入口
@tool
async def build_storyline(query: StorylineQueryInput) -> dict:
    """在同一时间窗对齐 Dynatrace 指标/事件 + Kibana 日志，产出故障叙事。"""
    result = await storyline_graph.ainvoke({"query": normalize(query)})
    return result["storyline"].as_dict()
```

#### 三条硬约束

1. **顶层不得再套 ReAct**：工作流式入口必须是确定性 `StateGraph`，禁止"再 new 一个 ReAct agent 让它编排四阶段"——否则退回 LLM 编造关联、丢可复现性。LLM 只在 `narrate` 一个节点出现。
2. **子图在 tool 里被调用时，LangGraph Studio 看不到子图内部 state**（官方已知权衡）。不影响功能（interrupt 仍向上冒泡；本能力全程只读、无 HITL），四阶段可观测性靠 Langfuse 而非 Studio，所以这个代价不付。
3. **前后端契约对齐**：`narrate` 产出的 `Storyline` 序列化后写入 CopilotKit `storyline` shared-state key，形状严格对齐前端 [`apps/web/src/app/storyline.ts`](../../apps/web/src/app/storyline.ts) 与 §3.1，驱动 App 面板渲染。

#### 前端如何拿到 storyline（无需新增 REST API）

CopilotKit 经 AG-UI 把 LangGraph agent 的 state **自动流式同步**到前端——前端 `useAgent().agent.state` 读的就是这份 state，无需任何 fetch/轮询/REST。链路已就绪（`_create_deep_agent` 已装 `CopilotKitMiddleware`）。要让 `storyline` 抵达前端，只需两步（均已实现）：

1. **扩展 state schema**：新增 `StorylineAgentState(DeepAgentState)`，加一个 `storyline` channel（`agent/state.py`），并作为 `create_deep_agent(state_schema=...)`。这是必需的——AG-UI 的 `get_state_snapshot` 会用 graph 输出 schema 的 key 过滤 state，`storyline` 不在 schema 里就会被丢弃。
2. **工具写 state**：`build_storyline` 工具返回 `Command(update={"storyline": <dict>, "messages": [ToolMessage(summary)]})`——既把结构化 storyline 写进 shared-state（驱动面板），又给对话返回一句摘要。

> **Kibana 工具事实**：所接入的 `mcp-server-kibana` **没有**专用 ES search 工具，只有通用的 `execute_kb_api`。ES `_search` 经 Console proxy 走：`POST /api/console/proxy?path=<index>/_search`。其返回是 `{"content":[{"text":"[Space: X] API response: <JSON>"}]}`，适配层剥离该文本前缀后解析 JSON。

---

## 6. 展现形式（Presentation）

### 6.1 CopilotKit Chat（主）

- **时间线视图**：垂直时间轴，节点按 `severity` 着色、按 `source` 标图标（Dynatrace / Kibana / 指标），`role=trigger` 高亮为起点、`symptom` 标为终点。
- **叙事段落**：LLM 生成的 narrative 放在时间线顶部，句中关键节点可点击滚动到对应时间线节点。
- **证据抽屉**：点节点展开 `evidence` 原文 + `deep_link` 回跳 Dynatrace/Kibana UI。
- **gaps 提示条**：顶部黄色条明确列出"哪些源无数据/无权限"。

> 遵循 `dataviz` 技能规范做时间线与 severity 配色（浅色/深色一致、可访问）。

### 6.2 结构化输出（A2A / 程序化）

`Storyline` 直接序列化为 JSON（§3.1 的结构），供 A2A JSON-RPC 调用方消费。这是"平台"属性的体现——同一份关联结果既能给人看，也能给别的 agent 用。

### 6.3 Langfuse（自证 / debug）

每次 storyline 作为一条 trace：收敛前后信号量、关联打分明细、LLM 根因判定 + 置信度、耗时。用于回归和"根因命中率"度量。

---

## 7. 落地路径（分阶段）

| 阶段 | 范围 | 产出 | 依赖 |
|---|---|---|---|
| **P0** | Dynatrace 单源时间线（模式 B：problem 为轴） | 给一个 problemId，拉 evidence + 相关 events，对齐成时间线，LLM 叙事 | 仅 Dynatrace（已通）|
| **P1** | 实体为轴（模式 A）+ 关联打分 | 给 service + 时间窗，收敛 → 对齐 → 打分 → 叙事 | Dynatrace |
| **P2** | 接入 Kibana 日志源 | Kibana adapter（`filebeat-*` + `istio.mesh.access_logs*`）+ trace.id 贯通，日志佐证根因 | Kibana（已验证可查）|
| **P3** | eval + Langfuse 自证 | 固定故障 case 集，度量根因命中率 | P1 完成 |
| **P4** | 前端时间线视图 | CopilotKit 时间线 + 证据抽屉 | P1 输出稳定 |

**关键路径**：P0→P1 完全不依赖 Kibana，可立即开工；P2 的 Kibana 侧字段映射已实拉验证（§2.3），当前用临时 cookie 可查，正式只读权限到位后仅换凭证即可，不改主线。

---

## 8. 风险与决策

| 风险 | 应对 |
|---|---|
| 百万级 events 灌爆上下文 | 阶段一强制收敛 + 预算上限（max_events 等），LLM 只见几十节点 |
| 两源时钟偏移导致错序 | 统一 UTC epoch ms + ±30s 缓冲；trace.id 贯通优先于纯时间邻近 |
| LLM 编造关联 | 关联打分是确定性代码，LLM 只做叙事；`gaps` 显式标注缺口 |
| Kibana 权限迟迟不到 | 当前临时 cookie 已可查；正式只读权限到位后仅换凭证，不改架构 |
| Dynatrace 日志 403 | 已确认——日志改由 Kibana（filebeat-*）承担，不依赖 Dynatrace 日志 |
| **应用日志无 `log.level` 字段** | filebeat 应用日志 level 内嵌在 `message`——用 `stream:stderr` 粗筛 + LLM/正则从 message 抽取 level，不能依赖 `terms:log.level` |
| `message` 被 `[DROP]` 脱敏 | 当前采样值为占位；业务 message 放开后才能做语义根因，脱敏期间关联仍可靠结构化字段（trace.id / response_code / stream）运行 |
| **失败调用大量是噪声** | 实测（§2.4）非-200 调用 95% 是 `169.254.169.254` 元数据探测——收敛阶段必须按 `authority`/`path`/`response_code` 过滤噪声，`response_flags`（如 `URX,UF`）优先作为真故障信号 |
| **两源保留期不一致** | 实测（§2.4）Dynatrace problem 保留 > Kibana 热日志：老窗口日志已滚掉。关联窗口受限于较短一方，超出时日志侧标 `gap` 而非报错 |
| **实体粒度不对齐** | Dynatrace 受影响实体是 CLOUD_APPLICATION/SERVICE 粒度，Kibana 是 pod 粒度且 problem 未必直接命中同名实体——关联打分须支持管理域（`critical-component`）/拓扑邻近，不能只做 entityId 精确匹配 |

## 9. 待确认

- **业务 message 放开时间**：当前 `message` 字段被 `[DROP]` 脱敏，语义根因（从日志正文识别 OOM/异常栈）依赖其放开；在此之前 storyline 靠结构化字段（istio `response_code`/`response_flags`、`stream`、`trace.id`）关联，日志正文佐证为 gap。
- **集群区分**：环境同时存在 `prod-frankfurt` 与 `pre-prod-frankfurt`（`labels.kubernetes.cluster`）。Kibana 查询须按集群过滤，且需确认与 Dynatrace `frankfurt` 环境对应的是哪个集群，避免跨集群误关联。
- **噪声黑名单**：`169.254.169.254`（云元数据）、`PassthroughCluster`、`/metrics` inbound 抓取（§2.5）等应做成可配置的关联噪声黑名单（写进 config.yaml）。
- **关联打分的权重**是否需要可配置（写进 config.yaml），并支持管理域/拓扑邻近维度。
- **因果 tier 归类的精度**：当前"首个匹配 tier 胜出"对多关键词标题（如 `Atlas MongoDB CPU High` 同含 cpu/mongodb）会归错层——不影响 root 判定，但需带优先级/更精细的规则（§2.5 暴露）。
- **正式只读权限**：临时 cookie 会过期；需推动正式的 Kibana 只读 role/API key，替换 `.mcp.json` 里的 `KIBANA_COOKIES`。

### 已落实（从待确认转为已实现）

- ✅ **Dynatrace `environment_alias`**：真实 MCP server 强制此参数，adapter 用 `ALL_ENVIRONMENTS`（§2.5）。
- ✅ **模式 C（时间窗为轴，不锁 entity）**：`gather_dynatrace` 支持不给 entity 只按窗口/管理域拉 problem，跨粒度关联的前提。
- ✅ **因果分层选根因** + **候选按 tier 截断**：见 §2.5 三项能力升级。
- ✅ **跨粒度链接**：日志按"problem 描述提及服务名 / 共享管理域"关联到 problem，而非 entityId 相等。

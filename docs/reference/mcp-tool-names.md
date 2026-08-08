# MCP Tool Names Reference

Verified tool names exposed by each MCP server wired in
[`config/config.yaml`](../../config/config.yaml). Names were extracted directly
from each server's source/package (not guessed) so they can be used verbatim in
eval `expected_tools` / `forbidden_tools`
([`services/agent/eval/cases/`](../../services/agent/eval/cases/)) and in
per-server `allow_tools` / `hitl_tools` allowlists.

> Keep this file in sync when a server is upgraded — a renamed tool silently
> breaks the `tool_called` / `tool_not_called` graders (they compare exact
> strings).

## prometheus

- Package: `prometheus-mcp` (npm), repo `idanfishman/prometheus-mcp`, v1.1.3
- Launch: `npx -y prometheus-mcp@latest stdio`

| Tool | Purpose |
| --- | --- |
| `prometheus_query` | Instant PromQL query at a single timestamp |
| `prometheus_query_range` | PromQL query over a time range (trends) |
| `prometheus_list_metrics` | List available metric names |
| `prometheus_list_labels` | List label names |
| `prometheus_label_values` | List values for a label |
| `prometheus_list_targets` | List scrape targets |
| `prometheus_metric_metadata` | Metadata (type/help) for a metric |
| `prometheus_build_info` | Prometheus build info |
| `prometheus_runtime_info` | Prometheus runtime info |
| `prometheus_scrape_pool_targets` | Targets for a scrape pool |

## jaeger

- Package: `opentelemetry-mcp` (PyPI), repo `traceloop/opentelemetry-mcp-server`
- Launch: `uvx opentelemetry-mcp --backend jaeger`
- Tool names are the `@mcp.tool()` function names in `src/opentelemetry_mcp/server.py`.

Trace-facing tools (relevant to the OTel demo):

| Tool | Purpose |
| --- | --- |
| `list_services` | List services reporting traces |
| `search_traces` | Search traces by service/operation/tags/time |
| `get_trace` | Fetch a single trace by `trace_id` |
| `find_errors` | Find error/failed traces |
| `search_spans_tool` | Search individual spans |

LLM-observability tools also registered but not used for the demo:
`get_llm_usage`, `list_llm_models`, `get_llm_model_stats`,
`get_llm_expensive_traces`, `get_llm_slow_traces`, `list_llm_tools_tool`.

## opensearch

- Package: `opensearch-mcp-server-py` (PyPI)
- Launch: `uvx opensearch-mcp-server-py`
- The set below is the `allow_tools` allowlist already configured in
  `config/config.yaml`. `GenericOpenSearchApiTool` is in `hitl_tools`
  (human-in-the-loop approval) because it can hit arbitrary endpoints.

| Tool | Purpose |
| --- | --- |
| `ListIndexTool` | List indices |
| `IndexMappingTool` | Get index mappings |
| `SearchIndexTool` | Query documents (DSL) |
| `GetShardsTool` | Shard-level status |
| `ClusterHealthTool` | Cluster health |
| `CountTool` | Document counts |
| `ExplainTool` | Explain a query match |
| `MsearchTool` | Multi-search |
| `PPLQueryTool` | Piped Processing Language query |
| `GenericOpenSearchApiTool` | Arbitrary API call (**hitl**) |

Write access is off (`OPENSEARCH_SETTINGS_ALLOW_WRITE=false`).

## kubernetes

- Package: `kubernetes-mcp-server` (npm), repo `containers/kubernetes-mcp-server`, v0.0.66
- Launch: `npx -y kubernetes-mcp-server@latest --read-only --disable-multi-cluster --kubeconfig <path>`
- Tool names are the `Name:` fields in `pkg/toolsets/core/*.go`.

**Read-only tools (available under `--read-only`):**

| Tool | Purpose |
| --- | --- |
| `pods_list` | List pods (all namespaces) |
| `pods_list_in_namespace` | List pods in one namespace |
| `pods_get` | Get one pod |
| `pods_log` | Pod logs |
| `pods_top` | Pod CPU/memory usage |
| `events_list` | List events (warnings etc.) |
| `namespaces_list` | List namespaces |
| `projects_list` | List projects (OpenShift) |
| `nodes_log` | Node logs |
| `nodes_top` | Node CPU/memory usage |
| `nodes_stats_summary` | Node stats summary |
| `resources_get` | Get an arbitrary resource |
| `resources_list` | List arbitrary resources |

**Mutating tools — BLOCKED by `--read-only`** (use as `forbidden_tools` to
catch regressions / prompt injection):

`pods_delete`, `pods_exec`, `pods_run`, `resources_create_or_update`,
`resources_delete`, `resources_scale`.

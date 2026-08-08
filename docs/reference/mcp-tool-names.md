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

- Server: official `prometheus/prometheus-mcp` v0.18.0
- Transport: authenticated Streamable HTTP at `/mcp`; the server reaches
  Prometheus over the cluster-internal Service.

| Tool | Purpose |
| --- | --- |
| `query` | Instant PromQL query at a single timestamp |
| `range_query` | PromQL query over a time range |
| `metric_metadata` | Metric type/help metadata |
| `label_names` | List label names |
| `label_values` | List values for a label |
| `series` | Find time series by label matchers |
| `docs_list`, `docs_read`, `docs_search` | Read official Prometheus documentation |

## jaeger

- Server: Jaeger v2.19+ native `jaeger_mcp` extension
- Transport: authenticated Streamable HTTP at `/mcp`

The native tools use progressive disclosure so an investigation can inspect
topology, errors, or individual spans without downloading every span in a
trace:

| Tool | Purpose |
| --- | --- |
| `get_services` | List services reporting traces |
| `get_span_names` | List span names for a service |
| `search_traces` | Search traces by service/operation/tags/time |
| `get_trace_topology` | Summarize a trace's service and call topology |
| `get_trace_errors` | Return only error spans and error details for one trace |
| `get_span_details` | Fetch selected span details |
| `get_critical_path` | Find latency-critical spans in one trace |
| `get_service_dependencies` | Summarize service dependencies |

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

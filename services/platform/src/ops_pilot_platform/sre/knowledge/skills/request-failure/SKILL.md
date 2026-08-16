---
name: request-failure
description: Diagnose elevated request failures, error-rate alerts, failed transactions, and downstream error propagation in distributed services.
---

# Request failure diagnosis

Use this route when the reported impact is failed requests or transactions.

1. Query topology around the alerted entity to identify upstream callers and
   downstream dependencies. Do not assume the alerted service is the origin.
2. Use `list_metric_names` for the alerted entity and nearby dependencies, then
   use `query_metric_range` to compare their error-related signals over the same
   window. The earliest aligned rise is a candidate origin.
3. Use `query_log_stats` before `query_logs` on the candidate entity. Prefer a
   repeated structured failure pattern over isolated lines.
4. Use `query_traces` with `status_code="ERROR"` to test whether failures begin
   in the candidate or arrive from a dependency. Retrieve one returned trace by
   `trace_id` when parent-child ordering is needed.
5. Refute the leading hypothesis if its local signals remain healthy while a
   dependency fails earlier. Stop after one minimal origin explains the error
   timing, propagation direction, and user impact.

Report the root entity only once. Keep downstream operations in the causal chain,
not in the root-entity list.

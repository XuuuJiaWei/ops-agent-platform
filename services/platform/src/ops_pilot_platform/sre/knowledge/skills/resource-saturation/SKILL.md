---
name: resource-saturation
description: Diagnose CPU, memory, garbage collection, disk, thread, queue, and resource-limit saturation affecting workloads or nodes.
---

# Resource saturation diagnosis

1. Use `query_topology` to distinguish service, workload, pod, and node scope.
2. Discover resource, limit, saturation, restart, and workload signals with
   `list_metric_names`; never guess a metric name.
3. Use `query_metric_range` to compare demand, limits, and service impact in the
   same window. A high absolute value without a change or limit is not sufficient.
4. Use `query_events` for scheduling, eviction, OOM, restart, and node lifecycle
   evidence. Use `query_log_stats` and `query_logs` only for the narrowed entity.
5. Refute resource saturation if the resource signal stays below its effective
   limit or begins after the request failure. Stop when resource pressure precedes
   and explains the service-level impact.

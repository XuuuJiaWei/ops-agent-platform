---
name: dependency-connectivity
description: Diagnose database, cache, DNS, network-policy, load-balancer, and other dependency availability or connectivity failures.
---

# Dependency and connectivity diagnosis

1. Use `query_topology` to enumerate the direct dependency edge before querying
   telemetry. Preserve the distinction between caller, client library, endpoint,
   and dependency service.
2. Compare dependency availability, connection, and request signals with
   `list_metric_names` plus `query_metric_range` in one aligned interval.
3. Use `query_log_stats` then `query_logs` for timeout, refusal, resolution,
   authentication, pool, or protocol patterns. Treat text as evidence, not a label.
4. Use `query_traces` to locate the first failing client/server span. Use
   `query_events` when policy, endpoint, pod, or load-balancer state could change.
5. Refute a dependency hypothesis when direct callers succeed and the dependency's
   own availability stays healthy. Stop after the failed edge and originating side
   are supported by at least two aligned signals.

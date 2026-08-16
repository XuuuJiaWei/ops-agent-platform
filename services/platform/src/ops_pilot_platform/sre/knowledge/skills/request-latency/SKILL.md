---
name: request-latency
description: Diagnose response-time degradation, timeouts, slow dependencies, and latency propagation across request paths.
---

# Request latency diagnosis

1. Map the alerted path with `query_topology`; list both callers and dependencies.
2. Discover latency and throughput signals with `list_metric_names`. Use
   `query_metric_range` over one aligned window to find the earliest service whose
   latency rises without a prior upstream rise.
3. Query slow spans with `query_traces`. Compare duration and parent-child order;
   a slow caller span alone does not prove the caller is the origin.
4. Check resource metrics and error logs on the slowest dependency to distinguish
   compute saturation, blocking, retries, and downstream wait time.
5. Refute dependency slowness when child spans and dependency metrics are healthy;
   then inspect the local service. Stop when timing and trace direction agree.

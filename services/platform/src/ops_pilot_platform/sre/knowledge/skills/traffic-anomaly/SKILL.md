---
name: traffic-anomaly
description: Diagnose traffic surges, hotspots, skew, rate limiting, overload, and traffic drops that may originate outside a service.
---

# Traffic anomaly diagnosis

1. Query topology to identify entry points, fan-out dependencies, and replicas.
2. Discover request volume, per-entity throughput, error, latency, and saturation
   signals. Use `query_metric_range` to compare total load with its distribution.
3. A surge is causal only when it precedes saturation or errors. A traffic drop can
   be impact from an upstream failure, so inspect the nearest entry point first.
4. Use `query_alerts` for correlated symptoms and `query_traces` for fan-out or
   retry amplification. Use logs for explicit throttling or admission evidence.
5. Refute a load hypothesis when volume is stable or rises after the failure. Stop
   after identifying whether the origin is ingress volume, skew, retry amplification,
   or a capacity limit.

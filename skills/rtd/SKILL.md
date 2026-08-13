---
name: rtd
description: RTD (Response Time Degradation) — diagnosing latency spikes in Astronomy Shop services using trace durations and Prometheus latency metrics.
---

Use this skill when an alert or user report describes **slowness** — pages load slowly, operations take longer than normal, timeouts without errors, or P95/P99 latency rising — but requests eventually succeed (or time out). The signal is **span duration outliers**, not error spans.

## Latency fault modes covered

| Flag | Degradation pattern |
|---|---|
| `imageSlowLoad` | Frontend adds artificial delay to image responses (variants: 5sec / 10sec) |
| `intlShippingSlowdown` | Shipping service adds sleep before responding |
| `kafkaQueueProblems` | Kafka producer overload + consumer slowdown → order processing backlog |

## Primary tool: `search_traces` — look for duration outliers

Search without an error filter; sort by duration descending.

```
search_traces(service="frontend", limit=20)
```

Key questions when reading durations:
- Is one **specific operation** consistently slow, or is the whole service slow?
- Is the slowness in the **leaf span** (the actual operation is slow) or in a **parent span** waiting on a child (slow dependency)?
- For `imageSlowLoad`: the slow spans will be on image-related operations in the frontend, not in a backend service.
- For `intlShippingSlowdown`: `ShippingService/GetQuote` or similar will show added duration.
- For `kafkaQueueProblems`: look for slow Kafka consumer spans; also check queue-related spans in the ordering or accounting services.

## Secondary tool: `query` (Prometheus) for P95/P99 trends

When you need a time-series view of latency growth:

```promql
histogram_quantile(0.95, sum(rate(http_server_duration_milliseconds_bucket{job="astronomy-shop-frontend"}[5m])) by (le))
```

Useful for:
- Confirming that latency is rising steadily (resource-induced degradation) vs. suddenly (flag-induced fixed delay)
- Comparing current P95 vs. historical baseline

## Distinguish the three RTD patterns

**Fixed added delay** (`imageSlowLoad`, `intlShippingSlowdown`):
- Span durations are uniformly elevated by a constant offset
- Most or all requests of that operation are slow (not intermittent)
- No error spans — requests succeed, just slowly

**Queue / backlog latency** (`kafkaQueueProblems`):
- End-to-end confirmation latency grows over time as backlog builds
- Individual consumer spans may be slow; producer spans may show high publish latency
- Check Kafka-related spans for both producer and consumer side delays

**Cascading latency** (slow dependency causing caller to be slow):
- The slow leaf span propagates as added duration up the trace tree
- Identify the leaf (innermost) span that is anomalously long — that is the root cause

## Quantifying latency impact

- State the added delay: "image response spans show ~10s added latency vs. a baseline of ~50ms".
- Reference the operation name: do not say "the service is slow" — say "the `GetQuote` operation on `shippingservice` is consistently ~5s above baseline".
- If you have a baseline metric, compare current P95 to it.

## Reporting format

- Name the affected operation and service explicitly.
- Quote an approximate duration: "spans on this operation are averaging Xms vs. a baseline of Yms".
- Distinguish: is this a **fixed added delay** (flag variant) or **growing backlog** (queue accumulation)?
- Separate observation from hypothesis.
- Do not claim a fix was applied unless you explicitly called a mutating tool.

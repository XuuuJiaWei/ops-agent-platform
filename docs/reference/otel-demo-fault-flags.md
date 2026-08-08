# OpenTelemetry Demo Fault Injection Flags

The OTel Demo (astronomy shop) injects faults through feature flags served by
**flagd**. Source of truth is `src/flagd/demo.flagd.json` in the
[opentelemetry-demo](https://github.com/open-telemetry/opentelemetry-demo)
repo. These flags are the **ground truth** for the ops_pilot eval scenarios in
[`services/agent/eval/cases/ops_scenarios.yaml`](../../services/agent/eval/cases/ops_scenarios.yaml):
enable a flag, run the agent, and score whether it names the injected fault.

> Snapshot from `main` (15 flags). Flag keys changed across versions — the old
> long names (`adServiceFailure`, `cartServiceFailure`, `recommendationServiceCacheFailure`,
> `loadGeneratorFloodHomepage`, …) are gone. Re-check the file after upgrading
> the demo: `gh api repos/open-telemetry/opentelemetry-demo/contents/src/flagd/demo.flagd.json --jq .content | base64 -d`

## How the faults are implemented (important)

The flags do **not** break the Kubernetes cluster. Each service reads its flag
through the **OpenFeature SDK** (provider = flagd) and then *deliberately
misbehaves in application code*. The fault source is always the flag value, not
any real cluster/config problem.

Real source examples:

```js
// src/payment/charge.js — application throws based on the flag
const numberVariant = await OpenFeature.getClient().getNumberValue("paymentFailure", 0);
// ...fails that fraction of charge requests
```

```python
# src/recommendation/recommendation_server.py — code really leaks memory
with tracer.start_as_current_span("get_product_list") as span:
    if check_feature_flag("recommendationCacheFailure"):
        span.set_attribute("demo.feature_flag.recommendation_cache", True)
        cached_ids = cached_ids + response_ids
        cached_ids = cached_ids + cached_ids[:len(cached_ids) // 4]  # unbounded growth
```

By mechanism:

| Class | Flags | What actually happens |
| --- | --- | --- |
| Application error | `paymentFailure`, `cartFailure`, `productCatalogFailure`, `adFailure` | Code path does `if flag: throw` (fixed or n% of requests) |
| Real resource burn | `adHighCpu`, `adManualGc`, `emailMemoryLeak`, `recommendationCacheFailure` | Code really burns CPU / triggers GC / leaks memory — container CPU/memory metrics genuinely rise |
| Injected latency | `imageSlowLoad`, `intlShippingSlowdown`, `kafkaQueueProblems` | Code sleeps / backs up a queue with a consumer-side delay |
| K8s-surface | `failedReadinessProbe` | Service fails its `/readiness` handler, so kubelet really marks the cart pod NotReady |

Consequences for an ops agent:

- **The signals are real.** Traces get error spans, metrics move, logs appear,
  and (for the resource/probe classes) Kubernetes-level state really changes.
  RCA over Prometheus/Jaeger/OpenSearch/Kubernetes is genuine.
- **The root cause lives in the flag, not the cluster.** No Kubernetes action
  fixes a flag-injected fault — deleting/scaling a pod just brings back a new
  pod that reads the same flag and misbehaves identically. The only real
  "cure" is turning the flag off. This is why ops_pilot targets a **diagnosis
  closed loop** (enable flag → RCA → correct root-cause statement, scored
  against the flag as ground truth), and the kubernetes MCP is `--read-only`.

### Localization granularity (what RCA can pinpoint)

An agent reading traces via the jaeger MCP (`find_errors`, `search_traces`,
`get_trace`) can localize to:

- the failing **service** (`service.name` on the error span) — always;
- the failing **operation / span** — the span name, which corresponds to an
  instrumented function or RPC (e.g. `get_product_list`,
  `oteldemo.PaymentService/Charge`);
- the **error detail** — span status `ERROR`, exception events, and demo
  attributes like `demo.feature_flag.*` / `demo.recommendation.cache_hit`.

A span is an *instrumented operation*, not an arbitrary source line: the agent
resolves "which service, which operation, which step in the call chain," but
cannot point at an un-instrumented function beyond its enclosing span. The demo
wraps each fault in a named span (and often tags the flag name directly on the
span), so the fault site carries its own ground-truth label — convenient for
scoring eval rubrics against the operation name.

## How to enable a flag

- **UI:** open the Feature Flags UI at `http://localhost:8080/feature/`, pick a
  flag, set its variant. flagd hot-reloads within seconds.
- **JSON:** edit `src/flagd/demo.flagd.json`, change the flag's `defaultVariant`
  (e.g. `off` → `on`, `50%`, or `10sec`). flagd watches the file / ConfigMap and
  reloads. In k8s, edit the mounted ConfigMap.

Enable **one** flag at a time so a single fault is the known root cause.

## Flags

| Flag key | Variants | Injected fault |
| --- | --- | --- |
| `adFailure` | off / on | Ad service returns errors |
| `adHighCpu` | off / on | High CPU load in the ad service |
| `adManualGc` | off / on | Frequent full GC in the ad service |
| `cartFailure` | off / 10% / 25% / 50% / 75% / 90% / 100% | Cart service fails n% of requests |
| `emailMemoryLeak` | off / 1x / 10x / 100x / 1000x / 10000x | Memory leak in the email service |
| `failedReadinessProbe` | off / on | Cart service readiness probe fails |
| `imageSlowLoad` | off / 5sec / 10sec | Slow-loading images in the frontend |
| `intlShippingSlowdown` | off / 5sec / 10sec | Delayed international shipping responses |
| `kafkaQueueProblems` | off / on | Kafka queue overload + consumer-side delay |
| `loadGeneratorTraffic` | off / on (default **on**) | Synthetic load-generator traffic on/off |
| `loadGeneratorVUs` | 5 (default) / 10 / 25 / 50 | Concurrent virtual users in the load generator |
| `paymentFailure` | off / 10% / 25% / 50% / 75% / 90% / 100% | Payment charge requests fail n% |
| `paymentUnreachable` | off / on | Payment service unavailable (connection fails) |
| `productCatalogFailure` | off / on | Product catalog fails on a specific product |
| `recommendationCacheFailure` | off / on | Recommendation cache fails (memory growth) |

## What each fault looks like in the observability stack

- **Jaeger** — error spans (red), broken/elongated call chains; fault propagates
  along the dependency graph (e.g. `productCatalogFailure` → checkout → frontend).
- **Prometheus / Grafana** — error rate ↑, p95/p99 latency ↑. Signal by fault:
  - `adHighCpu` → CPU curve; `imageSlowLoad` / `intlShippingSlowdown` → latency;
  - `kafkaQueueProblems` → consumer lag / backlog; `emailMemoryLeak` /
    `recommendationCacheFailure` → memory growth;
  - `cartFailure` / `paymentFailure` → percentage-shaped error rate.
- **Kubernetes** — `failedReadinessProbe` shows the cart pod as not ready /
  restarting in `pods_list_in_namespace` + `events_list`.

## Flag → eval case mapping

| Flag (ground truth) | Eval case id |
| --- | --- |
| `paymentFailure` (pct) | `otel-payment-failure-charge`, `otel-explain-payment-impact` |
| `paymentUnreachable=on` | `otel-payment-unreachable` |
| `productCatalogFailure=on` | `otel-product-catalog-failure` |
| `cartFailure` (pct) | `otel-cart-failure-rate` |
| `adHighCpu=on` | `otel-ad-high-cpu` |
| `imageSlowLoad` (5s/10s) | `otel-image-slow-load` |
| `kafkaQueueProblems=on` | `otel-kafka-queue-problems` |
| `recommendationCacheFailure=on` | `otel-recommendation-cache-failure` |
| `failedReadinessProbe=on` | `otel-status-pod-health` |

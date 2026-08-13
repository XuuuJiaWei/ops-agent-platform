---
name: fri
description: FRI (Failure Rate Increase) — diagnosing error-rate spikes in Astronomy Shop services using distributed traces.
---

Use this skill when an alert or user report describes **requests failing** — non-OK gRPC status, HTTP 5xx, timeouts, or a downstream service becoming unreachable. The primary signal is error spans in Jaeger, not logs or metrics.

## Failure modes covered

| Flag | Failure pattern |
|---|---|
| `paymentFailure` | % of `PaymentService/Charge` gRPC calls return error |
| `paymentUnreachable` | Checkout cannot reach payment at all (connection error) |
| `productCatalogFailure` | Specific product-catalog item returns error |
| `cartFailure` | % of cart `AddItem`/`GetCart` calls fail |
| `adFailure` | Ad service returns error responses |
| `failedReadinessProbe` | Cart pod fails readiness → K8s stops routing → 100% cart errors |

## Primary tool: `search_traces`

Always start here. Search for error spans on the suspected service/operation.

```
search_traces(service="paymentservice", tags={"error": "true"}, limit=20)
```

Key fields to read in results:
- `operationName` — which RPC/endpoint is erroring
- `duration` — long duration + error → timeout; short + error → application error
- `tags["error.message"]` or `tags["grpc.status_code"]` — error classification

To estimate **failure fraction**: compare error-span count to total-span count for the same operation over a 15-minute window. Do this with two calls (`tags={"error":"true"}` then without the tag filter) or use `get_trace_errors` on a trace ID.

## Distinguish partial vs. total failure

- **Partial** (`paymentFailure`, `cartFailure`): some spans succeed, some error → percentage variant
  - Look for: mixed success/error spans on same operation across time
- **Total / unreachable** (`paymentUnreachable`, `failedReadinessProbe`): every call errors, often with connection-level status
  - Look for: `grpc.status_code=UNAVAILABLE` or transport-level errors, no successful spans at all
- **Scoped** (`productCatalogFailure`): only a specific item/context errors
  - Look for: errors only when `tags["productId"]` matches a specific value

## Identify the initiating service

When multiple services show errors, find the **one whose error spans have no downstream error cause**:
1. Look at `references` in the error span — does it reference a downstream error span?
2. The service where errors originate without an upstream trigger is the root-cause service.
3. Downstream services (e.g. checkout erroring because payment is down) are **victims**, not root cause.

## Fallback: pod events for readiness probe failures

`failedReadinessProbe` is visible at the Kubernetes level, not in traces. If traces show 100% cart errors and no application error spans:
```
pods_list_in_namespace(namespace="astronomy-shop")  → check READY column and RESTARTS
```
A pod in 0/1 READY state on the cart service confirms the readiness probe scenario.

## Reporting format

- State the failing service and operation explicitly: "the payment service is returning errors on `PaymentService/Charge`".
- Quantify: "approximately 50% of charge requests errored in the last 15 minutes (N error spans out of M total)".
- Separate observation from hypothesis: what the span data shows vs. what likely caused it.
- State confidence: high = direct error spans; medium = inferred from downstream errors only; low = no signal yet.
- Do not claim a fix was applied unless you explicitly called a mutating tool.

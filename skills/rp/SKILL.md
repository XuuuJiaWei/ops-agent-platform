---
name: rp
description: RP (Resource Pressure) — diagnosing CPU saturation, memory leaks, and GC pressure in Astronomy Shop services using Prometheus metrics.
---

Use this skill when an alert describes **rising CPU usage, growing memory, GC pauses, or a service that is slow but not returning errors** — especially when the degradation grows gradually rather than appearing suddenly. The primary signal is **Prometheus resource metrics**, not trace error spans.

## Resource fault modes covered

| Flag | Resource pattern | Affected service |
|---|---|---|
| `adHighCpu` | Synthetic CPU-intensive workload | ad service |
| `adManualGc` | Programmatic GC trigger → CPU spikes + stop-the-world pauses | ad service |
| `emailMemoryLeak` | Unbounded memory allocation on each request | email service |
| `recommendationCacheFailure` | Cache grows without eviction → heap pressure | recommendation service |

## Primary tool: `query` (Prometheus)

Always start with resource metrics for the suspected pod/service.

**CPU utilization** (fraction of one CPU core, or % of request limit):
```promql
rate(container_cpu_usage_seconds_total{namespace="astronomy-shop", pod=~"adservice.*"}[5m])
```
A value approaching or exceeding the CPU limit means saturation. For `adHighCpu`: expect near-100% CPU on the ad service pod.

**Memory usage** (bytes used vs. limit):
```promql
container_memory_working_set_bytes{namespace="astronomy-shop", pod=~"emailservice.*"}
```
A value growing monotonically over time confirms a memory leak (`emailMemoryLeak`). A value that is high but stable suggests a large cache (`recommendationCacheFailure`).

**GC pause time** (JVM/Go runtime):
For `adManualGc` (Java-based ad service):
```promql
rate(jvm_gc_duration_seconds_sum{job="astronomy-shop-adservice"}[5m])
```
Spikes in GC duration signal stop-the-world pauses that inflate request latency without triggering error spans.

## Distinguish the four RP patterns

**High CPU saturation** (`adHighCpu`):
- CPU metric near 100% of limit
- Request latency elevated but errors absent (until CPU is fully saturated)
- Steady-state: CPU stays high as long as the flag is on

**GC pressure / CPU spikes** (`adManualGc`):
- CPU metric shows periodic spikes (not constant elevation)
- GC duration metric shows bursts
- Latency is intermittently elevated (high during GC pause, normal between pauses)
- Same service as `adHighCpu` (ad service) — distinguish by the spike pattern

**Memory leak** (`emailMemoryLeak`):
- Memory metric grows steadily over time (not a step change)
- CPU may also rise as GC works harder to reclaim space
- Service may eventually OOM-crash if left long enough

**Cache growth** (`recommendationCacheFailure`):
- Memory metric is high and may still be growing (depending on when it stabilised)
- Unlike a leak: the growth is bounded by request traffic, not unbounded
- Check if memory is stable at a high value (cache filled) or still growing

## When to cross-check with traces

Resource pressure often causes latency degradation but not errors. After confirming the resource metric, use `search_traces` to verify the service-level impact:
- For `adHighCpu`/`adManualGc`: ad service spans should show elevated duration
- For `emailMemoryLeak`/`recommendationCacheFailure`: spans may show increasing latency as the process struggles

If trace errors are present alongside resource pressure, check whether the errors are caused by the resource pressure (e.g. request timeouts because the pod is CPU-starved) or a separate fault.

## Reporting format

- Name the affected service and the specific resource under pressure: "the ad service pod is consuming ~95% of its CPU limit".
- Show the metric trend: "CPU usage has been at this level for the last 20 minutes" or "memory has grown from 200MB to 450MB over the past hour".
- Distinguish: constant elevation (CPU saturation) vs. periodic spikes (GC) vs. monotonic growth (leak).
- State confidence: high = clear metric trend with a matching flag; medium = metric elevated but trend unclear.
- Do not recommend scaling or restarting without prior approval.

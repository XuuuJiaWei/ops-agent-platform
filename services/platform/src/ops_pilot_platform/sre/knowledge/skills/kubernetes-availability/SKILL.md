---
name: kubernetes-availability
description: Diagnose pod, workload, replica, scheduling, restart, crash-loop, eviction, and node availability incidents in Kubernetes.
---

# Kubernetes availability diagnosis

1. Resolve the alert to workload, pod, and node identities with `query_topology`.
2. Use `query_events` early for lifecycle evidence such as scheduling failure,
   scaling, restart, eviction, image failure, readiness loss, or node transition.
3. Discover replica, readiness, restart, and node signals with
   `list_metric_names`; establish the first state change with `query_metric_range`.
4. Use logs only after identifying the affected pod or container. Use traces to
   confirm downstream request impact, not to infer Kubernetes state.
5. Distinguish control-plane change, node failure, application crash, and resource
   pressure by their event and metric ordering. Stop when the lifecycle transition
   precedes and explains the lost availability.

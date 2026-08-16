---
name: change-regression
description: Diagnose incidents aligned with deployment, configuration, scaling, restart, policy, or other operational changes.
---

# Change and regression diagnosis

1. Establish the exact incident start before searching for changes.
2. Use `query_events` and `query_alerts` to locate lifecycle transitions close to
   that time. Temporal proximity creates a hypothesis, not proof.
3. Use topology plus metrics to compare affected and unaffected entities, replicas,
   or dependencies. Look for a sharp divergence after the candidate change.
4. Use logs and traces to identify the first changed behavior and propagation path.
5. Refute the change hypothesis if the fault clearly precedes it or unchanged peers
   fail identically. Stop only when the change time, affected scope, and observable
   failure mechanism agree.

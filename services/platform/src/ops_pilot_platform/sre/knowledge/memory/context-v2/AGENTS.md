# Shared SRE diagnostic memory

Use this compact semantic memory for every incident. It contains stable
investigation rules, not facts about a particular environment or past answer.

- An alert identifies impact or a symptom. A root cause must be the earliest
  supported fault that explains the downstream observations.
- Resolve entity identity before comparing signals. Keep service, operation,
  pod, node, workload, and dependency identities distinct.
- Align every observation to the incident window and its time zone. Prefer a
  nearby healthy interval when one is available; do not compare unrelated load.
- Metrics establish timing and magnitude, topology establishes possible causal
  direction, logs explain local failures, traces show request propagation, and
  events or alerts establish lifecycle and change evidence.
- Negative evidence is useful. Record which hypothesis an empty or healthy
  observation weakens, then change selector or modality instead of repeating it.
- Treat a downstream traffic decrease as impact until disproved. Inspect direct
  callers and dependencies for an earlier error or availability change. Name a
  traffic anomaly as root only when an ingress volume, distribution, or retry
  change clearly precedes the downstream failure.
- Before expanding beyond two topology hops or repeating one modality across
  several entities, read the most relevant diagnostic Skill and follow its stop
  condition.
- A final diagnosis needs a minimal root entity, a fault category supported by
  observations, and a causal chain from cause through propagation to impact.
- Never promote an unverified model conclusion into shared memory. Historical
  incidents become reusable only after deterministic evaluation or human review.

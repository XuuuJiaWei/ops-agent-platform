# Autonomous SRE Knowledge Evolution

Status: RFC

## Summary

OpsPilot already has three building blocks required for an eval-driven improvement loop:

1. an isolated RCA100 runner that records per-case outputs and execution telemetry;
2. deterministic Entity / Fault / Process scoring plus baseline/candidate comparison;
3. versioned, read-only SRE Skills and Memory injected into the diagnosis agent.

This RFC closes the remaining manual gap. A failed or inefficient run is converted into a bounded `FailureReport`; a separate knowledge optimizer proposes a typed `KnowledgePatch`; the host materializes an immutable candidate; Validation and one-shot Holdout evaluation decide whether the candidate becomes active.

```text
Stable Knowledge
      |
      v
Train Runs -> Failure Mining -> Failure Clusters
                               |
                               v
                       Knowledge Optimizer
                               |
                               v
                         KnowledgePatch
                               |
                               v
                         Static Guard
                               |
                               v
                         Validation
                               |
                    select at most one winner
                               |
                               v
                      one-shot Holdout
                         /           \
                      pass           fail
                       |              |
                       v              v
                    Promote         Reject
```

The loop improves **procedural knowledge (`SKILL.md`) and compact semantic memory (`AGENTS.md`) only**. It does not automatically mutate runtime code, tools, permissions, MCP configuration, or infrastructure.

## Design decisions after official-doc review

### 1. Use background knowledge optimization, not hot-path self-editing

Deep Agents supports agent-written Memory and Skills, but its documentation also recommends background consolidation when shared memory quality and concurrent writes matter. Production organization-level knowledge is typically read-only to the serving agent and written by application code.

OpsPilot therefore keeps the diagnosis agent read-only. A separate optimizer runs outside the serving path and returns a candidate; application code owns persistence and promotion.

References:

- https://docs.langchain.com/oss/python/deepagents/memory
- https://docs.langchain.com/oss/python/deepagents/going-to-production

### 2. Return a typed patch through `response_format`; do not give the optimizer file-write tools

Deep Agents and LangChain support Pydantic structured output directly through `response_format`. The optimizer should return a validated object rather than free-form Markdown or direct `edit_file` / `write_file` calls.

```python
class KnowledgePatch(BaseModel):
    target: Literal["skill", "memory"]
    operation: Literal["create", "update"]
    target_name: str
    failure_cluster_ids: list[str]
    trigger_conditions: list[str]
    rules: list[str]
    anti_patterns: list[str]
    evidence_requirements: list[str]
    stopping_conditions: list[str]
    rationale: str
```

The host renders the final `SKILL.md` / `AGENTS.md` content deterministically after schema and policy validation.

References:

- https://docs.langchain.com/oss/python/deepagents/customization
- https://docs.langchain.com/oss/python/langchain/structured-output

### 3. Separate checkpoint state from long-term knowledge storage

LangGraph checkpointers solve thread-scoped durable execution. Long-term knowledge belongs in a `BaseStore`.

Production knowledge should use a persistent store such as `PostgresStore`; Deep Agents exposes it as files through `StoreBackend`. The namespace must be explicit. `FilesystemBackend` remains acceptable for local benchmark/CLI usage but should not be the production web-server persistence mechanism.

Target production composition:

```text
LangGraph Checkpointer -> durable run/thread state
LangGraph PostgresStore -> cross-thread knowledge snapshots
DeepAgents StoreBackend -> read-only /skills and /memory view
KnowledgeRegistry       -> active version + candidate lifecycle
```

The serving host resolves an active version before runtime construction and mounts that immutable version read-only. Candidate writes are performed by application code into a new version namespace.

References:

- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/langgraph/add-memory
- https://docs.langchain.com/oss/python/deepagents/backends

### 4. Keep Eval deterministic first; use an LLM judge only where rules cannot express trajectory quality

The current RCA100 evaluator already exposes deterministic Entity / Fault / Process scores. Existing telemetry contains model-call counts, tool-call counts, token usage, tool argument hashes, result hashes, duration, and tool errors.

V1 failure mining should only claim failure classes that can be derived from those artifacts.

Deterministic quality signals:

- entity precision / recall / F1 deficit;
- fault score deficit;
- reasoning node-match deficit;
- evidence-hit deficit;
- invalid prediction / parse failure;
- task timeout / execution error.

Deterministic trajectory signals:

- same tool + same argument hash repeated;
- repeated tool-error signature;
- tool-call or model-call budget exhaustion;
- excessive calls against an explicit configured threshold.

Do **not** deterministically label semantic concepts such as `causal_order_inversion` unless the evaluator has direct evidence for that label. When a semantic trajectory judgment is needed, use a bounded LLM judge with an explicit rubric and store the result separately from deterministic scores.

LangSmith trajectory evaluation uses the same split: exact/structural trajectory matching where possible, LLM-as-judge for qualitative behavior.

References:

- https://docs.langchain.com/langsmith/trajectory-evals
- https://docs.langchain.com/langsmith/evaluation

### 5. Validation may iterate; Holdout is one-shot per evolution cycle

Train failures may be mined repeatedly and multiple candidate patches may compete on Validation. Holdout must not become another tuning set.

Rules:

1. `train` may influence failure attribution and candidate generation.
2. `validation` may be used repeatedly to rank/reject candidates.
3. only the best surviving candidate enters `holdout`.
4. `holdout` is executed once for that evolution cycle.
5. if holdout fails, the cycle ends; its per-case failure details are not fed back into candidate generation in the same cycle.
6. a future cycle must use a rotated/new holdout policy before using those failures for optimization.

This prevents repeated accept/reject feedback from silently overfitting the holdout set.

The split manifest is immutable and hashed:

```json
{
  "schema_version": 1,
  "name": "rca100-evolution-v1",
  "seed": 20260817,
  "train": ["..."],
  "validation": ["..."],
  "holdout": ["..."],
  "sha256": "..."
}
```

### 6. Langfuse is observability and score storage, not the promotion control plane

OpsPilot keeps local benchmark artifacts and `KnowledgeRegistry` as the source of truth. Langfuse receives traces and scores for debugging/analysis.

Use metadata/tags for values known at run start:

- `evolution_run_id`
- `knowledge_version`
- `candidate_id`
- `split`
- `phase`

Use Scores for values learned after execution:

- Entity / Fault / Process / Final
- duplicate-query rate
- parse success
- promotion decision

This matches Langfuse guidance: tags/metadata describe execution context; Scores represent evaluations. Large artifacts remain in OpsPilot storage rather than propagated metadata.

References:

- https://langfuse.com/docs/observability/best-practices
- https://langfuse.com/docs/evaluation/scores/overview
- https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk

### 7. LangSmith is an architectural reference, not a second runtime dependency

LangSmith's documented loop — recurring failure -> root cause -> proposed fix -> offline evaluator -> regression monitor — validates the architecture, but OpsPilot already uses Langfuse plus an isolated RCA100 harness.

Do not add LangSmith solely to duplicate tracing/evaluation storage. Keep the implementation provider-neutral and reuse the useful concepts.

Reference:

- https://docs.langchain.com/langsmith/engine

## Data contracts

### FailureReport

`FailureReport` is the only evaluator-derived input allowed to cross into optimization.

It contains bounded, answer-free information:

```text
case_ref_hash
quality_deficits
execution_failures
trajectory_signals
cost_metrics
trace_ref
```

It must not contain:

- ground-truth root-cause entity names;
- expected fault labels copied from the answer key;
- expected numeric evidence values;
- raw answer-key reasoning paths;
- task-specific answer text.

A train case may expose the agent's own prediction and its own actions because those already existed before evaluation.

### FailureCluster

Cluster reports by stable failure signature and coarse trajectory pattern. Candidate generation receives cluster summaries, not raw answer-key data.

```python
class FailureCluster(BaseModel):
    id: str
    signatures: list[str]
    case_count: int
    quality_summary: dict[str, float]
    trajectory_summary: dict[str, float]
    representative_trace_refs: list[str]
```

### KnowledgePatch

The patch is intentionally narrower than an arbitrary prompt rewrite. It can create/update a Skill or update compact semantic Memory. Delete operations are excluded from V1 to avoid accidental knowledge erosion.

### KnowledgeVersion

Each materialized candidate is immutable.

```json
{
  "version": "kv-...",
  "base_version": "kv-...",
  "content_sha256": "...",
  "generator": {"provider": "...", "model": "..."},
  "failure_cluster_ids": ["..."],
  "status": "proposed",
  "created_at": "..."
}
```

Lifecycle:

```text
PROPOSED
  -> STATIC_VALIDATED
  -> VALIDATION_PASSED
  -> HOLDOUT_PASSED
  -> ACTIVE

or

STATIC_REJECTED / VALIDATION_REJECTED / HOLDOUT_REJECTED
```

## Static candidate guard

A candidate is rejected before benchmark execution when any rule fails:

- Pydantic schema validation;
- only `skill` / `memory` targets;
- valid Agent Skills directory/name shape;
- no path traversal or arbitrary file path;
- no benchmark task identifiers or answer-key-only literals;
- bounded patch size and bounded total always-loaded Memory growth;
- no instructions to bypass permissions/HITL, read evaluator files, mutate runtime code, or invoke undeclared tools;
- exact normalized candidate hash has not already been rejected for the same stable base version.

For context efficiency, large/task-specific guidance belongs in Skills because Skills use progressive disclosure; only rules that are broadly relevant to every diagnosis belong in always-loaded Memory.

Reference:

- https://docs.langchain.com/oss/python/deepagents/skills

## Promotion policy

Promotion is deterministic and quality-first.

Required invariants:

```text
completion_rate == 100%
parse_success_rate == 100%
evaluation_coverage == 100%
```

Quality gate:

```text
Entity >= configured floor vs stable
Fault >= configured floor vs stable
Process >= configured floor vs stable
Final >= configured floor vs stable
```

Efficiency metrics are reported but never compensate for a failed quality gate:

```text
model_calls
tool_calls
total_tokens
elapsed_s
```

Validation may rank several candidates. Only one enters Holdout. Holdout compares the candidate against the same stable version on the fixed holdout split.

Activation uses compare-and-swap semantics:

```text
promote(candidate, expected_active_version=base_version)
```

If the active version changed while evaluation was running, promotion aborts and the candidate must be revalidated against the new stable base. This prevents two concurrent evolution runs from overwriting each other.

## Rejection-aware generation

Rejected candidates remain useful evidence.

The registry stores:

```text
candidate_hash
base_version
failure_cluster_ids
decision
reasons
quality_delta
cost_delta
```

Future optimizer calls receive concise rejected-patch summaries for the same failure clusters and are instructed not to reproduce the same change. V1 guarantees exact normalized-patch de-duplication; semantic de-duplication is advisory only and must not be used as an irreversible gate without a deterministic criterion.

## Orchestration

The workflow is a resumable state machine:

```text
LOAD_STABLE
 -> RUN_TRAIN
 -> MINE_FAILURES
 -> CLUSTER_FAILURES
 -> GENERATE_CANDIDATES
 -> STATIC_GUARD
 -> RUN_VALIDATION
 -> SELECT_WINNER
 -> RUN_HOLDOUT_ONCE
 -> PROMOTE_OR_REJECT
 -> RECORD
```

Every transition writes an artifact before moving to the next state. Re-running the same `evolution_run_id` resumes from the last completed transition.

The benchmark runner remains process-isolated. Answer-key loading stays in the evaluator process after the diagnosis subprocess exits.

## Proposed repository boundary

```text
benchmarks/rca100/
  splits/
    evolution-v1.json
  src/rca100_benchmark/
    failures.py
    trajectory.py
    feedback.py
    cli.py

services/platform/src/ops_pilot_platform/sre/
  evolution/
    contracts.py
    optimizer.py
    guard.py
    materializer.py
    registry.py
    promotion.py
    loop.py
  knowledge.py
```

The Runtime package remains domain-neutral. Autonomous evolution belongs in the SRE platform layer; benchmark scoring remains framework-neutral under `benchmarks/rca100`.

## CLI contract

```bash
ops_pilot evolve-sre \
  --dataset-dir <RCA100> \
  --answer-key-dir <controlled-answer-key> \
  --split benchmarks/rca100/splits/evolution-v1.json \
  --max-candidates 3 \
  --state-dir <evolution-artifacts>
```

Expected terminal summary:

```text
stable            kv-...
train failures    14
failure clusters  4
candidates        3
validation winner kv-...
holdout           PASS
promotion         ACTIVE
```

## Test plan

Unit tests:

- failure reports never serialize answer-key entity/type/evidence values;
- deterministic duplicate-query detection from tool + argument hashes;
- `KnowledgePatch` schema validation;
- path and benchmark-leakage guards;
- exact candidate de-duplication;
- immutable version materialization;
- Validation quality gate;
- Holdout can run only once per evolution cycle;
- CAS promotion rejects a stale base version;
- rejected candidate leaves active version unchanged;
- resume is idempotent at every state transition.

Integration tests use a fake agent/evaluator pair:

1. candidate improves Validation and Holdout -> active pointer changes once;
2. candidate improves Validation but regresses Holdout -> candidate rejected, active pointer unchanged;
3. two concurrent runs share the same base -> only one successful CAS promotion;
4. optimizer returns forbidden benchmark-specific content -> static rejection before any eval run.

## Out of scope

- automatic Python/runtime/tool mutation;
- automatic MCP or permission changes;
- online production self-modification;
- Multi-Agent diagnosis topology changes;
- replacing RCA100 scoring with an LLM judge;
- using Holdout failures to generate another candidate in the same cycle.

## Research basis

The design follows the useful parts of prior self-improvement work while adding explicit isolation and regression gates required for a production-style system:

- Reflexion: language feedback retained across trials — https://arxiv.org/abs/2303.11366
- Self-Refine: iterative feedback/refinement — https://arxiv.org/abs/2303.17651
- Voyager: reusable skill library learned from environment feedback — https://arxiv.org/abs/2305.16291
- AFlow: workflow optimization as a search problem — https://arxiv.org/abs/2410.10762

OpsPilot deliberately keeps V1's search space smaller than AFlow: Skills and semantic Memory are versioned data; executable workflow/code mutation remains out of scope until this safer loop is validated.

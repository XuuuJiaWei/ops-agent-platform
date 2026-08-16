# Telemetry Replay Benchmark

## Goal

The live OpenTelemetry Astronomy Shop chaos suite is the strongest source of
root-cause ground truth, but it is intentionally infrastructure-heavy. A normal
agent change should not require a fresh Kubernetes cluster and live fault
injection just to catch a regression in planning, tool selection, evidence use,
or token efficiency.

The replay benchmark separates those concerns:

```text
Live Chaos (high fidelity, expensive)
    -> fault injection + real telemetry + ground truth
    -> telemetry snapshot schema
    -> Replay Eval (deterministic, low cost)
    -> model/tool/prompt regression metrics
```

`services/agent/eval/cases/held_out/replay.yaml` is the first replay suite.
`services/agent/eval/replay/*.json` contains the tool evidence for each case.
The committed seed fixtures are explicitly marked `origin=synthetic_seed`; they
validate the replay harness and MUST NOT be described as captured production or
live-cluster telemetry.

## Why Replay Is A Separate Source

Replay cases use `source: replay`. The eval runner treats that source as an
isolation boundary:

- normal MCP servers are disabled for the run;
- only reduced read-only `search_traces` and `query` tools are exposed;
- each concurrent case is bound to its own fixture through a `ContextVar`;
- replay and live/static cases cannot be mixed in the same run;
- rubric and expected output remain evaluator metadata and are never inserted
  into the agent prompt.

This makes the evidence deterministic without turning the diagnosis into a
hard-coded answer path. The agent must still choose a useful tool, interpret the
returned telemetry, identify the service/failure mode, and explain its evidence.

## Run

From the repository root:

```bash
pnpm run eval:replay
```

The command uses the normal model configuration. For an OpenAI-compatible
provider, keep the API key in `.env` as `MODEL_API_KEY`; do not commit it.

Replay is a model evaluation, not a secret-free unit test. The regular GitHub
Actions CI continues to run lint/format/pytest without model credentials.

## Metrics

Replay uses the same quality and safety evaluators as the live eval stack:

- `pass_rate` and `pass_rate_wilson_lower`;
- `judge_root_cause`, `judge_evidence`, `judge_safety`, `judge_calibration`;
- `infrastructure_completion_rate` and `conditional_task_pass_rate`;
- `latency_p50_seconds` / `latency_p95_seconds`;
- `mean_tool_calls`;
- `input_token_count`, `output_token_count`, `total_token_count` per case;
- `mean_input_tokens`, `mean_output_tokens`, `mean_total_tokens`, `total_tokens`;
- `token_usage_coverage` so a provider that omits usage metadata cannot silently
  look artificially cheap.

Raw tokens are the canonical efficiency measurement. USD cost is deliberately
not hard-coded into the evaluator because provider/model prices are time-varying.
If a cost number is published, record the model, provider, price snapshot date,
and the conversion formula next to the result.

## Evidence Rules For Resume / README Claims

A metric is publishable only when its measurement boundary is named.

Good:

> On the 6-case synthetic telemetry replay suite, model X achieved A/B task
> passes with p95 latency Y s and mean total token usage Z; replay fixtures are
> deterministic synthetic seeds.

Good after a real chaos run:

> On N OpenTelemetry Demo fault-injection cases, the agent achieved A% diagnosis
> pass rate with 100% HITL safety and p95 latency Y s.

Not acceptable:

> Production incident accuracy is A%.

The project does not contain production incidents, and synthetic/replayed
results must never be relabeled as production evidence.

## Next Fidelity Step

The replay schema is intentionally small (`schema_version`, `case_id`,
`origin`, `captured_at`, `tools`). The next high-fidelity step is a recorder that
serializes selected Jaeger/Prometheus tool responses from successful live chaos
runs into this schema. That change should preserve data minimization: no company
telemetry, credentials, raw PII, or internal endpoints belong in committed
fixtures.

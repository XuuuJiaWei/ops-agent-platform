# Held-out eval cases

Cases in this directory are **never used during prompt/agent iteration**. They
exist only to produce a final, uncontaminated benchmark number.

## Why this matters

If every eval case has been seen during prompt tuning, the reported `pass_rate`
measures "how well the current prompt does on cases we optimized against", not
"how well the agent generalizes". A held-out split that is only run at explicit
benchmark time keeps one honest signal of generalization.

## Rules

- Do **not** look at these cases when debugging failures or tuning prompts.
- Do **not** include this directory in the default `pnpm eval` / `eval:quick`
  runs. Run it explicitly:

  ```bash
  cd services/agent
  uv run ops_pilot eval run --dataset-name otel_scenarios \
    --cases-dir eval/cases/held_out --run-name benchmark
  ```

- Add cases here from real production incidents or chaos-eval failures once
  they are no longer used for iteration (see docs/design/agent-eval.md §11.3).

This directory currently holds no cases — it is a placeholder for the held-out
split so the discipline is in place before the dataset grows.

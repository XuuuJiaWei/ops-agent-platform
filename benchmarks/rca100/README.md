# RCA100 benchmark

Standalone, framework-neutral integration for [AgenticOpsEval RCA100 v1.1](https://www.aiops.cn/gitlab/aiops-live-benchmark/agenticopseval). It evaluates the 103 offline cloud-native incident cases without importing or invoking OpsPilot's `AgentRuntime`.

## Setup

Obtain the publisher's public `RCA100/` data locally. The directory must contain `manifest.txt` and `cases/t001` through `cases/t103`; its published size is about 3.43 GB. Keep the controlled `answer_key/` in a separate directory outside the public dataset root. The official repository publishes the dataset and scoring contracts, not an agent SDK or required tool API.

```powershell
cd benchmarks/rca100
uv sync
```

## Agent protocol

The runner invokes any external command once per task. It writes one UTF-8 JSON object to the command's standard input:

```json
{
  "benchmark": "rca100",
  "task_id": "t001",
  "task": { "...": "the publisher's public task.json" },
  "case_directory": "D:/datasets/RCA100/cases/t001",
  "parquet_schemas": { "metrics": ["..."], "logs": ["..."] },
  "topology_path": "D:/datasets/RCA100/cases/t001/topology.json",
  "prediction_schema": { "...": "JSON Schema for the required response" }
}
```

The command reads the public files under that single `case_directory` and writes one prediction object to standard output:

```json
{
  "root_cause_entities": ["payment"],
  "root_cause_types": ["httpError5xx"],
  "reasoning": [
    {
      "step_type": "cause",
      "target": "payment",
      "fault_type": "httpError5xx",
      "evidence": [
        {
          "source_type": "metric",
          "signal": "error_rate",
          "comparator": ">=",
          "value": 0.4964574898785425,
          "unit": "ratio"
        }
      ]
    }
  ]
}
```

No specific agent framework, API client, or runtime lifecycle is imposed. The
OpsPilot adapter lives in `ops_pilot_platform.benchmarks.rca100`, outside the agent
harness. It injects the case-scoped `query_metric`, `query_logs`,
`query_traces`, `query_events`, `query_alerts`, and `query_topology` tools
through LangChain's official `tools` and `ToolRuntime` context interfaces.

## Run

Run an agent script for one blind task:

```powershell
uv run rca100-benchmark run --dataset-dir D:/datasets/RCA100 --task t001 --agent-command python D:/agents/my_rca_agent.py
```

Run the bundled OpsPilot adapter from this directory:

```powershell
uv run rca100-benchmark run --dataset-dir D:/datasets/RCA100 --task t001 --agent-command uv run --project ../../services --package ops-pilot-platform --extra rca100 ops_pilot rca100-agent
```

Run the full manifest and persist results:

```powershell
uv run rca100-benchmark run --dataset-dir D:/datasets/RCA100 --all --output ../../artifacts/rca100.json --agent-command python D:/agents/my_rca_agent.py
```

Pass `--answer-key-dir` only in a controlled evaluator environment. The key is loaded after the agent command exits, never included in the input contract, and scored as `0.4 × Entity + 0.3 × Fault + 0.3 × Process`. Fault partial credit follows the publisher's taxonomy (`1.0` exact, `0.5` same L2, `0.25` same L1). Process gives equal weight to causal-node and numeric observability-checkpoint matches.

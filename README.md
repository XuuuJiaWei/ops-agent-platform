# OpsPilot

OpsPilot composes one DeepAgents runtime per entrypoint from one validated
configuration document. Credentials never belong in it.

```
config/runtime.example.yaml  → tracked defaults + entrypoint overrides
config/runtime.yaml          → ignored local runtime choices
.env                         → model, database, MCP, sandbox, and tracing secrets
```

The browser owns CopilotKit's frontend tool declarations. The Node bridge only
adapts the Web runtime to CopilotKit; it does not choose models or tools.

```text
apps/                  React UI and CopilotKit protocol bridge
services/agent/        host-neutral DeepAgents harness library
services/platform/     FastAPI/Web/A2A/AG-UI hosts and composition
benchmarks/            standalone evaluators and benchmark infrastructure
config/                one ignored runtime.yaml plus tracked example
```

```text
apps/                  React UI and CopilotKit protocol bridge
services/agent/        host-neutral DeepAgents harness library
services/platform/     FastAPI/Web/A2A/AG-UI hosts and composition
benchmarks/            standalone evaluators and benchmark infrastructure
config/                one ignored runtime.yaml plus tracked example
```

## Configure once

```powershell
pnpm install
cd services; uv sync --all-packages; cd ..
Copy-Item .env.example .env
Copy-Item config/runtime.example.yaml config/runtime.yaml
```

Edit the top-level defaults once and keep only real differences under `entrypoints`. The
`deepagent` subtree follows `create_deep_agent`'s injection points:

```yaml
deepagent:
  model:
    provider: deepseek
    name: deepseek-v4-flash
    base-url: https://api.deepseek.com
  checkpointer:
    backend: none
entrypoints:
  web:
    deepagent:
      checkpointer:
        backend: memory
  eval:
    deepagent:
      name: ops-pilot-eval
```

Put only secrets in `.env`:

```dotenv
DEEPSEEK_API_KEY=...
DATABASE_URL=...                 # only for a YAML entry using postgres
MCP_BASIC_AUTH_HEADER=...         # only for authenticated MCP endpoints
OPEN_SANDBOX_API_KEY=...          # only for an enabled sandbox
```

## Start the local Web stack

Start the configured OpenSandbox service first:

```powershell
pnpm sandbox:up
```

```powershell
pnpm dev
```

The command selects `entrypoints.web` and starts Vite, FastAPI/AG-UI, and
the CopilotKit bridge with one consistent host, port, agent id, and transport
configuration. Start processes separately only when diagnosing one layer:

```powershell
pnpm run dev:backend
pnpm run dev:copilot
pnpm run dev:web
```

## Run AIOpsLab benchmarks

Bootstrap AIOpsLab once:

```powershell
pnpm benchmark:setup
```

Then edit `entrypoints.benchmark` in `config/runtime.yaml`:

```yaml
entrypoints:
  benchmark:
    benchmark:
      aiopslab:
        directory: D:/dev/projects/AIOpsLab
```

`DEEPSEEK_API_KEY` remains in `.env`. Run a problem with its fully isolated
runtime:

```powershell
pnpm benchmark:status
pnpm benchmark -- --problem <aiopslab-problem-id> --max-steps 30
pnpm benchmark -- --problem <aiopslab-problem-id> --results-dir ./artifacts/aiopslab
```

The launcher layers the editable AIOpsLab checkout only into this one `uv run`
command, leaving normal Web, eval, and development environments untouched.

## RCA100 benchmark

RCA100 lives as an independent evaluator under [benchmarks/rca100](benchmarks/rca100/README.md). Its OpsPilot adapter and case-scoped PyArrow tool live in the benchmark domain, outside `ops_pilot.agent`; the evaluator invokes it through JSON-over-stdio.

```powershell
pnpm benchmark:rca100 -- run --dataset-dir D:/datasets/RCA100 --task t001 --agent-command uv run --project ../../services --package ops-pilot-platform --extra rca100 ops_pilot rca100-agent
```

## Validate

```powershell
pnpm check
```

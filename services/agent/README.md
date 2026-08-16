# ops_pilot service

Python 3.12 service managed by `uv`.

## Commands

```bash
uv sync
uv run ops_pilot serve --host 127.0.0.1 --port 8123
uv run ops_pilot smoke agent
uv run pytest
```

Run the official AIOpsLab benchmark adapter after installing AIOpsLab itself
(its upstream project is intentionally not a service dependency):

```bash
git clone --recurse-submodules https://github.com/microsoft/AIOpsLab.git
cd AIOpsLab && uv pip install -e .
cd ../ops-agent-platform/services/agent
uv run ops_pilot benchmark \
  --problem astronomy_shop_payment_service_failure-localization-1 \
  --max-steps 30
```

AIOpsLab owns the benchmark lifecycle, action parser, session trace, and
evaluation. OpsPilot only adapts its generic text-agent interface to the
official `Agent.get_action` interface. Additional benchmarks belong under
`ops_pilot.benchmarks` and must not add business tools, prompt fragments, or
repositories to the core runtime.

## Runtime

The backend exposes AG-UI under `/chat`, A2A JSON-RPC at `/a2a/jsonrpc`, agent-card discovery at `/a2a/.well-known/agent-card.json`, and health/status endpoints. These protocol surfaces share the same DeepAgents runtime.

Runtime guardrails reuse framework primitives where available: LangChain model/tool call limits and retry middleware, DeepAgents human approval, LangGraph checkpoints, and the configured sandbox backend. `RunController` provides the outer deadline/cancellation boundary. The core runtime is business-neutral; the backend explicitly composes its Spaces and CopilotKit extensions.

## Sandbox

Set the OpenSandbox endpoint in root `.env` / `config/config.yaml` to isolate filesystem and command execution. Configured local skills are synchronized into the sandbox before the graph is created.

## Durable execution

By default the runtime uses an in-memory LangGraph checkpointer and in-memory A2A task store. Set `persistence.backend: postgres` and `DATABASE_URL` to persist checkpoints/tasks across process restarts.

```yaml
persistence:
  backend: postgres
  setup_on_start: true
```

```bash
DATABASE_URL=postgresql://ops_pilot:ops_pilot@127.0.0.1:5433/ops_pilot
```

A local Postgres stack remains under `deploy/postgres` for development. Integration tests for PostgreSQL paths run only when `TEST_DATABASE_URL` is set.

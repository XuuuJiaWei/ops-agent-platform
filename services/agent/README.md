# ops_pilot

Python 3.12 service managed by `uv`.

## Commands

```bash
uv sync
uv run langgraph dev --host 127.0.0.1 --port 2024
uv run ops_pilot serve --host 127.0.0.1 --port 8123
uv run ops_pilot smoke a2a
uv run pytest
```

The service reads root `.env` when present. Leave Langfuse keys empty for local startup with tracing disabled.
The standard backend exposes AG-UI under `/chat`, A2A JSON-RPC at `/a2a/jsonrpc`, agent-card discovery at `/a2a/.well-known/agent-card.json`, and a health endpoint at `/health`.

## DeepAgents Sandbox

Set the OpenSandbox Gardener endpoint in the root `.env` to run DeepAgents filesystem and command execution in the remote sandbox backend. The domain in `config/config.yaml` (`open_sandbox.domain: opensandbox.${OTEL_SHOOT_DOMAIN}`) interpolates the shoot identity; only the API key is a raw secret:

```bash
OTEL_SHOOT_DOMAIN=abc123.cloud.shoot.canary.k8s-hana.ondemand.com
OPEN_SANDBOX_API_KEY=...
```

When both values are present, the backend automatically passes an `OpensandboxBackend` to `create_deep_agent(...)`. Configured local skills are uploaded into `/workspace/skills/...` before the graph is created so DeepAgents can discover `SKILL.md` files through the sandbox backend. Set `OPEN_SANDBOX_ENABLED=false` to force the default in-memory state backend.

`OPEN_SANDBOX_TIMEOUT_SECONDS` controls the OpenSandbox lease lifetime. The backend renews an active sandbox before use, and rebuilds the runtime with a fresh sandbox when a user returns after the previous sandbox has expired.

## Durable Execution (persistent checkpoint + task recovery)

By default the runtime uses an in-memory LangGraph checkpointer and an in-memory A2A task store: conversations and tasks are lost on restart. Set `persistence.backend: postgres` to make them durable.

```yaml
# config/config.yaml
persistence:
  backend: postgres      # memory (default) | postgres
  setup_on_start: true   # create checkpoints/writes/tasks tables on startup
```

```bash
# .env (secret DSN only; kept out of config.yaml)
DATABASE_URL=postgresql://ops_pilot:ops_pilot@127.0.0.1:5433/ops_pilot
```

Start a local Postgres with the bundled compose stack (see `deploy/postgres/README.md`):

```bash
cd deploy/postgres && cp .env.example .env && docker compose --env-file .env up -d
```

With `backend: postgres`, LangGraph writes a checkpoint per super-step to the `checkpoints`/`writes` tables (`AsyncPostgresSaver` over a process-lived connection pool), and A2A tasks persist via the SDK's `DatabaseTaskStore`. After a restart, reconnecting with the same `thread_id` resumes the conversation from its last checkpoint. `setup_on_start: true` creates tables on boot; use a managed migration in production instead.

Integration tests for the Postgres paths run only when `TEST_DATABASE_URL` is set:

```bash
TEST_DATABASE_URL=postgresql://ops_pilot:ops_pilot@127.0.0.1:5433/ops_pilot uv run pytest tests/unit/agent/test_persistence.py
```

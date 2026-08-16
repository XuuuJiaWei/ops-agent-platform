# Local Postgres

Durable execution backend for ops_pilot: LangGraph checkpoints
(`AsyncPostgresSaver`), the A2A `DatabaseTaskStore`, and the Copilot Runtime
AG-UI event log used for browser history replay. The `pgvector` image is used
so the same instance can later back the long-term memory Store.

## Start

```bash
cd deploy/postgres
cp .env.example .env        # first time only
docker compose --env-file .env up -d
docker compose ps
```

Postgres listens on `127.0.0.1:5433` (host) to avoid clashing with a default
local Postgres on 5432 and the Langfuse stack's Postgres on 15432.

## Ops Agent Configuration

Point the backend at this instance. In the repository root `.env`:

```bash
DATABASE_URL=postgresql://ops_pilot:ops_pilot@127.0.0.1:5433/ops_pilot
```

Enable durability for the web entry and the separate CopilotKit event journal:

```dotenv
OPS_PILOT_WEB_PERSISTENCE_BACKEND=postgres
OPS_PILOT_WEB_PERSISTENCE_SETUP_ON_START=true
COPILOTKIT_EVENT_STORE_BACKEND=postgres
COPILOTKIT_EVENT_STORE_SETUP_ON_START=true
```

On the next `pnpm dev`, LangGraph creates the `checkpoints`/`writes` tables,
the A2A store creates `tasks`, and Copilot Runtime creates
`copilotkit_agent_runs`/`copilotkit_run_events`/`copilotkit_thread_locks`.
Restarting the services now resumes graph execution and replays the visible
conversation using the same `thread_id`.

## Verify durable resume

```bash
# 1. Start Postgres + `pnpm dev`, then send a message.
# 2. Restart the backend and Copilot Runtime, then reload the browser.
# 3. Reopen the same thread: its UI events replay, and another message
#    continues from the persisted LangGraph checkpoint.
```

## Useful Commands

```bash
cd deploy/postgres
docker compose logs -f postgres
docker compose exec postgres psql -U ops_pilot -d ops_pilot -c '\dt'
docker compose down          # keep data
docker compose down -v       # delete the data volume
```

Use `docker compose down -v` only when you want to discard local checkpoints,
tasks, and Copilot conversation events.

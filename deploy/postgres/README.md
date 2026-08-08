# Local Postgres

Durable execution backend for ops_pilot: LangGraph checkpoints
(`AsyncPostgresSaver`) and the A2A `DatabaseTaskStore`. The `pgvector` image is
used so the same instance can later back the long-term memory Store.

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

Enable the durable backend in `config/config.yaml`:

```yaml
persistence:
  backend: postgres
  setup_on_start: true   # creates checkpoints/writes/tasks tables on startup
```

On the next backend start, LangGraph creates the `checkpoints`/`writes` tables
and the A2A store creates `tasks`. Restarting the backend now resumes
conversations (same `thread_id`) and A2A tasks from Postgres.

## Verify durable resume

```bash
# 1. Start Postgres + backend, send a message on thread "t1".
# 2. Kill the backend, restart it.
# 3. Send another message on thread "t1": earlier context is still present,
#    reconstructed from the persisted checkpoint.
```

## Useful Commands

```bash
cd deploy/postgres
docker compose logs -f postgres
docker compose exec postgres psql -U ops_pilot -d ops_pilot -c '\dt'
docker compose down          # keep data
docker compose down -v       # delete the data volume
```

Use `docker compose down -v` only when you want to discard local checkpoints
and tasks.

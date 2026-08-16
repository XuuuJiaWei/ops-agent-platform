# Repository Guidelines

## Architecture

`apps/web` is the Vite/CopilotKit UI and `apps/copilot-runtime` is its Node protocol bridge. Python application code lives in `services/agent/src/ops_pilot`; backend tests live in `services/agent/tests`.

Every executable host owns an explicit runtime composition in `ops_pilot.entrypoints`:

- `web` may opt into CopilotKit, Spaces, A2A, persistence, and MCP servers.
- `eval`, `benchmark`, and `langgraph` each declare their own model, MCP catalog, tools, middleware, persistence, and sandbox choices.

The core runtime consumes `RuntimeSpec` only. It must not load a profile file, infer host capabilities, or depend on the Web/CopilotKit protocol. Browser tools remain React declarations; secrets, model clients, and MCP transports remain in the owning backend entrypoint.

## Configuration and lifecycle

Use the entrypoint-scoped `RuntimeEnvironment` Pydantic Settings module to load `config/entries/<entry>.yaml`. Each YAML file declares only that entrypoint's non-sensitive runtime composition; `.env` supplies explicit credential aliases. Keep capability selection local to its entrypoint, never in a process-wide singleton.

Use official SDK abstractions before hand-written adapters:

- Pydantic Settings at process/configuration boundaries and Pydantic models for API schemas.
- FastAPI `lifespan` for application-owned resources; startup acquires them and shutdown closes them.
- LangChain/DeepAgents model factories, middleware, MCP adapters, backends, and checkpointers for agent execution.

Every created client, pool, runtime extension, task store, or background task needs one clear owner and a matching shutdown path. Do not allocate durable resources per request.

## Tooling

- JavaScript: pnpm (`pnpm@10.33.2`), Vite/React/TypeScript, ESLint, Prettier, Vitest.
- Python: Python 3.12, uv, FastAPI/Uvicorn, DeepAgents/LangGraph, Ruff, Pyright, pytest.

From the repository root:

```bash
pnpm install
cd services/agent && uv sync

pnpm dev
pnpm lint
pnpm run format:check
pnpm typecheck
pnpm test
pnpm check
```

Use `pnpm run lint:web`, `pnpm run test:backend`, and the other scoped scripts while iterating. `pnpm check` is the handoff gate and includes Pyright.

## Code and tests

Use TypeScript/React in `apps/web` and Python 3.12 in `services/agent`. Keep policy, prompts, tools, data access, sandbox/MCP lifecycle, and protocol adapters behind the backend composition boundary. Prefer deleting obsolete compatibility code and rebuilding focused tests over preserving stale configuration paths.

Place Python unit tests in `services/agent/tests/unit` and integration tests in `services/agent/tests/integration`; use unique `test_*.py` basenames. Frontend tests use Vitest only; the Copilot Runtime bridge uses `node --test`.

## Security and delivery

Never commit secrets. Copy the applicable `.env.example` and use the documented entrypoint prefix. Keep company data features disabled unless explicitly approved.

Use short imperative Conventional Commit messages. Before committing, run the relevant checks; run `pnpm check` for cross-stack or architectural changes. PRs describe runtime/data-boundary changes and include screenshots for UI changes.

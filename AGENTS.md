# Repository Guidelines

## Architecture

`apps/web` is the Vite/CopilotKit UI and `apps/copilot-runtime` is its Node protocol bridge. Python is an official uv workspace under `services/` with one shared lockfile:

- `services/agent` is the host-neutral DeepAgents harness. It owns models, MCP, sandbox, skills, reliability, persistence, and tracing.
- `services/platform` owns executable composition, FastAPI, CopilotKit/AG-UI, A2A, health, Spaces, LangGraph export, eval, and benchmark adapters.

Dependency direction is `platform -> agent`. The agent harness consumes `RuntimeSpec` only and exposes official DeepAgents/LangChain injection points (`tools`, `middleware`, and `context_schema`). Domain and protocol identifiers are mapped to generic `thread_id`, `run_id`, metadata, and configurable values at the platform boundary.

## Configuration and lifecycle

Use `ops_pilot_platform.entrypoints.RuntimeEnvironment` to merge top-level defaults with `entrypoints.<name>` from local `config/runtime.yaml`. Track `config/runtime.example.yaml`; keep `runtime.yaml` local and `.env` limited to explicit credential aliases. `deepagent` is a top-level key and mirrors `create_deep_agent` inputs. Entrypoints contain only real overrides. `system-prompt` accepts inline text or a prompt document under `config/prompts/` (`*.md`/`*.txt`, relative to the repo root); the platform resolves it when composing the runtime spec.

Spaces belongs to `ops_pilot_platform.web.spaces`. Agent-facing operations are CopilotKit `useFrontendTool` declarations in React.

Use official SDK abstractions before hand-written adapters:

- Pydantic Settings at process/configuration boundaries and Pydantic models for API schemas.
- FastAPI `lifespan` for application-owned resources; startup acquires them and shutdown closes them.
- LangChain/DeepAgents model factories, middleware, MCP adapters, backends, and checkpointers for agent execution.

Every created client, pool, task store, or background task needs one clear owner and a matching shutdown path.

## Tooling

- JavaScript: pnpm (`pnpm@10.33.2`), Vite/React/TypeScript, ESLint, Prettier, Vitest.
- Python: Python 3.12, uv, FastAPI/Uvicorn, DeepAgents/LangGraph, Ruff, Pyright, pytest.

From the repository root:

```bash
pnpm install
cd services && uv sync --all-packages

pnpm dev
pnpm lint
pnpm run format:check
pnpm typecheck
pnpm test
pnpm check
```

Use `pnpm run lint:web`, `pnpm run test:backend`, and the other scoped scripts while iterating. `pnpm check` is the handoff gate and includes Pyright.

## Code and tests

Use TypeScript/React in `apps/web` and Python 3.12 in the `services` workspace. Keep the agent harness host-neutral; platform and benchmark domains inject capabilities through its public spec.

Co-locate Python tests with their workspace member under `services/<member>/tests`. Frontend tests use Vitest; the Copilot Runtime bridge uses `node --test`.

## Security and delivery

Never commit secrets or `config/runtime.yaml`. Copy the tracked examples and keep company data features disabled unless explicitly approved.

Use short imperative Conventional Commit messages. Before committing, run the relevant checks; run `pnpm check` for cross-stack or architectural changes. PRs describe runtime/data-boundary changes and include screenshots for UI changes.

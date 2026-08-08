# Repository Guidelines

## Project Structure & Module Organization

This repo contains a thin CopilotKit/Vite frontend and an `ops_pilot` DeepAgents backend. Frontend code lives in `apps/web/src`; the local CopilotKit Runtime bridge lives in `apps/copilot-runtime/src`. Backend Python code lives in `services/agent/src/ops_pilot`, with tests under `services/agent/tests`. Shared configuration examples live in `config/`, documentation in `docs/`, archived legacy frontend artifacts in `archives/`, and optional DeepAgents skills in `skills/`.

Keep agent policy, prompts, tools, data access, sandbox lifecycle, MCP lifecycle, tracing, and protocol adapters in the backend. The frontend should stay a standard CopilotKit UI surface that forwards to the local runtime/backend.

## Build Tools & Runtime Stack

- JavaScript workspace: `pnpm` (`packageManager` is `pnpm@10.33.2`).
- Frontend: Vite 8, React 19, TypeScript, Tailwind CSS 4, ESLint 9, lucide-react.
- Copilot runtime: Node ESM service in `apps/copilot-runtime`, using `@copilotkit/runtime`.
- Backend: Python 3.12, `uv`, hatchling build backend, FastAPI/Uvicorn, DeepAgents, LangGraph, MCP adapters, SAP AI SDK, OpenSandbox.
- Backend quality tools: `ruff` for linting and formatting, `pytest` plus `pytest-asyncio` for tests.

## Build, Test, And Development Commands

- `pnpm install`: install workspace JavaScript dependencies.
- `cd services/agent && uv sync`: install Python backend dependencies.
- `pnpm dev`: run preflight checks, then start web, backend, and Copilot runtime together.
- `pnpm run dev:web`: start only the Vite web app wrapper.
- `pnpm run dev:backend`: start the FastAPI backend through `uv run ops_pilot serve`.
- `pnpm run dev:copilot`: start the local CopilotKit Runtime bridge.
- `pnpm run dev:langgraph`: optional LangGraph API/Studio debugging path.
- `pnpm --filter "./apps/web" build`: type-check and build the web app.
- `pnpm run test`: run backend tests through `uv run pytest`.
- `pnpm run smoke:model`, `pnpm run smoke:agent`, `pnpm run smoke:a2a`, `pnpm run smoke:local`: targeted backend smoke checks.

## Formatting, Linting, And Type Checks

For backend changes, run these from `services/agent`:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest
```

Use Ruff's formatter when changing Python code:

```bash
uv run ruff format src tests
```

Use Ruff auto-fixes when appropriate, but review the diff afterward:

```bash
uv run ruff check --fix src tests
```

For frontend changes, run:

```bash
pnpm --filter "./apps/web" typecheck
pnpm --filter "./apps/web" lint
pnpm --filter "./apps/web" build
```

## Coding Style & Naming Conventions

Use TypeScript/React for `apps/web` and Python 3.12 for `services/agent`. Python package imports should use `ops_pilot.*`. The backend CLI command is `ops_pilot`. Prefer existing local modules and patterns over new abstractions, and keep frontend state/UI concerns separate from backend agent behavior.

Backend tests use `pytest`; place unit tests in `services/agent/tests/unit` and integration tests in `services/agent/tests/integration`. Name test files `test_*.py`, but avoid duplicate basenames in different test folders because pytest may import them as top-level modules.

## Sandbox, MCP, And Lifecycle Notes

OpenSandbox is managed through the backend sandbox manager, not directly by callers. Agent code should ask for an execution environment through the runtime/backend abstraction; allocation policy (`process`, `thread`, or `run`), TTL renewal, cleanup, skill sync, concurrency limits, and visible `/workspace` path mapping belong in the sandbox module.

MCP servers should use explicit persistent sessions when the server supports it. Treat MCP tool `isError` responses and structured tool outputs as model-visible tool results unless the local program itself failed unexpectedly.

## Commit & Pull Request Guidelines

Use short, imperative commit messages, preferably Conventional Commit style, for example `fix: stabilize copilot runtime routing` or `docs: update sandbox lifecycle notes`. Pull requests should include a concise summary, validation commands run, screenshots for UI changes, and notes about configuration or data-boundary impacts.

## Security & Configuration Tips

Do not commit secrets. Secrets live in `.env` (copy from `.env.example`); regular configuration, including MCP servers and OpenSandbox options, lives in `config/config.yaml` (copy from `config/config.example.yaml`). Keep Copilot Cloud or Enterprise Intelligence Platform features disabled for company data unless explicitly approved. Langfuse is optional; missing credentials should leave tracing disabled.

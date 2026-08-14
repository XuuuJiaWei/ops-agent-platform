# Repository Guidelines

## Project Structure & Module Organization

This repo contains a thin CopilotKit/Vite frontend and an `ops_pilot` DeepAgents backend. Frontend code lives in `apps/web/src`; the local CopilotKit Runtime bridge lives in `apps/copilot-runtime/src`. Backend Python code lives in `services/agent/src/ops_pilot`, with tests under `services/agent/tests`. Shared configuration examples live in `config/`, documentation in `docs/`, and optional DeepAgents skills in `skills/`.

Keep agent policy, prompts, tools, data access, sandbox lifecycle, MCP lifecycle, tracing, and protocol adapters in the backend. The frontend should stay a standard CopilotKit UI surface that forwards to the local runtime/backend.

## Build Tools & Runtime Stack

- JavaScript workspace: `pnpm` (`packageManager` is `pnpm@10.33.2`).
- Frontend: Vite 8, React 19, TypeScript, Tailwind CSS 4, ESLint 9, lucide-react.
- Copilot runtime: Node ESM service in `apps/copilot-runtime`, using `@copilotkit/runtime`.
- Backend: Python 3.12, `uv`, hatchling build backend, FastAPI/Uvicorn, DeepAgents, LangGraph, MCP adapters, SAP AI SDK, OpenSandbox.
- Backend quality tools: `ruff` (lint + format), `pyright` (type check), `pytest` plus `pytest-asyncio` (tests).
- Frontend quality tools: `eslint` (lint), `prettier` (format, owned at the repo root over `apps/**`), `tsc` (type check), `vitest` (the single test runner for `apps/web`). The `copilot-runtime` bridge uses `node --test`.

## Build, Test, And Development Commands

Root `package.json` exposes cross-stack aggregate commands. Each has per-stack variants (`:backend`, `:web`, `:copilot`) so you can scope to one side.

Setup:

- `pnpm install`: install workspace JavaScript dependencies.
- `cd services/agent && uv sync`: install Python backend dependencies.

Development (unchanged):

- `pnpm dev`: preflight checks, then start web, backend, and Copilot runtime together.
- `pnpm run dev:web` / `dev:backend` / `dev:copilot` / `dev:langgraph`: start one process.

Quality gates (aggregate across backend + frontend):

- `pnpm lint`: `ruff check` (backend) + `eslint` (web).
- `pnpm format`: `ruff format` (backend) + `prettier --write` (frontend).
- `pnpm run format:check`: verify formatting without writing.
- `pnpm typecheck`: `pyright` (backend) + `tsc --noEmit` (web).
- `pnpm test`: `pytest` (backend) + `vitest run` (web) + `node --test` (copilot runtime).
- `pnpm check`: run all of the above in sequence (`lint` → `format:check` → `typecheck` → `test`).

Other:

- `pnpm --filter "./apps/web" build`: type-check and build the web app.
- `pnpm run smoke:model`, `smoke:agent`, `smoke:a2a`, `smoke:local`: targeted backend smoke checks.
- `pnpm run eval`, `eval:quick`, `eval:calibration`, `eval:chaos`: agent evaluation (see `docs/design/agent-eval.md`).

## Formatting, Linting, And Type Checks

Prefer the aggregate commands from the repo root — they cover both stacks:

```bash
pnpm lint          # ruff check (backend) + eslint (web)
pnpm format        # ruff format (backend) + prettier --write (frontend)
pnpm run format:check
pnpm typecheck     # pyright (backend) + tsc (web)
pnpm test          # pytest + vitest + node --test
pnpm check         # all of the above, in order
```

Scope to one stack with the `:backend` / `:web` / `:copilot` variants (e.g. `pnpm run lint:web`, `pnpm run test:backend`).

Backend-only, run from `services/agent`:

```bash
uv run ruff check src tests          # lint
uv run ruff format src tests         # format (add --check to verify only)
uv run ruff check --fix src tests    # auto-fix; review the diff afterward
uv run pyright                       # type check
uv run pytest                        # tests
```

Frontend formatting is Prettier, owned at the repo root over `apps/**` (config in `.prettierrc.json`, scope in `.prettierignore`). `eslint-config-prettier` is applied last in `apps/web/eslint.config.mjs` so ESLint does not fight Prettier on style.

> **Pyright is not yet a CI gate.** `uv run pyright` currently reports pre-existing type errors in backend code; `pnpm check` includes it so the errors stay visible as tech debt, but CI does not run pyright (so CI stays green). Do not treat a red `typecheck:backend` as a blocker until those errors are cleaned up and pyright is promoted to a gate.

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

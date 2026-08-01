# Repository Guidelines

## Project Structure & Module Organization

This repo contains a CopilotKit frontend and an `ops_pilot` backend. Frontend code lives in `apps/web/src`; the local CopilotKit Runtime lives in `apps/copilot-runtime/src`. Backend Python code is in `services/agent/src/ops_pilot`, with tests under `services/agent/tests`. Shared configuration examples live in `config/`, documentation in `docs/`, archived legacy frontend artifacts in `archives/`, and optional skills in `skills/`.

## Build, Test, and Development Commands

- `pnpm install`: install workspace JavaScript dependencies.
- `cd services/agent && uv sync`: install Python backend dependencies.
- `pnpm dev`: run the full local development stack: web app, Copilot runtime, AG-UI backend, and A2A backend.
- `pnpm --filter "./apps/web" build`: type-check and build the web app.
- `pnpm run test`: run backend tests via `uv run pytest`.
- `pnpm run smoke:model`, `pnpm run smoke:agent`, `pnpm run smoke:a2a`: run targeted backend smoke checks.

## Coding Style & Naming Conventions

Use TypeScript/React for `apps/web` and Python 3.12 for `services/agent`. Keep the frontend thin and standard CopilotKit-based; agent policy, prompts, tools, and data access belong in the backend. Python package imports should use `ops_pilot.*`. The backend CLI command is `ops_pilot`. Run `ruff` for Python style and ESLint/TypeScript checks for frontend changes.

## Testing Guidelines

Backend tests use `pytest`; place unit tests in `services/agent/tests/unit` and integration tests in `services/agent/tests/integration`. Name test files `test_*.py`. For backend changes, run `cd services/agent && uv run ruff check src tests && uv run pytest`. For frontend changes, run `pnpm --filter "./apps/web" typecheck` and `pnpm --filter "./apps/web" lint`.

## Commit & Pull Request Guidelines

No Git history is available in this workspace to infer an established convention. Use short, imperative commit messages, preferably Conventional Commit style, for example `fix: stabilize copilot runtime routing` or `docs: update product README`. Pull requests should include a concise summary, validation commands run, screenshots for UI changes, and notes about configuration or data-boundary impacts.

## Security & Configuration Tips

Do not commit secrets. Copy `.env.example` to `.env` for local values. Keep Copilot Cloud or Enterprise Intelligence Platform features disabled for company data unless explicitly approved. Langfuse is optional; missing credentials should leave tracing disabled.

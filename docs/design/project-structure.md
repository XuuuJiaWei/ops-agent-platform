# Project Structure Design

Date: 2026-07-31

## 1. Design Goals

- [ ] Keep the repository local-first and easy to start with one command.
- [ ] Separate frontend, agent runtime, protocol adapters, configuration, and documentation clearly.
- [ ] Preserve official protocol compatibility for `/chat/*` and Google A2A instead of hand-rolling protocol details in random modules.
- [ ] Put complex behavior behind small, stable module interfaces.
- [ ] Make `/chat` and `/a2a` share the same DeepAgent capability surface through a common agent factory.
- [ ] Keep SAP AI Core, MCP, skills, Langfuse, and A2A integration testable without a browser.
- [ ] Leave obvious extension points for an agent-native ops dashboard, custom subagents, production auth, and persistent task stores.

## 2. Recommended Repository Layout

```text
ops-agent-platform/
  README.md
  AGENTS.md
  package.json
  pnpm-lock.yaml
  pnpm-workspace.yaml
  .env.example
  .gitignore

  apps/
    web/
      package.json
      index.html
      vite.config.ts
      tsconfig.json
      eslint.config.mjs
      public/
      src/
        App.tsx
        main.tsx
        features/
          chat/
            components/
              chat-panel.tsx
              message-list.tsx
              message-composer.tsx
              stream-status.tsx
            hooks/
              use-deepagent-chat.ts
            model/
              thread-title.ts
              types.ts
          threads/
            components/
              thread-sidebar.tsx
              thread-list.tsx
            hooks/
              use-thread-cache.ts
            model/
              thread-cache.ts
          ops-dashboard/
            components/
              dashboard-shell.tsx
              placeholder-panel.tsx
            README.md
        lib/
          env.ts
          langgraph.ts
          routes.ts
        components/
          ui/
        styles/
          global.css

  services/
    agent/
      pyproject.toml
      uv.lock
      langgraph.json
      README.md
      src/
        ops_pilot/
          __init__.py
          config/
            __init__.py
            settings.py
            paths.py
            mcp_schema.py
            subagents_schema.py
          agent/
            __init__.py
            factory.py
            graph.py
            runtime.py
            state.py
          models/
            __init__.py
            sap_genai.py
            smoke.py
          mcp/
            __init__.py
            loader.py
            registry.py
            status.py
          skills/
            __init__.py
            resolver.py
            validator.py
          observability/
            __init__.py
            langfuse.py
            metadata.py
          a2a/
            __init__.py
            app.py
            executor.py
            mapper.py
            task_store.py
            agent_card.py
          health/
            __init__.py
            app.py
            status.py
          tools/
            __init__.py
            smoke_tools.py
          cli/
            __init__.py
            main.py
            smoke_model.py
            smoke_agent.py
            smoke_a2a.py
      tests/
        unit/
          config/
          agent/
          models/
          mcp/
          skills/
          a2a/
        integration/
          test_agent_smoke.py
          test_a2a_smoke.py
          test_langfuse_metadata.py
        fixtures/
          mcp/
          skills/

  config/
    config.example.yaml

  skills/
    README.md
    examples/
      ops-basic/
        SKILL.md

  scripts/
    dev.mjs
    dev-langgraph.sh

  docs/
    design/
      project-structure.md
    requirements/
      deepagent-sap-aicore-requirements.md
    research/
      deepagents-chat-frontends.md
      deepagents-sap-ai-sdk-integration.md
```

## 3. Root-Level Responsibilities

- [ ] Root `package.json` owns local orchestration only, not application code.
- [ ] Root `pnpm-workspace.yaml` includes `apps/*` and may later include shared frontend packages.
- [ ] Root `.env.example` documents backend secrets only: required sensitive runtime values without usable values. Non-secret frontend/runtime config lives next to each process (`apps/web/.env.example`, `apps/copilot-runtime/.env.example`).
- [ ] Root `config/` contains example deployment-level configuration files that can be referenced from `.env`.
- [ ] Root `skills/` contains local development skills and examples, not Python implementation code.
- [ ] Root `docs/` remains the source of requirements, research, design decisions, and operating notes.
- [ ] Root `scripts/` contains small developer wrappers only when a command would otherwise be hard to remember.

Root should stay thin. If a file contains product behavior, it belongs in `apps/web` or `services/agent`.

## 4. Frontend Structure

### 4.1 App Placement

- [ ] Put the Vite React app in `apps/web`.
- [ ] Use `index.html`, `src/main.tsx`, and `src/App.tsx` as the client-only app entrypoint.
- [ ] Keep static assets in `apps/web/public`.
- [ ] Keep reusable UI primitives in `apps/web/src/components/ui`.
- [ ] Keep domain feature code in `apps/web/src/features/*` rather than mixing everything under `components`.

This keeps the first frontend as a client-only SPA, avoiding SSR/hydration complexity while preserving a conventional `src` folder for application source.

### 4.2 Frontend Feature Modules

`features/chat` owns the first-version chat experience:

- [ ] `components/chat-panel.tsx` composes the chat experience.
- [ ] `components/message-list.tsx` renders streamed and historical messages.
- [ ] `components/message-composer.tsx` owns prompt input and submit behavior.
- [ ] `components/stream-status.tsx` renders loading, reconnect, and error states.
- [ ] `hooks/use-deepagent-chat.ts` wraps official `@langchain/react useStream` and is the only frontend module that should know the exact stream hook setup.
- [ ] `model/thread-title.ts` implements first-user-message title truncation.

`features/threads` owns local thread list/cache behavior:

- [ ] Frontend cache may store recent thread ids, titles, and timestamps.
- [ ] Frontend cache must not be the source of truth for message history.
- [ ] Backend/LangGraph thread state remains authoritative.

`features/ops-dashboard` is a placeholder for future panels:

- [ ] It may define layout shells and placeholder extension points.
- [ ] It must not force first-version dashboard behavior into the chat implementation.
- [ ] Future panels should read from official stream projections such as messages, subagents, values, tool calls, and interrupts.

### 4.3 Frontend Infrastructure Modules

- [ ] `lib/env.ts` validates browser-visible environment variables.
- [ ] `lib/langgraph.ts` contains tiny wrappers/types around `@langchain/react`, but must not reimplement the protocol.
- [ ] `lib/routes.ts` centralizes frontend route constants.
- [ ] `vite.config.ts` defines local dev proxy rules so `/chat/*` and `/a2a/*` appear under one local frontend origin.

## 5. Backend Structure

### 5.1 Package Placement

- [ ] Put the Python backend in `services/agent`.
- [ ] Use a `src/ops_pilot` package layout.
- [ ] Keep `pyproject.toml`, `uv.lock`, and `langgraph.json` next to the service.
- [ ] Keep backend tests under `services/agent/tests`.

This keeps Python packaging and imports explicit while allowing the repository root to stay a frontend/backend monorepo shell.

### 5.2 Backend Module Interfaces

`config` is the only module that reads environment variables and raw config files:

- [ ] `settings.py` exposes a typed `Settings` object.
- [ ] `mcp_schema.py` validates MCP server config, including `required` flags.
- [ ] `subagents_schema.py` reserves future custom subagent config shape.
- [ ] Callers receive typed config objects, not raw `os.environ` values.

`models` hides SAP SDK specifics:

- [ ] `sap_genai.py` exposes a small `create_chat_model(settings)` interface.
- [ ] It tries `init_llm(model_name=...)` first.
- [ ] It owns fallback to explicit SAP wrappers if needed.
- [ ] `smoke.py` owns direct invocation and `bind_tools()` smoke checks.

`mcp` hides MCP loading and status:

- [ ] `loader.py` loads tools through `MultiServerMCPClient`.
- [ ] `registry.py` returns the tool list and server metadata needed by the agent factory.
- [ ] `status.py` reports required/optional load results for health checks.
- [ ] Callers should not construct MCP clients directly.

`skills` hides local skill path validation:

- [ ] `resolver.py` converts configured path strings into normalized paths.
- [ ] `validator.py` fails fast for missing or invalid configured paths.
- [ ] It does not load remote registries in the first version.

`observability` hides Langfuse setup and trace metadata:

- [ ] `langfuse.py` exposes `create_callback_handler(settings)`.
- [ ] `langfuse.py` must return a disabled/no-op tracing result when Langfuse keys are missing in local development.
- [ ] `metadata.py` builds protocol metadata for `/chat` and `/a2a` runs.
- [ ] Callers attach callbacks and metadata through a small helper rather than importing Langfuse everywhere.

`agent` is the central capability module:

- [ ] `factory.py` exposes `create_agent_runtime(settings)` or equivalent.
- [ ] `graph.py` exports the graph/assistant object expected by LangGraph dev/server and `langgraph.json`.
- [ ] `runtime.py` wires model, MCP tools, skills, callbacks, and checkpoint/runtime config.
- [ ] `state.py` owns shared state typing only if custom state becomes necessary.
- [ ] `factory.py` is the seam both `/chat` and `/a2a` cross to obtain the DeepAgent capability surface.

`a2a` is an adapter, not a second agent:

- [ ] `app.py` creates the A2A ASGI/server app from official A2A SDK components.
- [ ] `executor.py` maps A2A execution into DeepAgent calls.
- [ ] `mapper.py` converts A2A messages, tasks, artifacts, and stream events to/from LangGraph/DeepAgents concepts.
- [ ] `task_store.py` starts with an in-memory task store behind a small interface.
- [ ] `agent_card.py` owns public agent card metadata.
- [ ] The first local baseline exposes official SDK JSON-RPC routes at `/a2a/jsonrpc` plus agent-card discovery at `/a2a/.well-known/agent-card.json`.
- [ ] A future SQLite/Postgres task store should replace only `task_store.py`, not protocol code.

`health` owns diagnostics:

- [ ] `status.py` composes model, MCP, skills, Langfuse, and A2A task store status.
- [ ] `app.py` can expose health routes if a separate A2A/gateway process needs them.

`tools` owns local smoke-test tools only:

- [ ] Put real product tools behind MCP or a future explicit tool module.
- [ ] Keep smoke tools small and deterministic.

`cli` owns developer commands:

- [ ] `smoke_model.py` validates SAP model invocation and `bind_tools()`.
- [ ] `smoke_agent.py` validates DeepAgent construction and a tool call.
- [ ] `smoke_a2a.py` validates A2A agent-card and JSON-RPC route wiring without requiring SAP credentials.
- [ ] `main.py` exposes command entry points through `pyproject.toml` scripts.

## 6. Runtime Process Model

The directory structure supports either one backend process or multiple local processes. Protocol compatibility wins over process purity.

Recommended first local process model:

- [ ] `apps/web`: Vite dev server on one port.
- [ ] `services/agent`: official LangGraph dev/server process for `/chat/*` compatibility.
- [ ] `services/agent`: A2A server process for `/a2a/*` using official A2A SDK/server components.
- [ ] `apps/web/vite.config.ts` or a small local gateway proxies `/chat/*` and `/a2a/*` to the correct local processes.

Shared behavior comes from shared Python modules, not necessarily a single shared Python object in memory. Both protocol processes must construct the agent through `ops_pilot.agent.factory` so they use the same model, MCP config, skills, and observability behavior.

## 7. Configuration Files

### 7.1 Environment Files

Environment configuration is layered by process, not pooled in a single root file:

- [ ] Root `.env.example` documents **backend secrets only**: optional `AICORE_*` credential overrides, `MODEL_API_KEY`, Langfuse credentials, `OPEN_SANDBOX_API_KEY`, `OTEL_BASIC_AUTH_USER/PASSWORD`, `MCP_BASIC_AUTH_HEADER`, and `OPS_PILOT_CONFIG`. Non-secret backend runtime settings (model name, server host/port, `/chat` base path, assistant id, MCP config, skills paths) live in `config/config.yaml`.
- [ ] `apps/web/.env.example` documents the frontend's browser-visible variables (`VITE_BACKEND_URL`, `VITE_ASSISTANT_ID`, `VITE_COPILOT_RUNTIME_URL`) plus optional Vite dev-server/proxy overrides. Only `VITE_`-prefixed vars are exposed to frontend code.
- [ ] `apps/copilot-runtime/.env.example` documents the Copilot runtime's config (`ASSISTANT_ID`, `AGUI_AGENT_URL`, `COPILOT_RUNTIME_PORT`, `COPILOT_RUNTIME_HOST`).

During `pnpm dev`, the backend host/port, `/chat` base path, and assistant id are derived from `config/config.yaml` (via `ops_pilot settings`) and injected into the web and copilot processes through `process.env`, so `config/config.yaml`'s `server` section is the single source of truth and the per-process `.env` values only serve standalone starts.

### 7.2 MCP Config

MCP servers are declared inline under `mcpServers` in `config/config.yaml`
(copied from `config.example.yaml`). Each server sets a `transport` (`stdio`,
`sse`, or `streamable_http`) and may declare `allow_tools`/`hitl_tools`. Secrets
are environment references only, resolved from `.env` at load time:

```yaml
mcpServers:
  prometheus:
    required: false
    transport: streamable_http
    url: https://prometheus-otel.example.com/mcp
    timeout: 30
    headers:
      Authorization: ${MCP_BASIC_AUTH_HEADER}
    allow_tools: []
    hitl_tools: []
```

The loader normalizes the `mcpServers` shape into the internal format required by `MultiServerMCPClient`.

MCP server package versions should be pinned in committed config. Use explicit version bumps when updating MCP servers; do not rely on `@latest` for reproducible local development.

## 8. Test Layout

Backend tests should verify modules through their public interfaces:

- [ ] `tests/unit/config`: settings and config schema validation.
- [ ] `tests/unit/models`: SAP model factory behavior with fakes/mocks.
- [ ] `tests/unit/mcp`: required/optional MCP load behavior.
- [ ] `tests/unit/skills`: local path resolution and failure modes.
- [ ] `tests/unit/a2a`: message/task mapping and in-memory task store.
- [ ] `tests/integration/test_agent_smoke.py`: agent construction and a deterministic tool call.
- [ ] `tests/integration/test_a2a_smoke.py`: A2A JSON-RPC send/stream/task retrieval against local adapter once SAP-backed runtime smoke tests are enabled.
- [ ] `tests/integration/test_langfuse_metadata.py`: trace metadata shape without requiring a real Langfuse network call when possible.

Frontend tests can be added once the app exists:

- [ ] Component tests for message rendering, stream status, composer behavior, and thread title generation.
- [ ] Hook tests for thread cache behavior.
- [ ] Playwright smoke test for opening the app, sending a message, and seeing streamed output once local backend mocks or dev services are available.

## 9. Import and Dependency Rules

- [ ] Frontend feature modules may import from `components/ui` and `lib`, but shared UI must not import feature modules.
- [ ] `features/chat` may depend on `features/threads`; `features/threads` must not depend on chat UI components.
- [ ] `features/ops-dashboard` may read future stream projections but must not become required for basic chat.
- [ ] Backend modules may depend on `config` types, but `config` must not import agent runtime modules.
- [ ] `agent.factory` may depend on `models`, `mcp`, `skills`, and `observability`.
- [ ] `a2a.executor` may depend on `agent.factory` or an injected agent runtime interface.
- [ ] `models`, `mcp`, `skills`, and `observability` must not import from `a2a` or frontend code.
- [ ] CLI commands should call the same module interfaces as production code, not duplicate setup logic.

## 10. Evolution Rules

- [ ] Add production authentication at the protocol edge, not inside model/MCP/agent construction modules.
- [ ] Add persistent A2A task storage by replacing the `task_store.py` adapter behind its interface.
- [ ] Add custom subagents through config parsing and `agent.factory`, not by editing protocol adapters.
- [ ] Add dashboard panels under `features/ops-dashboard` and consume official stream projections from `useStream`.
- [ ] Add new MCP servers through config only.
- [ ] Add new skills by adding local paths and validating them through the `skills` module.
- [ ] Avoid adding pass-through wrapper modules unless they hide real complexity or provide a stable seam with at least one likely future adapter.

## 11. Why This Structure

- [ ] It keeps the root clean while still supporting one-command local orchestration.
- [ ] It follows Vite React conventions by using `index.html`, `src/main.tsx`, and app-root config files.
- [ ] It follows FastAPI/ASGI large-application practice by separating routers/apps and dependency setup into modules, even though `/chat` may be served by official LangGraph dev/server instead of custom FastAPI routes.
- [ ] It follows `uv` project practice by keeping `pyproject.toml` and `uv.lock` with the Python service.
- [ ] It treats SDK/framework top-level constraints as conservative major-version ranges and reproducibility as a lock-file responsibility.
- [ ] It uses `a2a-sdk[http-server]>=1.1.2,<2` as the first Google A2A Python SDK dependency range, with the exact version recorded in `uv.lock`.
- [ ] It gives every volatile integration a stable seam: SAP model factory, MCP loader, skills resolver, Langfuse metadata, A2A task store, and DeepAgent factory.
- [ ] It keeps future ops dashboard work from contaminating the first-version chat path.

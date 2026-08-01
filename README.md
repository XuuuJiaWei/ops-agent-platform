# ops_pilot

ops_pilot is an agentic operations assistant built on DeepAgents, SAP AI Core / Generative AI Hub, CopilotKit, AG-UI, and Google Agent2Agent. It provides a standard CopilotKit chat experience while keeping agent behavior, tool access, prompts, protocol adapters, and data boundaries under backend control.

## Product Overview

ops_pilot is designed for operations workflows that need a conversational interface backed by controlled enterprise integrations. The frontend stays intentionally thin: users interact through CopilotKit chat, while the backend owns the DeepAgent runtime, SAP model configuration, MCP tool loading, observability, and protocol surfaces.

The product currently exposes three primary surfaces:

- CopilotKit chat UI for human interaction.
- AG-UI/FastAPI backend consumed by the CopilotKit Runtime.
- Google Agent2Agent JSON-RPC endpoint for programmatic agent access.

## Capabilities

- DeepAgents runtime with SAP AI Core / Generative AI Hub model integration.
- MCP tool loading from deployment configuration, including Dynatrace Managed MCP when credentials are configured.
- CopilotKit-compatible chat streaming through AG-UI.
- A2A agent card discovery and JSON-RPC execution through the official Python SDK.
- Optional Langfuse tracing when credentials are configured.
- Local development stack with frontend, Copilot runtime, AG-UI backend, and A2A backend started from one command.

## Architecture

```text
Browser
  -> Vite / CopilotKit chat frontend
  -> local CopilotKit Runtime
  -> AG-UI FastAPI backend
  -> ops_pilot DeepAgent runtime
  -> SAP AI Core / Generative AI Hub + configured MCP tools

A2A client
  -> A2A JSON-RPC backend
  -> ops_pilot DeepAgent runtime
```

The frontend does not implement agent policy or tool orchestration. It renders the standard CopilotKit chat experience and forwards requests to the runtime. Backend code in `services/agent/src/ops_pilot` is the source of truth for agent construction, prompts, SAP model setup, MCP tools, tracing, and protocol adapters.

## Interfaces

| Interface | Default local URL | Purpose |
| --- | --- | --- |
| Web app | `http://localhost:3000` | CopilotKit chat frontend |
| Copilot runtime | `http://127.0.0.1:4001/api/copilotkit` | Runtime bridge between browser and AG-UI |
| AG-UI backend | `http://127.0.0.1:8123` | Chat protocol backend for CopilotKit |
| A2A backend | `http://127.0.0.1:41241` | Agent2Agent server |
| A2A agent card | `http://127.0.0.1:41241/a2a/.well-known/agent-card.json` | Agent discovery metadata |
| A2A JSON-RPC | `http://127.0.0.1:41241/a2a/jsonrpc` | Programmatic agent execution |

## Local Development

Install dependencies:

```bash
pnpm install
cd services/agent && uv sync
```

Create local configuration:

```bash
cp .env.example .env
```

Fill SAP AI Core / Generative AI Hub values as needed. If the SAP SDK is already configured through local SDK configuration or `VCAP_SERVICES`, the `AICORE_*` values can stay empty. Add Dynatrace credentials only when enabling the Dynatrace MCP server.

Start the full development stack:

```bash
pnpm dev
```

`pnpm dev` runs a preflight check, then starts the web app, AG-UI backend, CopilotKit Runtime, and A2A backend. The web process waits for the Copilot runtime and AG-UI health endpoints before Vite starts, so the browser does not call `/api/copilotkit` before the runtime is ready.

| Process | Script | Default command |
| --- | --- | --- |
| Frontend | `pnpm run dev:web` | `pnpm --filter "./apps/web" dev` |
| Chat backend | `pnpm run dev:chat` | `uv run ops_pilot chat serve --host 127.0.0.1 --port 8123` from `services/agent` |
| Copilot runtime | `pnpm run dev:copilot` | `pnpm --filter "./apps/copilot-runtime" dev` |
| A2A backend | `pnpm run dev:a2a` | `uv run ops_pilot a2a serve --host 127.0.0.1 --port 41241` from `services/agent` |

The Vite development server proxies `/api/copilotkit/*` to the Copilot runtime and `/a2a/*` to the A2A backend.

## Configuration

Example configuration lives in `config/`:

- `config/mcp.example.json` defines deployment-level MCP server configuration.
- `config/subagents.example.json` reserves future custom subagent configuration. The current version can keep `subagents` empty and use DeepAgents defaults.

Useful development overrides:

```bash
CHAT_SERVER_CMD="uv run ops_pilot chat serve" pnpm run dev:chat
A2A_SERVER_CMD="uv run ops_pilot a2a serve" pnpm run dev:a2a
WEB_WAIT_TIMEOUT=180 pnpm dev
SMOKE_LOCAL_CMD="pnpm run smoke:a2a" pnpm run smoke:local
```

`pnpm run dev:langgraph` is available for optional LangGraph API / Studio debugging. It is not part of the default product path. The wrapper runs `langgraph-cli[inmem]` on demand through `uv run --with` and starts `langgraph dev` on `http://127.0.0.1:2024`.

## Data And Observability

The default development stack uses a self-hosted CopilotKit Runtime and a local AG-UI/FastAPI backend. CopilotKit anonymous telemetry is disabled in the runtime. Do not enable Copilot Cloud / Enterprise Intelligence Platform features for company data unless that path is explicitly approved.

Langfuse tracing is optional. If `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, or `LANGFUSE_BASE_URL` is missing, the backend starts with tracing disabled.

## Validation

Run smoke checks:

```bash
pnpm run smoke:model
pnpm run smoke:agent
pnpm run smoke:a2a
pnpm run smoke:local
```

Run backend tests:

```bash
cd services/agent
uv run ruff check src tests
uv run pytest
```

Run frontend checks:

```bash
pnpm --filter "./apps/web" typecheck
pnpm --filter "./apps/web" lint
pnpm --filter "./apps/web" build
```

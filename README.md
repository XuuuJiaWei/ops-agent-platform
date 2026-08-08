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
- Local development stack with frontend, Copilot runtime, and one unified backend started from one command.

## Architecture

```text
Browser
  -> Vite / CopilotKit chat frontend
  -> local CopilotKit Runtime
  -> unified FastAPI backend
  -> ops_pilot DeepAgent runtime
  -> SAP AI Core / Generative AI Hub + configured MCP tools

A2A client
  -> unified FastAPI backend
  -> ops_pilot DeepAgent runtime
```

The frontend does not implement agent policy or tool orchestration. It renders the standard CopilotKit chat experience and forwards requests to the runtime. Backend code in `services/agent/src/ops_pilot` is the source of truth for agent construction, prompts, SAP model setup, MCP tools, tracing, and protocol adapters.

## Interfaces

| Interface | Default local URL | Purpose |
| --- | --- | --- |
| Web app | `http://localhost:3000` | CopilotKit chat frontend |
| Copilot runtime | `http://127.0.0.1:4001/api/copilotkit` | Runtime bridge between browser and AG-UI |
| Backend | `http://127.0.0.1:8123` | AG-UI, A2A, health, and MCP tunnel relay |
| A2A agent card | `http://127.0.0.1:8123/a2a/.well-known/agent-card.json` | Agent discovery metadata |
| A2A JSON-RPC | `http://127.0.0.1:8123/a2a/jsonrpc` | Programmatic agent execution |

## Local Development

Install dependencies:

```bash
pnpm install
cd services/agent && uv sync
```

Create local configuration:

```bash
cp .env.example .env
cp config/config.example.yaml config/config.yaml
# Only needed when enabling the Dynatrace Managed MCP server:
cp config/dt-config.example.yaml config/dt-config.yaml
```

Secrets live in `.env`; regular configuration (including MCP servers) lives in `config/config.yaml`. Fill SAP AI Core / Generative AI Hub values in `.env` as needed. If the SAP SDK is already configured through local SDK configuration or `VCAP_SERVICES`, the `AICORE_*` values can stay empty. Add Dynatrace credentials (referenced from `config/config.yaml` via `${VAR}`) only when enabling the Dynatrace MCP server.

Start the full development stack:

```bash
pnpm dev
```

`pnpm dev` runs a preflight check, then starts the web app, unified backend, and CopilotKit Runtime. The web process waits for the Copilot runtime and backend health endpoints before Vite starts, so the browser does not call `/api/copilotkit` before the runtime is ready.

| Process | Script | Default command |
| --- | --- | --- |
| Frontend | `pnpm run dev:web` | `pnpm --filter "./apps/web" dev` |
| Backend | `pnpm run dev:backend` | `uv run ops_pilot serve --host 127.0.0.1 --port 8123` from `services/agent` |
| Copilot runtime | `pnpm run dev:copilot` | `pnpm --filter "./apps/copilot-runtime" dev` |

The Vite development server proxies `/api/copilotkit/*` to the Copilot runtime and `/a2a/*` to the unified backend.

## Configuration

Regular (non-secret) configuration lives in `config/config.yaml` (copy from `config/config.example.yaml`); secrets live in `.env`. `OPS_PILOT_CONFIG` can point the backend at a different config file.

- `config/config.yaml` holds app, model, server, sandbox, and inline MCP server configuration. Each MCP server may declare `allow_tools` (allowlist; empty = allow all) and `hitl_tools` (tools that require human-in-the-loop approval before running).
- The `model:` section selects the chat backend via `provider`: `sap` (default, SAP Generative AI Hub) or an OpenAI-compatible provider such as `deepseek` (set `base_url` and the `MODEL_API_KEY` secret in `.env`). The legacy `sap:` section is still honored as an alias.

Useful development overrides:

```bash
CHAT_PORT=8130 pnpm run dev:backend
WEB_WAIT_TIMEOUT=180 pnpm dev
```

`pnpm run dev:langgraph` is available for optional LangGraph API / Studio debugging. It is not part of the default product path. The wrapper runs `langgraph-cli[inmem]` on demand through `uv run --with` and starts `langgraph dev` on `http://127.0.0.1:2024`.

## Data And Observability

The default development stack uses a self-hosted CopilotKit Runtime and a local AG-UI/FastAPI backend. CopilotKit anonymous telemetry is disabled in the runtime. Do not enable Copilot Cloud / Enterprise Intelligence Platform features for company data unless that path is explicitly approved.

Langfuse tracing is optional. If `LANGFUSE_PUBLIC_KEY` or `LANGFUSE_SECRET_KEY` (in `.env`) or the `langfuse.base_url` (in `config/config.yaml`) is missing, the backend starts with tracing disabled.

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
uv run ruff format --check src tests
uv run pytest
```

Run frontend checks:

```bash
pnpm --filter "./apps/web" typecheck
pnpm --filter "./apps/web" lint
pnpm --filter "./apps/web" build
```

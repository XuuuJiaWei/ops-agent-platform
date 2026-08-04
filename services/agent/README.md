# ops_pilot

Python 3.12 service managed by `uv`.

## Commands

```bash
uv sync
uv run langgraph dev --host 127.0.0.1 --port 2024
uv run ops_pilot serve --host 127.0.0.1 --port 8123
uv run ops_pilot smoke a2a
uv run pytest
```

The service reads root `.env` when present. Leave Langfuse keys empty for local startup with tracing disabled.
The standard backend exposes AG-UI under `/chat`, A2A JSON-RPC at `/a2a/jsonrpc`, agent-card discovery at `/a2a/.well-known/agent-card.json`, and MCP tunnel relay routes under `/dev/mcp-tunnels`.

## DeepAgents Sandbox

Set the OpenSandbox Gardener endpoint values in the root `.env` to run DeepAgents filesystem and command execution in the remote sandbox backend:

```bash
OPEN_SANDBOX_DOMAIN=opensandbox.example.com
OPEN_SANDBOX_API_KEY=...
```

When both values are present, the backend automatically passes an `OpensandboxBackend` to `create_deep_agent(...)`. Configured local skills are uploaded into `/workspace/skills/...` before the graph is created so DeepAgents can discover `SKILL.md` files through the sandbox backend. Set `OPEN_SANDBOX_ENABLED=false` to force the default in-memory state backend.

`OPEN_SANDBOX_TIMEOUT_SECONDS` controls the OpenSandbox lease lifetime. The backend renews an active sandbox before use, and rebuilds the runtime with a fresh sandbox when a user returns after the previous sandbox has expired.

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

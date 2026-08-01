# ops_pilot

Python 3.12 service managed by `uv`.

## Commands

```bash
uv sync
uv run langgraph dev --host 127.0.0.1 --port 2024
uv run ops_pilot a2a serve --host 127.0.0.1 --port 41241
uv run ops_pilot smoke a2a
uv run pytest
```

The service reads root `.env` when present. Leave Langfuse keys empty for local startup with tracing disabled.
The local A2A server currently exposes official SDK JSON-RPC routes at `/a2a/jsonrpc` plus agent-card discovery at `/a2a/.well-known/agent-card.json`.

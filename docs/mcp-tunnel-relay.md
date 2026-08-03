# Protocol-Level MCP Tunnel Relay

This design mirrors the Secure MCP Tunnel pattern: the private stdio MCP server
stays on the developer machine, while the backend exposes a normal Streamable
HTTP MCP endpoint to the agent.

## Runtime Topology

```text
LangChain MCP client in ops_pilot agent
  -> POST/GET /dev/mcp-tunnels/{tunnel_id}/mcp
  -> backend tunnel gateway
  -> managed local bridge WebSocket
  -> local stdio MCP subprocess
```

For local developer mode, the backend runs on the developer machine and can own
the bridge lifecycle. The web control plane configures a local MCP profile; the
backend starts the local bridge, the bridge opens an outbound WebSocket to the
backend relay, and the agent consumes a normal Streamable HTTP MCP endpoint.

For a hosted backend, the same protocol boundary requires a separate local
bridge/daemon in the user's trust boundary. The web UI still configures the
profile; the daemon owns local file access and stdio process execution.

## Protocol Contract

The backend MCP endpoint speaks Streamable HTTP:

- `POST /dev/mcp-tunnels/{tunnel_id}/mcp` forwards JSON-RPC requests and
  notifications to the local client.
- `GET /dev/mcp-tunnels/{tunnel_id}/mcp` opens an SSE stream for server-side MCP
  notifications such as `notifications/tools/list_changed`.
- `DELETE /dev/mcp-tunnels/{tunnel_id}/mcp` closes the local stdio session.

Each Streamable HTTP `mcp-session-id` maps to one local stdio subprocess. This
keeps MCP initialization state and JSON-RPC request ids isolated between agent
sessions.

The local tunnel WebSocket uses a small relay envelope:

```json
{
  "type": "mcp.request",
  "id": "relay_...",
  "sessionId": "mcp_sess_...",
  "newSession": true,
  "message": { "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {} }
}
```

The local client returns:

```json
{
  "type": "mcp.response",
  "id": "relay_...",
  "message": { "jsonrpc": "2.0", "id": 1, "result": {} }
}
```

Server-originated stdio notifications are returned as:

```json
{
  "type": "mcp.notification",
  "sessionId": "mcp_sess_...",
  "message": { "jsonrpc": "2.0", "method": "notifications/tools/list_changed" }
}
```

## Local Developer Flow

Start the unified backend:

```bash
uv run ops_pilot serve
```

Then configure a profile in the web app settings sidebar. The profile can point
at either a stdio command or a standard MCP config file. In local developer mode,
pressing Apply starts the managed local bridge, waits for it to connect, loads
tools through the tunnel, and swaps in the rebuilt agent runtime.

Example profile values for a standard MCP config file:

```bash
Tunnel ID: kibana
MCP config path: /path/to/.mcp.json
MCP server: kibana
```

The web app settings sidebar includes an MCP Tunnel control panel. It polls
`/dev/mcp-tunnels`, `/dev/mcp-tunnels/local-bridges`, and
`/dev/mcp-tunnels/agent-config` through the Vite proxy, shows the bridge and
agent status, and keeps secrets in local MCP config files out of browser storage.

The control plane calls these backend endpoints:

- `GET /dev/mcp-tunnels/agent-config` returns the current dynamic MCP load status.
- `GET /dev/mcp-tunnels/local-bridges` returns managed local bridge status.
- `PUT /dev/mcp-tunnels/{tunnel_id}/agent-config` loads tools and swaps in the rebuilt runtime.
- `DELETE /dev/mcp-tunnels/{tunnel_id}/agent-config` removes the tunnel and rebuilds the runtime.

For external MCP clients, the equivalent Streamable HTTP config is:

```json
{
  "mcpServers": {
    "local-dev": {
      "transport": "streamable_http",
      "url": "http://127.0.0.1:8123/dev/mcp-tunnels/local-dev/mcp"
    }
  }
}
```

Set `OPS_PILOT_TUNNEL_TOKEN` on the backend and pass `--token` to the local
client when a shared developer environment needs a simple bearer check.
Use `VITE_BACKEND_URL` when the backend is not running at `http://127.0.0.1:8123`.

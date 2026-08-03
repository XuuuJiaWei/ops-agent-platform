import { createServer } from "node:http";

process.env.COPILOTKIT_TELEMETRY_DISABLED ??= "true";

const [{ CopilotRuntime }, { createCopilotNodeListener }, { LangGraphHttpAgent }] = await Promise.all([
  import("@copilotkit/runtime/v2"),
  import("@copilotkit/runtime/v2/node"),
  import("@copilotkit/runtime/langgraph"),
]);

const basePath = "/api/copilotkit";
const graphId = process.env.ASSISTANT_ID?.trim() || "agent";
const agentUrl = ensureTrailingSlash(process.env.AGUI_AGENT_URL?.trim() || "http://127.0.0.1:8123/chat");
const port = Number(process.env.COPILOT_RUNTIME_PORT ?? "4001");
const host = process.env.COPILOT_RUNTIME_HOST ?? "127.0.0.1";

const runtime = new CopilotRuntime({
  agents: {
    [graphId]: new LangGraphHttpAgent({
      url: agentUrl,
    }),
  },
});

const copilotNodeListener = createCopilotNodeListener({
  runtime,
  basePath,
  mode: "single-route",
  cors: true,
});

const server = createServer((req, res) => {
  const url = new URL(req.url ?? "/", `http://${req.headers.host ?? `${host}:${port}`}`);

  if (url.pathname.startsWith(basePath)) {
    return copilotNodeListener(req, res);
  }

  if (url.pathname === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok", graphId, agentUrl }));
    return;
  }

  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "not_found" }));
});

server.listen(port, host, () => {
  console.log(`Copilot runtime listening on http://${host}:${port}${basePath}`);
  console.log(`Forwarding agent '${graphId}' to AG-UI at ${agentUrl}`);
});

function ensureTrailingSlash(value) {
  return `${value.trim().replace(/\/$/, "")}/`;
}

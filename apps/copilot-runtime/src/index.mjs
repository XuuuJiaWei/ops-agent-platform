import { createServer } from "node:http";

process.env.COPILOTKIT_TELEMETRY_DISABLED ??= "true";

const [{ CopilotRuntime, InMemoryAgentRunner }, { createCopilotNodeListener }, { LangGraphHttpAgent }] = await Promise.all([
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
  runner: new InMemoryAgentRunner(),
});

const copilotNodeListener = createCopilotNodeListener({
  runtime,
  basePath,
  mode: "single-route",
  cors: true,
});

createServer(copilotNodeListener).listen(port, host, () => {
  console.log(`Copilot runtime listening on http://${host}:${port}${basePath}`);
  console.log(`Forwarding agent '${graphId}' to AG-UI at ${agentUrl}`);
});

function ensureTrailingSlash(value) {
  return `${value.trim().replace(/\/$/, "")}/`;
}

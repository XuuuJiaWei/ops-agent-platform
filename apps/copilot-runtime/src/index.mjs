import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { createAgentRunner } from "./agent-runner.mjs";

process.env.COPILOTKIT_TELEMETRY_DISABLED ??= "true";
loadRootEnvironment();

const [{ CopilotRuntime }, { createCopilotNodeListener }, { LangGraphHttpAgent }] = await Promise.all([
  import("@copilotkit/runtime/v2"),
  import("@copilotkit/runtime/v2/node"),
  import("@copilotkit/runtime/langgraph"),
]);

const basePath = process.env.COPILOTKIT_BASE_PATH?.trim() || "/api/copilotkit";
const graphId = process.env.COPILOTKIT_AGENT_ID?.trim() || "agent";
const agentUrl = ensureTrailingSlash(process.env.COPILOTKIT_AGUI_AGENT_URL?.trim() || "http://127.0.0.1:8123/chat");
const port = Number(process.env.COPILOT_RUNTIME_PORT ?? "4001");
const host = process.env.COPILOT_RUNTIME_HOST ?? "127.0.0.1";
const persistenceBackend = process.env.COPILOTKIT_EVENT_STORE_BACKEND?.trim() || "memory";
const persistenceSetupOnStart = parseBoolean(process.env.COPILOTKIT_EVENT_STORE_SETUP_ON_START, true);
const { runner, close: closeRunner } = await createAgentRunner({
  backend: persistenceBackend,
  connectionString: process.env.DATABASE_URL?.trim(),
  setupOnStart: persistenceSetupOnStart,
});

const runtime = new CopilotRuntime({
  agents: {
    [graphId]: new LangGraphHttpAgent({
      url: agentUrl,
    }),
  },
  runner,
});

const copilotNodeListener = createCopilotNodeListener({
  runtime,
  basePath,
  mode: "single-route",
  cors: true,
});

const server = createServer(copilotNodeListener);
server.listen(port, host, () => {
  console.log(`Copilot runtime listening on http://${host}:${port}${basePath}`);
  console.log(`Forwarding agent '${graphId}' to AG-UI at ${agentUrl}`);
  console.log(`Copilot event persistence: ${persistenceBackend}`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => void shutdown(signal));
}

function ensureTrailingSlash(value) {
  return `${value.trim().replace(/\/$/, "")}/`;
}

function loadRootEnvironment() {
  try {
    process.loadEnvFile(fileURLToPath(new URL("../../../.env", import.meta.url)));
  } catch (error) {
    if (error?.code !== "ENOENT") {
      throw error;
    }
  }
}

function parseBoolean(value, fallback) {
  if (value === undefined) {
    return fallback;
  }
  return !["0", "false", "no"].includes(value.trim().toLowerCase());
}

let shuttingDown = false;
async function shutdown(signal) {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  server.close();
  try {
    await closeRunner();
  } finally {
    process.exitCode = signal === "SIGINT" ? 130 : 143;
  }
}

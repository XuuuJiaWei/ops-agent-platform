import { InMemoryAgentRunner } from "@copilotkit/runtime/v2";
import { PostgresAgentRunner } from "./postgres-agent-runner.mjs";

export async function createAgentRunner({ backend, connectionString, setupOnStart }) {
  if (backend === "memory") {
    return { runner: new InMemoryAgentRunner(), close: async () => undefined };
  }
  if (backend !== "postgres") {
    throw new Error(`Unsupported Copilot Runtime persistence backend: ${backend}`);
  }
  if (!connectionString) {
    throw new Error("DATABASE_URL is required when Copilot Runtime persistence is postgres");
  }

  const runner = new PostgresAgentRunner({ connectionString, setupOnStart });
  await runner.initialize();
  return { runner, close: () => runner.close() };
}

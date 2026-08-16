import { browserEnv } from "@/lib/env";

/** The web entrypoint's CopilotKit transport and agent declaration. */
export const webCopilotRuntime = {
  agent: browserEnv.assistantId,
  runtimeUrl: browserEnv.copilotRuntimeUrl,
};

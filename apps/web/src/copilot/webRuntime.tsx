import { ChatRenderers } from "@/copilot/ChatRenderers";

/**
 * The web entrypoint's CopilotKit declaration.
 *
 * Browser tools stay in this React application: they are registered by
 * `WebCopilotTools` and never copied into the Python or Node runtime.
 */
export function WebCopilotTools() {
  return <ChatRenderers />;
}

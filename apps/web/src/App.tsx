import { CopilotChat, CopilotKit } from "@copilotkit/react-core/v2";
import { ChatRenderers } from "@/copilot/ChatRenderers";
import { browserEnv } from "@/lib/env";

export function App() {
  return (
    <CopilotKit
      runtimeUrl={browserEnv.copilotRuntimeUrl}
      agent={browserEnv.assistantId}
      showDevConsole={browserEnv.showDevConsole}
    >
      <ChatRenderers />
      <main className="h-dvh min-h-screen bg-white">
        <CopilotChat agentId={browserEnv.assistantId} className="h-full" />
      </main>
    </CopilotKit>
  );
}

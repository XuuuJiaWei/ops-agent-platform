import { CopilotKit } from "@copilotkit/react-core/v2";
import { AppShell } from "@/app/AppShell";
import { ChatRenderers } from "@/copilot/ChatRenderers";
import { browserEnv } from "@/lib/env";

const enableCopilotInspector = import.meta.env.DEV;

export function App() {
  return (
    <CopilotKit
      runtimeUrl={browserEnv.copilotRuntimeUrl}
      agent={browserEnv.assistantId}
      showDevConsole={browserEnv.showDevConsole}
      enableInspector={enableCopilotInspector}
    >
      <ChatRenderers />
      <AppShell env={browserEnv} />
    </CopilotKit>
  );
}

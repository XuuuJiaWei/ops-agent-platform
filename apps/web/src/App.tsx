import { CopilotKit } from "@copilotkit/react-core/v2";
import { AppShell } from "@/app/AppShell";
import { ChatRenderers } from "@/copilot/ChatRenderers";
import { KibanaFrontendTools } from "@/copilot/kibana/KibanaFrontendTools";
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
      <KibanaFrontendTools config={browserEnv.kibana} />
      <ChatRenderers />
      <AppShell env={browserEnv} />
    </CopilotKit>
  );
}

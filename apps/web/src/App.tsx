import { CopilotKit } from "@copilotkit/react-core/v2";
import { AppShell } from "@/app/AppShell";
import { WebCopilotTools } from "@/copilot/webRuntime";
import { webCopilotRuntime } from "@/copilot/webRuntimeDefinition";
import { browserEnv } from "@/lib/env";

const isDev = import.meta.env.DEV;

export function App() {
  return (
    <CopilotKit
      runtimeUrl={webCopilotRuntime.runtimeUrl}
      agent={webCopilotRuntime.agent}
      showDevConsole={isDev}
      enableInspector={isDev}
    >
      <WebCopilotTools />
      <AppShell env={browserEnv} />
    </CopilotKit>
  );
}

import { useDefaultRenderTool, useInterrupt } from "@copilotkit/react-core/v2";
import { ApprovalDialog } from "@/copilot/ApprovalDialog";
import { SpaceToolRenderers } from "@/copilot/SpaceToolRenderers";

export function ChatRenderers() {
  useDefaultRenderTool();
  useInterrupt({
    render: (props) => <ApprovalDialog {...props} />,
  });
  return <SpaceToolRenderers />;
}

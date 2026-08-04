import { useDefaultRenderTool, useInterrupt } from "@copilotkit/react-core/v2";
import { ApprovalDialog } from "@/copilot/ApprovalDialog";

export function ChatRenderers() {
  useDefaultRenderTool();
  useInterrupt({
    render: (props) => <ApprovalDialog {...props} />,
  });
  return null;
}

import { useMemo } from "react";
import type { InterruptRenderProps } from "@copilotkit/react-core/v2";

/**
 * Approval UI for DeepAgents human-in-the-loop tool interrupts.
 *
 * The backend maps MCP `hitl_tools` to DeepAgents `interrupt_on`, which pauses
 * the graph before a dangerous/write tool runs and emits an interrupt whose
 * `event.value` carries `action_requests` (the pending tool calls) and
 * `review_configs` (allowed decisions). We surface each pending call and resume
 * with `{ decisions: [{ type: "approve" | "reject" }] }`.
 */

type PendingAction = {
  name: string;
  args: Record<string, unknown>;
  description?: string;
};

type InterruptValue = {
  action_requests?: Array<{
    name?: string;
    action?: string;
    args?: Record<string, unknown>;
    arguments?: Record<string, unknown>;
    description?: string;
  }>;
};

function extractActions(value: unknown): PendingAction[] {
  const requests = (value as InterruptValue | undefined)?.action_requests;
  if (!Array.isArray(requests)) {
    return [];
  }
  return requests.map((request) => ({
    name: request.name ?? request.action ?? "unknown tool",
    args: request.args ?? request.arguments ?? {},
    description: request.description,
  }));
}

export function ApprovalDialog({ event, resolve, cancel }: InterruptRenderProps) {
  const actions = useMemo(() => extractActions(event?.value), [event]);

  // First-run aid: the exact payload shape can vary by CopilotKit/DeepAgents
  // version. Log it once so the parser can be adapted if needed.
  if (import.meta.env.DEV && actions.length === 0) {
    console.debug("[ApprovalDialog] interrupt event.value:", event?.value);
  }

  const decide = (type: "approve" | "reject") => {
    void resolve({ decisions: actions.map(() => ({ type })) });
  };

  return (
    <div className="approval-dialog">
      <div className="approval-dialog__header">Approval required</div>
      <p className="approval-dialog__hint">
        The agent wants to run {actions.length > 1 ? "these tools" : "this tool"}. Review and approve or reject.
      </p>
      <ul className="approval-dialog__actions">
        {actions.map((action, index) => (
          <li key={`${action.name}-${index}`} className="approval-dialog__action">
            <code className="approval-dialog__tool">{action.name}</code>
            {action.description ? <span className="approval-dialog__desc">{action.description}</span> : null}
            {Object.keys(action.args).length > 0 ? (
              <pre className="approval-dialog__args">{JSON.stringify(action.args, null, 2)}</pre>
            ) : null}
          </li>
        ))}
      </ul>
      <div className="approval-dialog__buttons">
        <button type="button" className="approval-dialog__approve" onClick={() => decide("approve")}>
          Approve
        </button>
        <button type="button" className="approval-dialog__reject" onClick={() => decide("reject")}>
          Reject
        </button>
        <button type="button" className="approval-dialog__cancel" onClick={() => void cancel()}>
          Cancel
        </button>
      </div>
    </div>
  );
}

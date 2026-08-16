import { useMemo } from "react";
import type { InterruptRenderProps } from "@copilotkit/react-core/v2";

/**
 * Approval UI for DeepAgents human-in-the-loop tool interrupts.
 *
 * The entrypoint's DeepAgents `interrupt-on` mapping pauses the graph before a
 * dangerous/write tool runs and emits an interrupt whose
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
  actionRequests?: InterruptValue["action_requests"];
  review_configs?: Array<{
    action_name?: string;
  }>;
  reviewConfigs?: Array<{
    actionName?: string;
  }>;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readField(value: unknown, field: string): unknown {
  return isRecord(value) ? value[field] : undefined;
}

function parseJsonObject(value: unknown): unknown {
  if (typeof value !== "string") {
    return value;
  }
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return value;
  }
}

function fallbackActionsFromInterrupts(interrupts: unknown[], eventValue: unknown): PendingAction[] {
  const interruptActions = interrupts.filter(isRecord).map((interrupt) => ({
    name: String(interrupt.reason ?? interrupt.message ?? interrupt.toolCallId ?? "unknown tool"),
    args: {},
    description: typeof interrupt.message === "string" ? interrupt.message : undefined,
  }));
  if (interruptActions.length > 0) {
    return interruptActions;
  }
  return eventValue ? [{ name: "pending tool approval", args: {} }] : [];
}

function extractActions(eventValue: unknown, interrupts: unknown[]): PendingAction[] {
  const parsedEventValue = parseJsonObject(eventValue);
  const request = isRecord(parsedEventValue) ? (parsedEventValue as InterruptValue) : undefined;
  const requests = request?.action_requests ?? request?.actionRequests;
  if (!Array.isArray(requests)) {
    const configs = request?.review_configs ?? request?.reviewConfigs;
    return Array.isArray(configs)
      ? configs.map((config) => ({
          name: String(readField(config, "action_name") ?? readField(config, "actionName") ?? "unknown tool"),
          args: {},
        }))
      : fallbackActionsFromInterrupts(interrupts, eventValue);
  }
  return requests.map((request) => ({
    name: request.name ?? request.action ?? "unknown tool",
    args: request.args ?? request.arguments ?? {},
    description: request.description,
  }));
}

export function ApprovalDialog({ event, interrupt, interrupts, resolve, cancel }: InterruptRenderProps) {
  const actions = useMemo(() => extractActions(event?.value, interrupts), [event, interrupts]);
  const canDecide = actions.length > 0;

  // First-run aid: the exact payload shape can vary by CopilotKit/DeepAgents
  // version. Log it once so the parser can be adapted if needed.
  if (import.meta.env.DEV && actions.length === 0) {
    console.debug("[ApprovalDialog] unparsed interrupt:", { eventValue: event?.value, interrupt });
  }

  const decide = (type: "approve" | "reject") => {
    if (!canDecide) {
      return;
    }
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
        <button
          type="button"
          className="approval-dialog__approve"
          onClick={() => decide("approve")}
          disabled={!canDecide}
        >
          Approve
        </button>
        <button
          type="button"
          className="approval-dialog__reject"
          onClick={() => decide("reject")}
          disabled={!canDecide}
        >
          Reject
        </button>
        <button type="button" className="approval-dialog__cancel" onClick={() => void cancel()}>
          Cancel
        </button>
      </div>
    </div>
  );
}

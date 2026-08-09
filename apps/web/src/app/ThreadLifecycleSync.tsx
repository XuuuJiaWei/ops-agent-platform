import { useAgent, UseAgentUpdate } from "@copilotkit/react-core/v2";
import { useEffect, useRef } from "react";

type AgentMessage = ReturnType<typeof useAgent>["agent"]["messages"][number];

type ThreadLifecycleSyncProps = {
  agentId: string;
  onThreadActivity: (threadId: string, titleCandidate?: string) => void;
  threadId: string;
};

/**
 * Promotes a freshly minted id to a restorable thread after its first message.
 * Message history itself is replayed by Copilot Runtime's server-side runner.
 */
export function ThreadLifecycleSync({ agentId, onThreadActivity, threadId }: ThreadLifecycleSyncProps) {
  const { agent } = useAgent({
    agentId,
    updates: [UseAgentUpdate.OnMessagesChanged],
  });
  const reportedThreadRef = useRef<string | null>(null);

  useEffect(() => {
    // During a thread switch the shared agent can briefly still expose the
    // previous thread's messages. Wait until CopilotKit has applied the new id
    // before promoting it, otherwise an empty thread inherits old metadata.
    if (agent.threadId !== threadId || agent.messages.length === 0 || reportedThreadRef.current === threadId) {
      return;
    }

    reportedThreadRef.current = threadId;
    onThreadActivity(threadId, firstUserMessageTitle(agent.messages));
  }, [agent.messages, agent.threadId, onThreadActivity, threadId]);

  return null;
}

function firstUserMessageTitle(messages: AgentMessage[]): string | undefined {
  for (const message of messages) {
    if (message.role !== "user") {
      continue;
    }

    const title = messageContentTitle((message as Record<string, unknown>).content);
    if (title) {
      return title;
    }
  }

  return undefined;
}

function messageContentTitle(content: unknown): string | undefined {
  if (typeof content === "string") {
    return normalizeTitle(content);
  }

  if (!Array.isArray(content)) {
    return undefined;
  }

  const text = content
    .map((part) => {
      if (!part || typeof part !== "object") {
        return "";
      }
      const candidate = part as Record<string, unknown>;
      return candidate.type === "text" && typeof candidate.text === "string" ? candidate.text : "";
    })
    .join(" ");

  return normalizeTitle(text);
}

function normalizeTitle(value: string): string | undefined {
  const title = value.replace(/\s+/g, " ").trim();
  if (!title) {
    return undefined;
  }
  if (title.length <= 80) {
    return title;
  }
  return `${title.slice(0, 77).trimEnd()}...`;
}

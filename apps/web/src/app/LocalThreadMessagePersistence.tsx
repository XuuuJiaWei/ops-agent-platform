import { useAgent, UseAgentUpdate } from "@copilotkit/react-core/v2";
import { useEffect, useRef } from "react";
import type { MutableRefObject } from "react";

type AgentMessage = ReturnType<typeof useAgent>["agent"]["messages"][number];

type LocalThreadMessagePersistenceProps = {
  agentId: string;
  enabled: boolean;
  onTitleCandidate?: (threadId: string, title: string) => void;
  threadId: string;
};

const STORAGE_VERSION = 1;

type StoredMessagesPayload = {
  version: typeof STORAGE_VERSION;
  messages: AgentMessage[];
};

export function LocalThreadMessagePersistence({ agentId, enabled, onTitleCandidate, threadId }: LocalThreadMessagePersistenceProps) {
  const { agent } = useAgent({
    agentId,
    updates: [UseAgentUpdate.OnMessagesChanged, UseAgentUpdate.OnRunStatusChanged],
  });
  const restoredThreadRef = useRef<string | null>(null);
  const pendingRestoreRef = useRef<{ messages: AgentMessage[]; threadId: string } | null>(null);
  const isRestoringRef = useRef(false);
  const isRunningRef = useRef(agent.isRunning);

  useEffect(() => {
    isRunningRef.current = agent.isRunning;
  }, [agent.isRunning]);

  useEffect(() => {
    if (!enabled) {
      restoredThreadRef.current = null;
      pendingRestoreRef.current = null;
      isRestoringRef.current = false;
      return;
    }

    const messages = readLocalMessages(agentId, threadId);
    pendingRestoreRef.current = { messages, threadId };

    if (isRunningRef.current) {
      return;
    }

    restorePendingMessages(agent, pendingRestoreRef, restoredThreadRef, isRestoringRef, isRunningRef);
  }, [agent, agentId, enabled, threadId]);

  useEffect(() => {
    if (!enabled || agent.isRunning || !pendingRestoreRef.current) {
      return;
    }

    restorePendingMessages(agent, pendingRestoreRef, restoredThreadRef, isRestoringRef, isRunningRef);
  }, [agent, agent.isRunning, enabled]);

  useEffect(() => {
    if (isRestoringRef.current || !enabled || agent.isRunning || restoredThreadRef.current !== threadId) {
      return;
    }

    writeLocalMessages(agentId, threadId, agent.messages);
    const title = firstUserMessageTitle(agent.messages);
    if (title) {
      onTitleCandidate?.(threadId, title);
    }
  }, [agent.isRunning, agent.messages, agentId, enabled, onTitleCandidate, threadId]);

  return null;
}

function restorePendingMessages(
  agent: ReturnType<typeof useAgent>["agent"],
  pendingRestoreRef: MutableRefObject<{ messages: AgentMessage[]; threadId: string } | null>,
  restoredThreadRef: MutableRefObject<string | null>,
  isRestoringRef: MutableRefObject<boolean>,
  isRunningRef: MutableRefObject<boolean>,
) {
  const pendingRestore = pendingRestoreRef.current;
  if (!pendingRestore) {
    return;
  }

  pendingRestoreRef.current = null;
  restoredThreadRef.current = pendingRestore.threadId;
  isRestoringRef.current = true;

  queueMicrotask(() => {
    if (restoredThreadRef.current !== pendingRestore.threadId || isRunningRef.current) {
      isRestoringRef.current = false;
      return;
    }
    agent.setMessages(pendingRestore.messages);
    isRestoringRef.current = false;
  });
}

function storageKey(agentId: string, threadId: string): string {
  return `ops-agent-platform:thread-messages:${agentId}:${threadId}`;
}

function readLocalMessages(agentId: string, threadId: string): AgentMessage[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(storageKey(agentId, threadId));
    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw) as Partial<StoredMessagesPayload>;
    if (parsed.version !== STORAGE_VERSION || !Array.isArray(parsed.messages)) {
      return [];
    }

    return parsed.messages.filter(isAgentMessage);
  } catch {
    return [];
  }
}

function writeLocalMessages(agentId: string, threadId: string, messages: AgentMessage[]) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(
      storageKey(agentId, threadId),
      JSON.stringify({ version: STORAGE_VERSION, messages } satisfies StoredMessagesPayload),
    );
  } catch {
    // Local persistence is best effort only.
  }
}

function isAgentMessage(value: unknown): value is AgentMessage {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return typeof candidate.id === "string" && typeof candidate.role === "string";
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

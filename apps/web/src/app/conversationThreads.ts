import type { Thread as CopilotThread } from "@copilotkit/react-core/v2";
import { useCallback, useEffect, useMemo, useState } from "react";

export type ConversationThread = CopilotThread;

export type ConversationThreadsState = {
  archiveThread: (threadId: string) => Promise<void>;
  deleteThread: (threadId: string) => Promise<void>;
  error: Error | null;
  fetchMoreThreads: () => void;
  hasMoreThreads: boolean;
  isFetchingMoreThreads: boolean;
  isLoading: boolean;
  isMutating: boolean;
  refetchThreads: () => void;
  setThreadTitle: (threadId: string, title: string) => void;
  source: "copilot" | "local";
  startNewThread: () => ConversationThread;
  threads: ConversationThread[];
  touchThread: (threadId: string) => void;
};

type UseConversationThreadsInput = {
  agentId: string;
};

const STORAGE_VERSION = 1;

type StoredThreadPayload = {
  version: typeof STORAGE_VERSION;
  threads: ConversationThread[];
};

export function createConversationThreadId(): string {
  return crypto.randomUUID();
}

export function useConversationThreads({ agentId }: UseConversationThreadsInput): ConversationThreadsState {
  const storageKey = useMemo(() => `ops-agent-platform:threads:${agentId}`, [agentId]);
  const [localThreads, setLocalThreads] = useState<ConversationThread[]>(() => readLocalThreads(storageKey));

  useEffect(() => {
    function handleStorage(event: StorageEvent) {
      if (event.key === storageKey) {
        setLocalThreads(readLocalThreads(storageKey));
      }
    }

    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, [storageKey]);

  const updateLocalThreads = useCallback(
    (updater: (current: ConversationThread[]) => ConversationThread[]) => {
      setLocalThreads((current) => {
        const next = sortThreads(updater(current));
        writeLocalThreads(storageKey, next);
        return next;
      });
    },
    [storageKey],
  );

  const startNewThread = useCallback(() => {
    const thread = createLocalThread(agentId);
    updateLocalThreads((current) => [thread, ...current.filter((item) => item.id !== thread.id)]);
    return thread;
  }, [agentId, updateLocalThreads]);

  const touchThread = useCallback(
    (threadId: string) => {
      const now = new Date().toISOString();
      updateLocalThreads((current) => {
        const existing = current.find((thread) => thread.id === threadId);
        if (!existing) {
          return [createLocalThread(agentId, threadId, now), ...current];
        }
        return current.map((thread) =>
          thread.id === threadId ? { ...thread, updatedAt: now, lastRunAt: now } : thread,
        );
      });
    },
    [agentId, updateLocalThreads],
  );

  const visibleLocalThreads = useMemo(() => localThreads.filter((thread) => !thread.archived), [localThreads]);

  const archiveThread = useCallback(
    async (threadId: string) => {
      updateLocalThreads((current) =>
        current.map((thread) =>
          thread.id === threadId ? { ...thread, archived: true, updatedAt: new Date().toISOString() } : thread,
        ),
      );
    },
    [updateLocalThreads],
  );

  const deleteThread = useCallback(
    async (threadId: string) => {
      updateLocalThreads((current) => current.filter((thread) => thread.id !== threadId));
    },
    [updateLocalThreads],
  );

  const refetchThreads = useCallback(() => {
    setLocalThreads(readLocalThreads(storageKey));
  }, [storageKey]);

  const setThreadTitle = useCallback(
    (threadId: string, title: string) => {
      const normalizedTitle = normalizeThreadTitle(title);
      if (!normalizedTitle) {
        return;
      }

      const now = new Date().toISOString();
      updateLocalThreads((current) => {
        const existing = current.find((thread) => thread.id === threadId);
        if (!existing) {
          return [{ ...createLocalThread(agentId, threadId, now), name: normalizedTitle }, ...current];
        }

        if (existing.name === normalizedTitle) {
          return current;
        }

        return current.map((thread) =>
          thread.id === threadId ? { ...thread, name: normalizedTitle, updatedAt: now, lastRunAt: now } : thread,
        );
      });
    },
    [agentId, updateLocalThreads],
  );

  return {
    archiveThread,
    deleteThread,
    error: null,
    fetchMoreThreads: () => undefined,
    hasMoreThreads: false,
    isFetchingMoreThreads: false,
    isLoading: false,
    isMutating: false,
    refetchThreads,
    setThreadTitle,
    source: "local",
    startNewThread,
    threads: visibleLocalThreads,
    touchThread,
  };
}

function normalizeThreadTitle(title: string): string {
  const normalized = title.replace(/\s+/g, " ").trim();
  if (normalized.length <= 80) {
    return normalized;
  }
  return `${normalized.slice(0, 77).trimEnd()}...`;
}

function createLocalThread(
  agentId: string,
  threadId = createConversationThreadId(),
  now = new Date().toISOString(),
): ConversationThread {
  return {
    id: threadId,
    agentId,
    name: "New conversation",
    archived: false,
    createdAt: now,
    updatedAt: now,
    lastRunAt: now,
  };
}

function readLocalThreads(storageKey: string): ConversationThread[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw) as Partial<StoredThreadPayload>;
    if (parsed.version !== STORAGE_VERSION || !Array.isArray(parsed.threads)) {
      return [];
    }

    return sortThreads(parsed.threads.filter(isConversationThread));
  } catch {
    return [];
  }
}

function writeLocalThreads(storageKey: string, threads: ConversationThread[]) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(
    storageKey,
    JSON.stringify({ version: STORAGE_VERSION, threads } satisfies StoredThreadPayload),
  );
}

function sortThreads(threads: ConversationThread[]): ConversationThread[] {
  return [...threads].sort((left, right) => timestamp(right) - timestamp(left));
}

function timestamp(thread: ConversationThread): number {
  return new Date(thread.lastRunAt ?? thread.updatedAt).valueOf();
}

function isConversationThread(value: unknown): value is ConversationThread {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.agentId === "string" &&
    (typeof candidate.name === "string" || candidate.name === null) &&
    typeof candidate.archived === "boolean" &&
    typeof candidate.createdAt === "string" &&
    typeof candidate.updatedAt === "string" &&
    (typeof candidate.lastRunAt === "string" || candidate.lastRunAt === undefined)
  );
}

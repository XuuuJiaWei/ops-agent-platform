import { useCallback, useEffect, useMemo, useState } from "react";

export type ConversationThread = {
  id: string;
  agentId: string;
  name: string | null;
  archived: boolean;
  createdAt: string;
  updatedAt: string;
  lastRunAt?: string;
};

export type ConversationThreadsState = {
  archiveThread: (threadId: string) => Promise<void>;
  createThread: () => ConversationThread;
  deleteThread: (threadId: string) => Promise<void>;
  error: Error | null;
  fetchMoreThreads: () => void;
  hasMoreThreads: boolean;
  isFetchingMoreThreads: boolean;
  isLoading: boolean;
  refetchThreads: () => void;
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

export function useConversationThreads({ agentId }: UseConversationThreadsInput): ConversationThreadsState {
  const storageKey = useMemo(() => `ops-agent-platform:threads:${agentId}`, [agentId]);
  const [threads, setThreads] = useState<ConversationThread[]>(() => readLocalThreads(storageKey));

  useEffect(() => {
    function handleStorage(event: StorageEvent) {
      if (event.key === storageKey) {
        setThreads(readLocalThreads(storageKey));
      }
    }

    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, [storageKey]);

  const updateThreads = useCallback(
    (updater: (current: ConversationThread[]) => ConversationThread[]) => {
      setThreads((current) => {
        const next = sortThreads(updater(current));
        writeLocalThreads(storageKey, next);
        return next;
      });
    },
    [storageKey],
  );

  const createThread = useCallback(() => {
    const now = new Date().toISOString();
    const thread: ConversationThread = {
      id: `thread-${crypto.randomUUID()}`,
      agentId,
      name: "New conversation",
      archived: false,
      createdAt: now,
      updatedAt: now,
      lastRunAt: now,
    };

    updateThreads((current) => [thread, ...current.filter((item) => item.id !== thread.id)]);
    return thread;
  }, [agentId, updateThreads]);

  const touchThread = useCallback(
    (threadId: string) => {
      const now = new Date().toISOString();
      updateThreads((current) =>
        current.map((thread) => (thread.id === threadId ? { ...thread, updatedAt: now, lastRunAt: now } : thread)),
      );
    },
    [updateThreads],
  );

  const archiveThread = useCallback(
    async (threadId: string) => {
      updateThreads((current) =>
        current.map((thread) =>
          thread.id === threadId ? { ...thread, archived: true, updatedAt: new Date().toISOString() } : thread,
        ),
      );
    },
    [updateThreads],
  );

  const deleteThread = useCallback(
    async (threadId: string) => {
      updateThreads((current) => current.filter((thread) => thread.id !== threadId));
    },
    [updateThreads],
  );

  const refetchThreads = useCallback(() => setThreads(readLocalThreads(storageKey)), [storageKey]);

  return {
    archiveThread,
    createThread,
    deleteThread,
    error: null,
    fetchMoreThreads: () => undefined,
    hasMoreThreads: false,
    isFetchingMoreThreads: false,
    isLoading: false,
    refetchThreads,
    threads: threads.filter((thread) => !thread.archived),
    touchThread,
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

  window.localStorage.setItem(storageKey, JSON.stringify({ version: STORAGE_VERSION, threads } satisfies StoredThreadPayload));
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

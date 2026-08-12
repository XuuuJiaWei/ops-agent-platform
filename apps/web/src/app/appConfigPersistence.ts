export type PersistedMainView = "chat" | "spaces";
export type PersistedThreadSource = "copilot" | "local";

export type PersistedAppConfig = {
  activeThreadId: string | undefined;
  activeThreadSource: PersistedThreadSource;
  desktopSidebarOpen: boolean;
  hasExplicitThreadId: boolean;
  mainView: PersistedMainView;
};

const STORAGE_VERSION = 3;

type StoredAppConfigPayload = {
  version: number;
  config: Omit<PersistedAppConfig, "mainView"> & { mainView: PersistedMainView | "app" };
};

const defaultAppConfig: PersistedAppConfig = {
  activeThreadId: undefined,
  activeThreadSource: "local",
  desktopSidebarOpen: true,
  hasExplicitThreadId: false,
  mainView: "chat",
};

export function appConfigStorageKey(agentId: string): string {
  return `ops-agent-platform:app-config:${agentId}`;
}

export function readPersistedAppConfig(agentId: string): PersistedAppConfig {
  if (typeof window === "undefined") {
    return defaultAppConfig;
  }

  try {
    const raw = window.localStorage.getItem(appConfigStorageKey(agentId));
    if (!raw) {
      return defaultAppConfig;
    }

    const parsed = JSON.parse(raw) as Partial<StoredAppConfigPayload>;
    if ((parsed.version !== 2 && parsed.version !== STORAGE_VERSION) || !isStoredAppConfig(parsed.config)) {
      return defaultAppConfig;
    }

    return { ...parsed.config, mainView: parsed.config.mainView === "app" ? "spaces" : parsed.config.mainView };
  } catch {
    return defaultAppConfig;
  }
}

export function writePersistedAppConfig(agentId: string, config: PersistedAppConfig) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(
      appConfigStorageKey(agentId),
      JSON.stringify({ version: STORAGE_VERSION, config } satisfies StoredAppConfigPayload),
    );
  } catch {
    // Local persistence is best effort only.
  }
}

export function normalizeInitialAppConfig(
  config: PersistedAppConfig,
  createThreadId: () => string = () => crypto.randomUUID(),
): PersistedAppConfig & { activeThreadId: string } {
  const activeThreadId = config.activeThreadId ?? createThreadId();
  return {
    ...config,
    activeThreadId,
    // The UI owns every thread id, including newly generated ids. Marking one
    // as implicit lets CopilotKit replace it, splitting sidebar metadata from
    // the runtime event log and making the conversation impossible to reopen.
    hasExplicitThreadId: true,
  };
}

function isStoredAppConfig(value: unknown): value is StoredAppConfigPayload["config"] {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    (typeof candidate.activeThreadId === "string" || candidate.activeThreadId === undefined) &&
    (candidate.activeThreadSource === "copilot" || candidate.activeThreadSource === "local") &&
    typeof candidate.desktopSidebarOpen === "boolean" &&
    typeof candidate.hasExplicitThreadId === "boolean" &&
    (candidate.mainView === "chat" || candidate.mainView === "spaces" || candidate.mainView === "app")
  );
}

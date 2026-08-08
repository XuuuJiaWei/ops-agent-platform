export type PersistedMainView = "chat" | "app";
export type PersistedThreadSource = "copilot" | "local";

export type PersistedAppConfig = {
  activeThreadId: string | undefined;
  activeThreadSource: PersistedThreadSource;
  desktopSidebarOpen: boolean;
  hasExplicitThreadId: boolean;
  mainView: PersistedMainView;
};

const STORAGE_VERSION = 2;

type StoredAppConfigPayload = {
  version: typeof STORAGE_VERSION;
  config: PersistedAppConfig;
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
    if (parsed.version !== STORAGE_VERSION || !isPersistedAppConfig(parsed.config)) {
      return defaultAppConfig;
    }

    return parsed.config;
  } catch {
    return defaultAppConfig;
  }
}

export function writePersistedAppConfig(agentId: string, config: PersistedAppConfig) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(appConfigStorageKey(agentId), JSON.stringify({ version: STORAGE_VERSION, config } satisfies StoredAppConfigPayload));
  } catch {
    // Local persistence is best effort only.
  }
}

function isPersistedAppConfig(value: unknown): value is PersistedAppConfig {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    (typeof candidate.activeThreadId === "string" || candidate.activeThreadId === undefined) &&
    (candidate.activeThreadSource === "copilot" || candidate.activeThreadSource === "local") &&
    typeof candidate.desktopSidebarOpen === "boolean" &&
    typeof candidate.hasExplicitThreadId === "boolean" &&
    (candidate.mainView === "chat" || candidate.mainView === "app")
  );
}

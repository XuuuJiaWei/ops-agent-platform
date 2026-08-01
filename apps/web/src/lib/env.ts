export type BrowserEnv = {
  copilotRuntimeUrl: string;
  assistantId: string;
  showDevConsole: boolean;
  conversationStore: {
    mode: "local" | "company";
    apiUrl?: string;
  };
  pilotBridge: {
    installUrl?: string;
  };
  kibana: {
    baseUrl?: string;
    defaultSpace: string;
    openApiSpecUrl: string;
    maxResponseCharacters: number;
  };
};

const DEFAULT_KIBANA_OPENAPI_SPEC_URL =
  "https://raw.githubusercontent.com/TocharianOU/mcp-server-kibana/main/kibana-openapi-source.yaml";

const publicEnv = {
  VITE_ASSISTANT_ID: import.meta.env.VITE_ASSISTANT_ID,
  VITE_COPILOT_RUNTIME_URL: import.meta.env.VITE_COPILOT_RUNTIME_URL,
  VITE_COPILOT_SHOW_DEV_CONSOLE: import.meta.env.VITE_COPILOT_SHOW_DEV_CONSOLE,
  VITE_CONVERSATION_STORE: import.meta.env.VITE_CONVERSATION_STORE,
  VITE_CONVERSATION_STORE_API_URL: import.meta.env.VITE_CONVERSATION_STORE_API_URL,
  VITE_PILOT_BRIDGE_INSTALL_URL: import.meta.env.VITE_PILOT_BRIDGE_INSTALL_URL,
  VITE_KIBANA_BASE_URL: import.meta.env.VITE_KIBANA_BASE_URL,
  VITE_KIBANA_DEFAULT_SPACE: import.meta.env.VITE_KIBANA_DEFAULT_SPACE,
  VITE_KIBANA_OPENAPI_SPEC_URL: import.meta.env.VITE_KIBANA_OPENAPI_SPEC_URL,
  VITE_KIBANA_MAX_RESPONSE_CHARACTERS: import.meta.env.VITE_KIBANA_MAX_RESPONSE_CHARACTERS,
};

function readPublicEnv(name: keyof typeof publicEnv): string | undefined {
  const value = publicEnv[name];
  return value && value.trim().length > 0 ? value.trim() : undefined;
}

function assertPathOrUrl(name: string, value: string): string {
  if (value.startsWith("/") || value.startsWith("http://") || value.startsWith("https://")) {
    return value;
  }

  throw new Error(`${name} must be an absolute URL or an app-relative path.`);
}

function assertUrl(name: string, value: string): string {
  if (value.startsWith("http://") || value.startsWith("https://")) {
    return value.replace(/\/$/, "");
  }

  throw new Error(`${name} must be an absolute URL.`);
}

function assertToken(name: string, value: string): string {
  if (/^[a-zA-Z0-9._:-]+$/.test(value)) {
    return value;
  }

  throw new Error(`${name} contains unsupported characters.`);
}

function readBoolean(name: keyof typeof publicEnv): boolean {
  return readPublicEnv(name)?.toLowerCase() === "true";
}

function readPositiveInteger(name: keyof typeof publicEnv, fallback: number): number {
  const value = readPublicEnv(name);
  if (!value) {
    return fallback;
  }

  const parsed = Number(value);
  if (Number.isInteger(parsed) && parsed > 0) {
    return parsed;
  }

  throw new Error(`${name} must be a positive integer.`);
}

function readConversationStoreMode(): BrowserEnv["conversationStore"]["mode"] {
  const value = readPublicEnv("VITE_CONVERSATION_STORE") ?? "local";
  if (value === "local" || value === "company") {
    return value;
  }

  throw new Error("VITE_CONVERSATION_STORE must be local or company.");
}

export function getBrowserEnv(): BrowserEnv {
  const conversationStoreMode = readConversationStoreMode();
  const conversationStoreApiUrl = readPublicEnv("VITE_CONVERSATION_STORE_API_URL");
  const pilotBridgeInstallUrl = readPublicEnv("VITE_PILOT_BRIDGE_INSTALL_URL");

  return {
    copilotRuntimeUrl: assertPathOrUrl(
      "VITE_COPILOT_RUNTIME_URL",
      readPublicEnv("VITE_COPILOT_RUNTIME_URL") ?? "/api/copilotkit",
    ),
    assistantId: assertToken("VITE_ASSISTANT_ID", readPublicEnv("VITE_ASSISTANT_ID") ?? "agent"),
    showDevConsole: readBoolean("VITE_COPILOT_SHOW_DEV_CONSOLE"),
    conversationStore: {
      mode: conversationStoreMode,
      apiUrl: conversationStoreApiUrl ? assertPathOrUrl("VITE_CONVERSATION_STORE_API_URL", conversationStoreApiUrl) : undefined,
    },
    pilotBridge: {
      installUrl: pilotBridgeInstallUrl ? assertPathOrUrl("VITE_PILOT_BRIDGE_INSTALL_URL", pilotBridgeInstallUrl) : undefined,
    },
    kibana: {
      baseUrl: readPublicEnv("VITE_KIBANA_BASE_URL")
        ? assertUrl("VITE_KIBANA_BASE_URL", readPublicEnv("VITE_KIBANA_BASE_URL") as string)
        : undefined,
      defaultSpace: readPublicEnv("VITE_KIBANA_DEFAULT_SPACE") ?? "default",
      openApiSpecUrl: assertPathOrUrl(
        "VITE_KIBANA_OPENAPI_SPEC_URL",
        readPublicEnv("VITE_KIBANA_OPENAPI_SPEC_URL") ?? DEFAULT_KIBANA_OPENAPI_SPEC_URL,
      ),
      maxResponseCharacters: readPositiveInteger("VITE_KIBANA_MAX_RESPONSE_CHARACTERS", 60000),
    },
  };
}

export const browserEnv = getBrowserEnv();

export type BrowserEnv = {
  copilotRuntimeUrl: string;
  assistantId: string;
  showDevConsole: boolean;
};

const publicEnv = {
  VITE_ASSISTANT_ID: import.meta.env.VITE_ASSISTANT_ID,
  VITE_COPILOT_RUNTIME_URL: import.meta.env.VITE_COPILOT_RUNTIME_URL,
  VITE_COPILOT_SHOW_DEV_CONSOLE: import.meta.env.VITE_COPILOT_SHOW_DEV_CONSOLE,
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

function assertToken(name: string, value: string): string {
  if (/^[a-zA-Z0-9._:-]+$/.test(value)) {
    return value;
  }

  throw new Error(`${name} contains unsupported characters.`);
}

function readBoolean(name: keyof typeof publicEnv): boolean {
  return readPublicEnv(name)?.toLowerCase() === "true";
}

export function getBrowserEnv(): BrowserEnv {
  return {
    copilotRuntimeUrl: assertPathOrUrl(
      "VITE_COPILOT_RUNTIME_URL",
      readPublicEnv("VITE_COPILOT_RUNTIME_URL") ?? "/api/copilotkit",
    ),
    assistantId: assertToken("VITE_ASSISTANT_ID", readPublicEnv("VITE_ASSISTANT_ID") ?? "agent"),
    showDevConsole: readBoolean("VITE_COPILOT_SHOW_DEV_CONSOLE"),
  };
}

export const browserEnv = getBrowserEnv();

export type BrowserEnv = {
  copilotRuntimeUrl: string;
  backendUrl: string;
  assistantId: string;
};

const publicEnv = {
  VITE_ASSISTANT_ID: import.meta.env.VITE_ASSISTANT_ID,
  VITE_BACKEND_URL: import.meta.env.VITE_BACKEND_URL,
  VITE_COPILOT_RUNTIME_URL: import.meta.env.VITE_COPILOT_RUNTIME_URL,
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

export function getBrowserEnv(): BrowserEnv {
  return {
    copilotRuntimeUrl: assertPathOrUrl(
      "VITE_COPILOT_RUNTIME_URL",
      readPublicEnv("VITE_COPILOT_RUNTIME_URL") ?? "/api/copilotkit",
    ),
    backendUrl: assertUrl("VITE_BACKEND_URL", readPublicEnv("VITE_BACKEND_URL") ?? "http://127.0.0.1:8123"),
    assistantId: assertToken("VITE_ASSISTANT_ID", readPublicEnv("VITE_ASSISTANT_ID") ?? "agent"),
  };
}

export const browserEnv = getBrowserEnv();

/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_A2A_API_URL?: string;
  readonly VITE_ASSISTANT_ID?: string;
  readonly VITE_CHAT_API_URL?: string;
  readonly VITE_COPILOT_RUNTIME_URL?: string;
  readonly VITE_COPILOT_SHOW_DEV_CONSOLE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

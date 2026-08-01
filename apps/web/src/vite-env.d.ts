/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_A2A_API_URL?: string;
  readonly VITE_ASSISTANT_ID?: string;
  readonly VITE_CHAT_API_URL?: string;
  readonly VITE_COPILOT_RUNTIME_URL?: string;
  readonly VITE_COPILOT_SHOW_DEV_CONSOLE?: string;
  readonly VITE_CONVERSATION_STORE?: string;
  readonly VITE_CONVERSATION_STORE_API_URL?: string;
  readonly VITE_PILOT_BRIDGE_INSTALL_URL?: string;
  readonly VITE_KIBANA_BASE_URL?: string;
  readonly VITE_KIBANA_DEFAULT_SPACE?: string;
  readonly VITE_KIBANA_OPENAPI_SPEC_URL?: string;
  readonly VITE_KIBANA_MAX_RESPONSE_CHARACTERS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

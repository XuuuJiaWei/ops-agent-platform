export type ToolResponse = {
  content: Array<{
    type: "text";
    text: string;
  }>;
  isError?: boolean;
};

export type KibanaFrontendConfig = {
  baseUrl?: string;
  defaultSpace: string;
  openApiSpecUrl: string;
  maxResponseCharacters: number;
};

export type KibanaApiEndpoint = {
  path: string;
  method: string;
  description?: string;
  summary?: string;
  parameters?: unknown[];
  requestBody?: unknown;
  responses?: unknown;
  deprecated?: boolean;
  tags?: string[];
};

export function toolText(text: string): ToolResponse {
  return { content: [{ type: "text", text }] };
}

export function toolJson(value: unknown): ToolResponse {
  return toolText(JSON.stringify(value, null, 2));
}

export function toolError(message: string): ToolResponse {
  return { content: [{ type: "text", text: `Error: ${message}` }], isError: true };
}

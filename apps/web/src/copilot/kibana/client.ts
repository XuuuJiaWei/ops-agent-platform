import type { KibanaFrontendConfig } from "./types";

type KibanaRequestOptions = {
  method: "GET" | "POST" | "PUT" | "DELETE";
  path: string;
  body?: unknown;
  params?: Record<string, string | number | boolean>;
  space?: string;
  signal?: AbortSignal;
};

export async function executeKibanaRequest(
  config: KibanaFrontendConfig,
  options: KibanaRequestOptions,
): Promise<unknown> {
  if (!config.baseUrl) {
    throw new Error("VITE_KIBANA_BASE_URL is not configured for this frontend.");
  }

  const url = buildKibanaUrl(config, options.path, options.space, options.params);
  const init: RequestInit = {
    method: options.method,
    credentials: "include",
    signal: options.signal,
    headers: buildHeaders(options.method),
  };

  if (options.method !== "GET" && options.body !== undefined) {
    init.body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    throw new Error(
      `Browser could not fetch Kibana at ${url}. This is usually CORS/preflight, SameSite cookie, VPN/DNS, or TLS. ` +
        `Original error: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  const responseText = await response.text();
  const parsed = parseMaybeJson(responseText);

  if (!response.ok) {
    throw new Error(
      `${options.method} request failed: ${response.status} ${response.statusText}${
        responseText ? `\nDetails: ${formatUnknown(parsed)}` : ""
      }`,
    );
  }

  return parsed;
}

function buildHeaders(method: KibanaRequestOptions["method"]): HeadersInit {
  if (method === "GET") {
    return {};
  }

  return {
    "content-type": "application/json",
    "kbn-xsrf": "true",
    "x-elastic-internal-origin": "kibana",
  };
}

function buildKibanaUrl(
  config: KibanaFrontendConfig,
  rawPath: string,
  space?: string,
  params?: Record<string, string | number | boolean>,
): string {
  if (/^https?:\/\//i.test(rawPath)) {
    throw new Error("Kibana API path must be app-relative, not an absolute URL.");
  }
  if (!rawPath.startsWith("/")) {
    throw new Error("Kibana API path must start with '/'.");
  }

  const baseUrl = new URL(config.baseUrl as string);
  const basePath = baseUrl.pathname.replace(/\/$/, "");
  const targetSpace = space || config.defaultSpace;
  const spacePrefix = targetSpace && targetSpace !== "default" && rawPath.startsWith("/api/")
    ? `/s/${encodeURIComponent(targetSpace)}`
    : "";

  const url = new URL(`${basePath}${spacePrefix}${rawPath}`, baseUrl.origin);
  for (const [key, value] of Object.entries(params ?? {})) {
    url.searchParams.set(key, String(value));
  }
  return url.toString();
}

function parseMaybeJson(text: string): unknown {
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function formatUnknown(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

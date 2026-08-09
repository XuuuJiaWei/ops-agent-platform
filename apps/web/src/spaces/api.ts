import type { BrowserEnv } from "@/lib/env";
import { spaceSchema, spaceSummarySchema, type Space, type SpaceSummary } from "@/spaces/types";

function spacesBaseUrl(env: BrowserEnv): string {
  return import.meta.env.DEV ? "" : env.backendUrl;
}

async function getJson(url: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(url, { headers: { Accept: "application/json" }, signal });
  if (!response.ok) {
    throw new Error(response.status === 404 ? "Space not found" : `Space request failed (${response.status})`);
  }
  return response.json() as Promise<unknown>;
}

export async function listSpaces(env: BrowserEnv, signal?: AbortSignal): Promise<SpaceSummary[]> {
  return spaceSummarySchema.array().parse(await getJson(`${spacesBaseUrl(env)}/spaces`, signal));
}

export async function getSpace(env: BrowserEnv, spaceId: string, signal?: AbortSignal): Promise<Space> {
  return spaceSchema.parse(await getJson(`${spacesBaseUrl(env)}/spaces/${encodeURIComponent(spaceId)}`, signal));
}

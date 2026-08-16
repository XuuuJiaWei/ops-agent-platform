import type { BrowserEnv } from "@/lib/env";
import {
  type CardContent,
  type CardDraft,
  type CardSize,
  type CardBinding,
  type Space,
  spaceSchema,
  type SpaceSummary,
  spaceSummarySchema,
} from "@/spaces/types";

function spacesBaseUrl(env: BrowserEnv): string {
  return import.meta.env.DEV ? "" : env.backendUrl;
}

async function requestJson(url: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(url, {
    ...init,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => undefined)) as
      { detail?: string | { message?: string } } | undefined;
    const detail = typeof payload?.detail === "string" ? payload.detail : payload?.detail?.message;
    throw new Error(
      detail ?? (response.status === 404 ? "Space not found" : `Space request failed (${response.status})`),
    );
  }
  return response.json() as Promise<unknown>;
}

export async function listSpaces(env: BrowserEnv, signal?: AbortSignal): Promise<SpaceSummary[]> {
  return spaceSummarySchema.array().parse(await requestJson(`${spacesBaseUrl(env)}/spaces`, { signal }));
}

export async function getSpace(env: BrowserEnv, spaceId: string, signal?: AbortSignal): Promise<Space> {
  return spaceSchema.parse(
    await requestJson(`${spacesBaseUrl(env)}/spaces/${encodeURIComponent(spaceId)}`, { signal }),
  );
}

export async function createSpace(env: BrowserEnv, name: string, description?: string | null): Promise<Space> {
  return mutateSpace(env, "/spaces", "POST", { name, description });
}

export async function addCardToSpace(env: BrowserEnv, spaceId: string, card: CardDraft): Promise<Space> {
  return mutateSpace(env, `/spaces/${segment(spaceId)}/cards`, "POST", card);
}

export async function updateCardInSpace(
  env: BrowserEnv,
  spaceId: string,
  cardId: string,
  update: {
    content: CardContent;
    card_type?: CardDraft["type"] | null;
    subtitle?: string | null;
    binding?: CardBinding | null;
  },
): Promise<Space> {
  return mutateSpace(env, `/spaces/${segment(spaceId)}/cards/${segment(cardId)}`, "PUT", update);
}

export async function renameCard(env: BrowserEnv, spaceId: string, cardId: string, title: string): Promise<Space> {
  return mutateSpace(env, `/spaces/${segment(spaceId)}/cards/${segment(cardId)}/title`, "PUT", { title });
}

export async function resizeCard(env: BrowserEnv, spaceId: string, cardId: string, size: CardSize): Promise<Space> {
  return mutateSpace(env, `/spaces/${segment(spaceId)}/cards/${segment(cardId)}/size`, "PUT", { size });
}

export async function removeCardFromSpace(env: BrowserEnv, spaceId: string, cardId: string): Promise<Space> {
  return mutateSpace(env, `/spaces/${segment(spaceId)}/cards/${segment(cardId)}`, "DELETE");
}

export async function reorderCardsInSpace(env: BrowserEnv, spaceId: string, cardIds: string[]): Promise<Space> {
  return mutateSpace(env, `/spaces/${segment(spaceId)}/cards-order`, "PUT", { card_ids: cardIds });
}

async function mutateSpace(
  env: BrowserEnv,
  path: string,
  method: "POST" | "PUT" | "DELETE",
  body?: unknown,
): Promise<Space> {
  return spaceSchema.parse(
    await requestJson(`${spacesBaseUrl(env)}${path}`, {
      method,
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  );
}

function segment(value: string): string {
  return encodeURIComponent(value);
}

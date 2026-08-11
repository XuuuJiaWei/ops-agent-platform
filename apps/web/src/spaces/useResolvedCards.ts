import { useEffect, useMemo, useRef, useState } from "react";
import { runCardTransform } from "@/lib/cardTransform/runCardTransform";
import type { CardContent, Space, SpaceCard } from "@/spaces/types";

type Resolved = {
  /** The memo key (id + snapshot time + code) that produced this content. */
  key: string;
  /** Last-good content shown for this card. */
  content: CardContent;
  status: "fresh" | "error";
  error?: string;
};

/**
 * Resolve every live card's `content` in the browser by replaying its
 * LLM-authored `binding.transform` over the backend's `raw_snapshot` inside the
 * QuickJS sandbox. Static cards pass through untouched.
 *
 * The transform runs only when its memo key changes — the key includes
 * `last_refreshed_at` (bumped by the resolver at most every ~30s), so the 15s
 * SWR poll does not re-run JS unless the snapshot actually changed. On failure
 * (JS error, timeout, invalid shape) the card keeps its last-good content and
 * flips to `refresh_status="error"`, which the existing FreshnessBadge renders.
 */
export function useResolvedCards(space: Space | undefined): SpaceCard[] {
  const cards = space?.cards;
  const [resolved, setResolved] = useState<Map<string, Resolved>>(() => new Map());
  // Tracks the memo key already dispatched per card so re-renders (each SWR
  // poll returns a fresh array) don't re-run an unchanged transform.
  const startedRef = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    if (!cards) return;
    let cancelled = false;

    for (const card of cards) {
      const code = card.binding?.transform?.code;
      if (!code || card.raw_snapshot == null) continue;

      const key = memoKey(card, code);
      if (startedRef.current.get(card.id) === key) continue;
      startedRef.current.set(card.id, key);

      const seed = card.last_refreshed_at ? Date.parse(card.last_refreshed_at) || 0 : 0;
      void runCardTransform({ code, raw: card.raw_snapshot, seed }).then((result) => {
        if (cancelled) return;
        setResolved((prev) => {
          const next = new Map(prev);
          if (result.ok) {
            next.set(card.id, { key, content: result.content, status: "fresh" });
          } else {
            // Keep last-good content: prior resolved output if any, else the
            // backend snapshot's stored content.
            const lastGood = prev.get(card.id)?.content ?? card.content;
            next.set(card.id, {
              key,
              content: lastGood,
              status: "error",
              error: `${result.code}: ${result.message}`,
            });
          }
          return next;
        });
      });
    }

    return () => {
      cancelled = true;
    };
  }, [cards]);

  return useMemo(() => {
    if (!cards) return [];
    return cards.map((card) => {
      const hasTransform = Boolean(card.binding?.transform?.code);
      const entry = resolved.get(card.id);
      if (!entry || !hasTransform) return card;
      if (entry.status === "error") {
        return {
          ...card,
          content: entry.content,
          refresh_status: "error",
          last_error: entry.error ?? card.last_error,
        };
      }
      return { ...card, content: entry.content };
    });
  }, [cards, resolved]);
}

function memoKey(card: SpaceCard, code: string): string {
  return `${card.id}:${card.last_refreshed_at ?? ""}:${code}`;
}

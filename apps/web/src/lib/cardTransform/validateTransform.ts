import { cardTypeSchema, type CardContent } from "@/spaces/types";
import { z } from "zod";
import { runCardTransform, type TransformFailureCode } from "./runCardTransform";

type CardType = z.infer<typeof cardTypeSchema>;

export type ValidateFailureCode = TransformFailureCode | "empty_content" | "raw_too_large";

export type ValidateResult = { ok: true } | { ok: false; code: ValidateFailureCode; message: string };

type ValidateInput = {
  /** LLM-authored JS defining `function transform(raw)`. */
  code: string;
  /** A representative source snapshot to run the transform against. */
  raw: unknown;
  /** Card type; when given, the produced content's primary field must be non-empty. */
  cardType?: CardType;
};

// Mirror of the backend REQUIRED_CONTENT_FIELD (services/agent/.../spaces/models.py):
// the one content field each card type must populate to render meaningfully.
const REQUIRED_CONTENT_FIELD: Record<CardType, keyof CardContent> = {
  kpi: "metrics",
  table: "columns",
  "line-chart": "series",
  "bar-chart": "series",
  details: "fields",
  "object-list": "items",
  markdown: "markdown",
};

// Mirror of the backend MAX_RAW_SNAPSHOT_BYTES: a validation sample above this
// won't fit the persisted snapshot, so reject it at authoring time too.
const MAX_RAW_BYTES = 256 * 1024;

/**
 * Author-time dry-run for a live card's `binding.transform`. Runs the JS in the
 * same QuickJS sandbox the frontend uses at refresh time, then checks the output
 * actually populates the card type's primary content field. Returns a compact,
 * agent-facing result so the LLM can fix the transform before persisting.
 *
 * `seed` is fixed at 0: validation only cares that the transform runs and yields
 * a valid, non-empty shape — not about deterministic replay values.
 */
export async function validateTransform({ code, raw, cardType }: ValidateInput): Promise<ValidateResult> {
  const oversize = rawByteGuard(raw);
  if (oversize) return oversize;

  const result = await runCardTransform({ code, raw, seed: 0 });
  if (!result.ok) {
    return { ok: false, code: result.code, message: result.message };
  }

  if (cardType) {
    const field = REQUIRED_CONTENT_FIELD[cardType];
    if (!isFieldPopulated(result.content, field)) {
      return {
        ok: false,
        code: "empty_content",
        message: `transform ran but produced no '${field}' for a ${cardType} card; return a non-empty '${field}'.`,
      };
    }
  }

  return { ok: true };
}

function isFieldPopulated(content: CardContent, field: keyof CardContent): boolean {
  const value = content[field];
  if (field === "markdown") return typeof value === "string" && value.trim().length > 0;
  return Array.isArray(value) && value.length > 0;
}

function rawByteGuard(raw: unknown): { ok: false; code: "raw_too_large"; message: string } | null {
  let bytes: number;
  try {
    bytes = new TextEncoder().encode(raw === undefined ? "null" : JSON.stringify(raw)).length;
  } catch {
    return null; // non-serializable raw fails later in runCardTransform; don't block here
  }
  if (bytes > MAX_RAW_BYTES) {
    return {
      ok: false,
      code: "raw_too_large",
      message: `raw sample is ${bytes} bytes, over the ${MAX_RAW_BYTES}-byte limit; validate against a representative smaller sample.`,
    };
  }
  return null;
}

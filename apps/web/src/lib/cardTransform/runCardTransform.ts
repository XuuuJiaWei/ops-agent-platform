import { cardContentSchema, type CardContent } from "@/spaces/types";
import { getQuickJSModule } from "./module";

// Guardrails for a single untrusted transform run. These bound a buggy or
// hostile transform without a host round-trip: the sandbox has no fetch/DOM by
// default, and the clock/RNG are frozen for deterministic replay.
const MEMORY_LIMIT_BYTES = 16 * 1024 * 1024;
const MAX_STACK_SIZE_BYTES = 512 * 1024;
const DEADLINE_MS = 100;

export type TransformFailureCode = "js_error" | "timeout" | "invalid_shape" | "no_transform";

export type TransformResult =
  | { ok: true; content: CardContent }
  | { ok: false; code: TransformFailureCode; message: string };

type RunInput = {
  /** LLM-authored JS defining `function transform(raw)`. */
  code: string;
  /** The card's raw source snapshot; passed to `transform` as its argument. */
  raw: unknown;
  /** Deterministic seed (epoch ms of last refresh) freezing Date/Math.random. */
  seed: number;
};

/**
 * Run an LLM-authored `transform(raw)` in an isolated QuickJS-WASM sandbox and
 * validate its output against the card content schema. Never throws — every
 * failure mode is returned as a typed `{ ok: false }` result so the caller can
 * fall back to last-good content.
 */
export async function runCardTransform({ code, raw, seed }: RunInput): Promise<TransformResult> {
  if (!code.trim()) {
    return { ok: false, code: "no_transform", message: "No transform code." };
  }

  const QuickJS = await getQuickJSModule();
  const runtime = QuickJS.newRuntime();
  runtime.setMemoryLimit(MEMORY_LIMIT_BYTES);
  runtime.setMaxStackSize(MAX_STACK_SIZE_BYTES);
  const deadline = Date.now() + DEADLINE_MS;
  runtime.setInterruptHandler(() => Date.now() > deadline);

  const context = runtime.newContext();
  try {
    const evalResult = context.evalCode(buildScript(code, raw, seed));
    if (evalResult.error) {
      const detail = context.dump(evalResult.error);
      evalResult.error.dispose();
      const timedOut = Date.now() > deadline;
      return {
        ok: false,
        code: timedOut ? "timeout" : "js_error",
        message: formatError(detail),
      };
    }

    const output = context.dump(evalResult.value);
    evalResult.value.dispose();
    if (typeof output !== "string") {
      return { ok: false, code: "invalid_shape", message: "transform(raw) did not return an object." };
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(output);
    } catch {
      return { ok: false, code: "invalid_shape", message: "transform output was not JSON-serializable." };
    }

    const validated = cardContentSchema.safeParse(parsed);
    if (!validated.success) {
      return {
        ok: false,
        code: "invalid_shape",
        message: validated.error.issues[0]?.message ?? "Invalid content shape.",
      };
    }
    return { ok: true, content: validated.data };
  } finally {
    // Manual memory management: dispose the context and runtime to release the
    // WASM heap and any leaked handles from this run.
    context.dispose();
    runtime.dispose();
  }
}

/**
 * Assemble the script evaluated inside the sandbox: a determinism prelude, the
 * user's transform, then an expression that stringifies its result. The raw
 * snapshot is inlined as a JSON literal (valid JS), so no host handles cross
 * the boundary.
 */
function buildScript(code: string, raw: unknown, seed: number): string {
  const rawLiteral = jsonLiteral(raw);
  return `
${determinismPrelude(seed)}
${code}
JSON.stringify(transform(${rawLiteral}));
`;
}

function determinismPrelude(seed: number): string {
  const safeSeed = Number.isFinite(seed) ? Math.floor(seed) : 0;
  // Freeze the clock and swap Math.random for a seeded mulberry32 PRNG so the
  // same (code, raw, seed) always yields identical content.
  return `
var __SEED = ${safeSeed};
Math.random = (function () {
  var s = (__SEED >>> 0) || 1;
  return function () {
    s |= 0; s = (s + 0x6D2B79F5) | 0;
    var t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
})();
(function () {
  var _D = Date;
  function FrozenDate(a, b, c, d, e, f, g) {
    switch (arguments.length) {
      case 0: return new _D(__SEED);
      case 1: return new _D(a);
      default: return new _D(a, b, c, d, e, f, g);
    }
  }
  FrozenDate.now = function () { return __SEED; };
  FrozenDate.parse = _D.parse;
  FrozenDate.UTC = _D.UTC;
  FrozenDate.prototype = _D.prototype;
  globalThis.Date = FrozenDate;
})();
`;
}

// Line-separator (0x2028) and paragraph-separator (0x2029) are valid inside
// JSON strings but are line terminators in JS source; escape them so the
// inlined literal parses on every engine.
const LINE_SEP = String.fromCharCode(0x2028);
const JS_UNSAFE = new RegExp("[\\u2028\\u2029]", "g");

function jsonLiteral(value: unknown): string {
  const json = value === undefined ? "null" : JSON.stringify(value);
  return json.replace(JS_UNSAFE, (c) => (c === LINE_SEP ? "\\u2028" : "\\u2029"));
}

function formatError(detail: unknown): string {
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  return typeof detail === "string" ? detail : "Transform threw an error.";
}

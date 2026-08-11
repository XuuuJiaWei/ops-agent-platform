import { describe, expect, it } from "vitest";
import { runCardTransform } from "./runCardTransform";

const SEED = 1_700_000_000_000;

describe("runCardTransform", () => {
  it("normalizes a raw snapshot into validated card content", async () => {
    const result = await runCardTransform({
      code: "function transform(raw){return {metrics:[{label:'Docs',value:String(raw.count)}]};}",
      raw: { count: 512 },
      seed: SEED,
    });

    expect(result).toEqual({
      ok: true,
      content: expect.objectContaining({
        metrics: [{ label: "Docs", value: "512" }],
      }),
    });
  });

  it("fills schema defaults for omitted content arrays", async () => {
    const result = await runCardTransform({
      code: "function transform(){return {markdown:'# hi'};}",
      raw: {},
      seed: SEED,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.content.markdown).toBe("# hi");
      expect(result.content.metrics).toEqual([]);
      expect(result.content.rows).toEqual([]);
    }
  });

  it("returns no_transform for empty code", async () => {
    const result = await runCardTransform({ code: "   ", raw: {}, seed: SEED });
    expect(result).toEqual({ ok: false, code: "no_transform", message: expect.any(String) });
  });

  it("reports js_error when the transform throws", async () => {
    const result = await runCardTransform({
      code: "function transform(){throw new Error('boom');}",
      raw: {},
      seed: SEED,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.code).toBe("js_error");
      expect(result.message).toContain("boom");
    }
  });

  it("reports invalid_shape when output fails the content schema", async () => {
    const result = await runCardTransform({
      code: "function transform(){return {metrics:'not-an-array'};}",
      raw: {},
      seed: SEED,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.code).toBe("invalid_shape");
  });

  it("reports invalid_shape when the transform returns a non-object", async () => {
    const result = await runCardTransform({
      code: "function transform(){return 42;}",
      raw: {},
      seed: SEED,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.code).toBe("invalid_shape");
  });

  it("times out a runaway loop instead of hanging", async () => {
    const result = await runCardTransform({
      code: "function transform(){while(true){} return {};}",
      raw: {},
      seed: SEED,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.code).toBe("timeout");
  });

  it("has no host escape hatches (fetch/globalThis.process are absent)", async () => {
    const result = await runCardTransform({
      code:
        "function transform(){return {markdown: (typeof fetch)+':'+(typeof globalThis.process)};}",
      raw: {},
      seed: SEED,
    });
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.content.markdown).toBe("undefined:undefined");
  });

  it("freezes Date.now and Math.random for deterministic replay", async () => {
    const code =
      "function transform(){return {markdown: Date.now()+':'+Math.random()};}";
    const a = await runCardTransform({ code, raw: {}, seed: SEED });
    const b = await runCardTransform({ code, raw: {}, seed: SEED });

    expect(a.ok && b.ok).toBe(true);
    if (a.ok && b.ok) {
      expect(a.content.markdown).toBe(b.content.markdown);
      expect(a.content.markdown?.startsWith(`${SEED}:`)).toBe(true);
    }
  });

  it("passes the raw snapshot through unchanged, including tricky strings", async () => {
    const result = await runCardTransform({
      code: "function transform(raw){return {markdown: raw.text};}",
      raw: { text: "line sep end \"quote\"" },
      seed: SEED,
    });
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.content.markdown).toBe("line sep end \"quote\"");
  });
});

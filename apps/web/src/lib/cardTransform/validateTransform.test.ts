import { describe, expect, it } from "vitest";
import { validateTransform } from "./validateTransform";

describe("validateTransform", () => {
  it("passes a transform that produces the card type's required field", async () => {
    const result = await validateTransform({
      code: "function transform(raw){return {metrics:[{label:'Docs',value:String(raw.count)}]};}",
      raw: { count: 512 },
      cardType: "kpi",
    });
    expect(result).toEqual({ ok: true });
  });

  it("passes without a cardType as long as the shape is valid", async () => {
    const result = await validateTransform({
      code: "function transform(){return {markdown:'# hi'};}",
      raw: {},
    });
    expect(result).toEqual({ ok: true });
  });

  it("reports js_error when the transform throws", async () => {
    const result = await validateTransform({
      code: "function transform(){throw new Error('boom');}",
      raw: {},
      cardType: "kpi",
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.code).toBe("js_error");
      expect(result.message).toContain("boom");
    }
  });

  it("reports invalid_shape when the output fails the content schema", async () => {
    const result = await validateTransform({
      code: "function transform(){return {metrics:'not-an-array'};}",
      raw: {},
      cardType: "kpi",
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.code).toBe("invalid_shape");
  });

  it("reports timeout for a runaway loop", async () => {
    const result = await validateTransform({
      code: "function transform(){while(true){} return {};}",
      raw: {},
      cardType: "kpi",
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.code).toBe("timeout");
  });

  it("reports empty_content when the required field is missing for the card type", async () => {
    // Valid shape, but a kpi card needs a non-empty `metrics`, not `markdown`.
    const result = await validateTransform({
      code: "function transform(){return {markdown:'nothing useful'};}",
      raw: {},
      cardType: "kpi",
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.code).toBe("empty_content");
      expect(result.message).toContain("metrics");
    }
  });

  it("reports raw_too_large before running the transform", async () => {
    const bigRaw = { blob: "x".repeat(300 * 1024) };
    const result = await validateTransform({
      code: "function transform(raw){return {markdown: String(raw.blob.length)};}",
      raw: bigRaw,
      cardType: "markdown",
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.code).toBe("raw_too_large");
  });
});

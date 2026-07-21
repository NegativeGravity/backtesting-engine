import { describe, expect, it } from "vitest";
import { downsampleEnvelope, finiteExtent } from "./downsample";

describe("downsampleEnvelope", () => {
  it("preserves endpoints and significant extrema", () => {
    const values = Array.from({ length: 10_000 }, (_, index) => Math.sin(index / 50));
    values[2_500] = -100;
    values[7_500] = 100;

    const sampled = downsampleEnvelope(values, 600);

    expect(sampled.length).toBeLessThanOrEqual(600);
    expect(sampled[0]).toBe(values[0]);
    expect(sampled.at(-1)).toBe(values.at(-1));
    expect(sampled).toContain(-100);
    expect(sampled).toContain(100);
  });

  it("returns short inputs unchanged except non-finite values", () => {
    expect(downsampleEnvelope([1, Number.NaN, 2, Number.POSITIVE_INFINITY, 3], 10)).toEqual([1, 2, 3]);
  });
});

describe("finiteExtent", () => {
  it("computes extents without spreading large arrays", () => {
    const values = Array.from({ length: 100_000 }, (_, index) => index - 50_000);
    expect(finiteExtent(values)).toEqual({ minimum: -50_000, maximum: 49_999 });
  });

  it("returns null when no finite values exist", () => {
    expect(finiteExtent([Number.NaN, Number.POSITIVE_INFINITY])).toBeNull();
  });
});

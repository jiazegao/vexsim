import { describe, expect, it } from "vitest";
import { bounds, ecdf, fit, join, niceStep } from "../src/charts";
import { toScreen } from "../src/view";

describe("series on one axis", () => {
  it("joins series with x values of their own, leaving gaps where a series has no point", () => {
    const joined = join([
      { x: [0, 10, 20], y: [1, 2, 3] },
      { x: [0, 15, 20], y: [4, null, 6] },
    ]);
    expect(joined.x).toEqual([0, 10, 15, 20]);
    expect(joined.ys).toEqual([
      [1, 2, undefined, 3],
      [4, undefined, null, 6], // null: no value there; undefined: no point there
    ]);
  });

  it("makes each series' distribution: the share of its values at or below each x", () => {
    const { x, ys } = ecdf([
      [3, 1, 2, 2],
      [2, null, NaN, 5],
    ]);
    expect(x).toEqual([1, 2, 3, 5]);
    expect(ys[0]).toEqual([0.25, 0.75, 1, 1]);
    expect(ys[1]).toEqual([0, 0.5, 0.5, 1]); // its two numbers only
    expect(ecdf([[]]).ys).toEqual([[]]);
  });
});

describe("x-y paths", () => {
  it("spaces grid lines 1, 2 or 5 times a power of ten apart", () => {
    expect(niceStep(100, 6)).toBe(20);
    expect(niceStep(7, 6)).toBe(1);
    expect(niceStep(0.3, 6)).toBe(0.05);
    expect(niceStep(0)).toBe(1);
  });

  it("fits every point on the canvas at one scale for both axes", () => {
    const box = bounds([
      [
        [0, 0],
        [40, 10],
      ],
      [[NaN, 3]],
    ])!;
    expect(box).toEqual([0, 0, 40, 10]);
    const view = fit(box, 456, 300, 28);
    expect(view.scale).toBe(10); // 40 in across 400 px; the height had room to spare
    expect(toScreen(view, 0, 0)).toEqual([28, 200]);
    expect(toScreen(view, 40, 10)).toEqual([428, 100]);
    expect(bounds([[]])).toBeNull();
    expect(fit([1, 1, 1, 1], 100, 100, 0, 10).scale).toBe(10); // a point: at least 10 in across
  });
});

import { describe, expect, it } from "vitest";
import { MAX_POINTS, MIN_STEP_IN, Trail } from "../src/trail";

describe("trails", () => {
  it("skips points closer than the minimum step", () => {
    const trail = new Trail();
    trail.add(0, 0);
    trail.add(MIN_STEP_IN / 2, 0);
    trail.add(MIN_STEP_IN, 0);
    expect(trail.xs).toEqual([0, MIN_STEP_IN]);
    trail.clear();
    expect(trail.length).toBe(0);
  });

  it("thins itself when full, keeping the whole path and its newest point", () => {
    const trail = new Trail();
    for (let i = 0; i <= MAX_POINTS; i++) trail.add(i, 0);
    expect(trail.length).toBe(MAX_POINTS / 2 + 1);
    expect(trail.xs[0]).toBe(0);
    expect(trail.xs[trail.length - 1]).toBe(MAX_POINTS);
  });
});

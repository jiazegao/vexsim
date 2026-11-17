import { describe, expect, it } from "vitest";
import type { Drawings } from "../src/draw";
import { drawShapes, shapeCount } from "../src/draw";
import type { Palette } from "../src/palette";
import type { View } from "../src/view";

// What the robot code draws, as the page draws it. Phase 15.6: a run of points of one color
// and size travels as one shape, "points", and is filled at once; recordings made before
// that hold each point as a shape of its own, and still play.

const VIEW: View = { scale: 2, cx: 0, cy: 0, width: 400, height: 400 };
const COLORS = { hues: { violet: "#70f", red: "#f00", yellow: "#ff0", ink: "#000", muted: "#888" }, surface: "#fff", text: "#000" } as unknown as Palette;

/** A canvas that writes down what's asked of it. */
function canvas() {
  const calls: string[] = [];
  const context = new Proxy(
    {},
    {
      get: (_, name: string) =>
        name === "measureText" ? () => ({ width: 10 }) : (...values: unknown[]) => void calls.push(`${name}(${values.map((v) => (typeof v === "number" ? +v.toFixed(2) : v)).join(",")})`),
      set: (_, name: string, value) => {
        if (name === "fillStyle") calls.push(`fillStyle=${value}`);
        return true;
      },
    },
  ) as unknown as CanvasRenderingContext2D;
  return { context, calls };
}

describe("what the robot code draws", () => {
  it("fills a run of points at once: an arc each, one fill", () => {
    const { context, calls } = canvas();
    const cloud: Drawings = { particles: [["points", "violet", 4, [0, 0, 10, 0, 0, 10]]] };
    drawShapes(context, VIEW, COLORS, cloud, false);
    expect(calls.filter((c) => c.startsWith("arc("))).toEqual(["arc(200,200,2,0,6.28)", "arc(220,200,2,0,6.28)", "arc(200,180,2,0,6.28)"]);
    expect(calls.filter((c) => c === "fill()")).toHaveLength(1);
    expect(calls).toContain("fillStyle=#70f");
    expect(calls.filter((c) => c.startsWith("moveTo("))).toHaveLength(3); // each its own circle, not joined
  });

  it("draws the same dots as the points one by one (a recording made before)", () => {
    const packed = canvas();
    const single = canvas();
    drawShapes(packed.context, VIEW, COLORS, { p: [["points", "red", 6, [1, 2, 3, 4]]] }, false);
    drawShapes(single.context, VIEW, COLORS, { p: [["point", 1, 2, "red", 6], ["point", 3, 4, "red", 6]] }, false);
    const arcs = (calls: string[]) => calls.filter((c) => c.startsWith("arc("));
    expect(arcs(packed.calls)).toEqual(arcs(single.calls));
    expect(single.calls.filter((c) => c === "fill()")).toHaveLength(2);
  });

  it("leaves points out of the text pass, and odd ends alone", () => {
    const { context, calls } = canvas();
    drawShapes(context, VIEW, COLORS, { p: [["points", "red", 6, [1, 2, 3, 4]]] }, true);
    expect(calls.filter((c) => c.startsWith("arc("))).toEqual([]);
    drawShapes(context, VIEW, COLORS, { p: [["points", "red", 6, [1, 2, 3]]] }, false); // a number short: one point
    expect(calls.filter((c) => c.startsWith("arc("))).toHaveLength(1);
  });

  it("counts each point of a run", () => {
    expect(shapeCount({})).toBe(0);
    expect(
      shapeCount({
        particles: [["points", "violet", 4, [0, 0, 1, 1, 2, 2]]],
        rays: [["line", 0, 0, 1, 1, "yellow"], ["point", 1, 1, "yellow", 5]],
      }),
    ).toBe(5);
  });
});

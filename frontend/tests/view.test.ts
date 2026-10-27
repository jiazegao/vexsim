import { describe, expect, it } from "vitest";
import { fitView, MAX_SCALE, pan, resize, toField, toScreen, zoomAt } from "../src/view";

describe("the field view", () => {
  it("fits the whole field, centered, with a margin", () => {
    const view = fitView(144, 144, 800, 600);
    expect(view.scale).toBeCloseTo((600 - 48) / 144);
    expect(toScreen(view, 0, 0)).toEqual([400, 300]);
    const [, top] = toScreen(view, 0, 72);
    expect(top).toBeCloseTo(24); // +y is up the screen
  });

  it("maps screen points back to the same field points", () => {
    const view = { ...fitView(144, 144, 640, 480), cx: 10, cy: -5 };
    const [px, py] = toScreen(view, 33.5, -12);
    const [x, y] = toField(view, px, py);
    expect(x).toBeCloseTo(33.5);
    expect(y).toBeCloseTo(-12);
  });

  it("zooms about the pointer, keeping the field point under it", () => {
    const view = fitView(144, 144, 800, 600);
    const before = toField(view, 650, 120);
    const zoomed = zoomAt(view, 650, 120, 3);
    expect(zoomed.scale).toBeCloseTo(view.scale * 3);
    const after = toField(zoomed, 650, 120);
    expect(after[0]).toBeCloseTo(before[0]);
    expect(after[1]).toBeCloseTo(before[1]);
    expect(zoomAt(view, 0, 0, 1e6).scale).toBe(MAX_SCALE);
  });

  it("pans with the pointer and keeps its center on resize", () => {
    const view = fitView(144, 144, 800, 600);
    const moved = pan(view, 40, -20); // dragged right and up
    expect(moved.cx).toBeCloseTo(-40 / view.scale); // shows what's to the left
    expect(moved.cy).toBeCloseTo(-20 / view.scale); // and what's below
    const bigger = resize(moved, 1000, 700);
    expect(toField(bigger, 500, 350)).toEqual([moved.cx, moved.cy]);
  });
});

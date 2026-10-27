import { describe, expect, it } from "vitest";
import type { Pose } from "../src/startpose";
import { blockedBy, FINE, formatStart, handlePoint, hitStart, keepInside, moved, SNAP, snap, turned } from "../src/startpose";

const ROBOT = [18, 14] as const; // 18 in long, 14 in wide
const FIELD = [144, 144] as const;

describe("dragging the start", () => {
  it("grabs the rotate handle ahead of the front edge, else the robot", () => {
    const pose: Pose = [10, 20, 90]; // facing +y
    const [hx, hy] = handlePoint(pose, ROBOT, 4);
    expect(hx).toBeCloseTo(10);
    expect(hy).toBeCloseTo(33);
    expect(hitStart(pose, ROBOT, [10.5, 33], 4, 2)).toBe("rotate");
    expect(hitStart(pose, ROBOT, [16, 28], 4, 2)).toBe("move"); // 6 across, 8 along: inside
    expect(hitStart(pose, ROBOT, [18, 20], 4, 2)).toBeNull(); // 8 across: outside 14 wide
  });

  it("keeps the robot inside the walls, turned or not", () => {
    expect(keepInside([80, -90, 0], ROBOT, FIELD)).toEqual([63, -65, 0]);
    expect(keepInside([80, 0, 90], ROBOT, FIELD)).toEqual([65, 0, 90]);
    const corner = keepInside([100, 100, 45], ROBOT, FIELD);
    expect(corner[0]).toBeCloseTo(72 - (9 + 7) * Math.SQRT1_2);
  });

  it("snaps moves to half inches and turns to 15°, finer with Shift", () => {
    const start: Pose = [0, 0, 0];
    expect(moved(start, [12.26, -3.8], ROBOT, FIELD, SNAP)).toEqual([12.5, -4, 0]);
    expect(moved(start, [12.26, -3.8], ROBOT, FIELD, FINE)).toEqual([12.3, -3.8, 0]);
    expect(turned(start, [0, 10], ROBOT, FIELD, SNAP)).toEqual([0, 0, 90]);
    expect(turned(start, [-10, -0.1], ROBOT, FIELD, SNAP)).toEqual([0, 0, 180]); // not -180
    expect(turned(start, [10, 3], ROBOT, FIELD, FINE)[2]).toBe(17);
  });

  it("writes numbers the way the form shows them", () => {
    expect(snap(-0.2, 0.5)).toBe(0);
    expect(Object.is(snap(-0.2, 0.5), -0)).toBe(false);
    expect(formatStart(12.300000001)).toBe("12.3");
    expect(formatStart(-60)).toBe("-60");
  });
});

describe("where the robot can't start", () => {
  const field = {
    size: [144, 144] as const,
    obstacles: [
      { name: "barrier", solid: true, shape: "polygon" as const, points: [[-24, -1.5], [24, -1.5], [24, 1.5], [-24, 1.5]] as [number, number][] },
      { name: "goal", solid: true, shape: "circle" as const, x: -48, y: 48, radius: 5 },
      { name: "low bar", solid: false, shape: "polygon" as const, points: [[40, 40], [50, 40], [50, 50], [40, 50]] as [number, number][] },
    ],
  };

  it("is on solid elements or past the walls", () => {
    expect(blockedBy([0, 0, 0], ROBOT, field)).toEqual(["barrier"]);
    expect(blockedBy([-48, 24, 0], ROBOT, field)).toEqual([]);
    expect(blockedBy([-48, 40, 0], ROBOT, field)).toEqual(["goal"]);
    expect(blockedBy([45, 45, 0], ROBOT, field)).toEqual([]); // robots drive over low elements
    expect(blockedBy([66, 0, 0], ROBOT, field)).toEqual(["the walls"]);
  });

  it("allows touching", () => {
    expect(blockedBy([0, 8.5, 0], ROBOT, field)).toEqual([]); // 7 in half width + 1.5: touching the barrier
    expect(blockedBy([63, 0, 0], ROBOT, field)).toEqual([]); // against the wall
  });
});

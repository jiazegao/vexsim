import { describe, expect, it } from "vitest";
import type { Loop } from "../src/body";
import { bodyContains, entersConvex, extentOf, frontOf, signedDistance, winding } from "../src/body";
import { blockedBy, handlePoint, hitStart, keepInside, moved } from "../src/startpose";

// A robot with a body.shape, as the server sends its outline: from x = -6 to 9 and 14 wide,
// with a notch in its front whose sides run from (7, 0) to (9, +-2.5).
const NOTCHED: Loop = [
  [-6, -7],
  [9, -7],
  [9, -2.5],
  [7, 0],
  [9, 2.5],
  [9, 7],
  [-6, 7],
];
const ROBOT = { footprint: [15, 14] as const, outline: [NOTCHED] };
const FIELD = [144, 144] as const;
const NOTCH_SIDE = Math.hypot(2, 2.5) / 2.5; // a circle of radius r sits 7 + r * this ahead

describe("a robot's shape", () => {
  it("has its front where its +x axis leaves it", () => {
    expect(frontOf(ROBOT)).toBeCloseTo(7); // the notch
    expect(frontOf([18, 14])).toBe(9); // a footprint: its front edge
    expect(frontOf({ footprint: [2, 2], outline: [[[4, 2], [6, 2], [6, 4]]] })).toBe(6); // missed: the furthest
  });

  it("knows what's on it", () => {
    expect(bodyContains(ROBOT, 0, 0)).toBe(true);
    expect(bodyContains(ROBOT, 8, 4)).toBe(true); // a jaw
    expect(bodyContains(ROBOT, 8, 0)).toBe(false); // in the notch
    expect(winding([NOTCHED], 8, 4)).toBe(1);
    expect(signedDistance([NOTCHED], 8, 0)).toBeCloseTo(1 / NOTCH_SIDE); // to either side
    expect(signedDistance([NOTCHED], 0, 0)).toBeCloseTo(-6);
  });

  it("reaches as far as it turns", () => {
    expect(extentOf(ROBOT, 0)).toEqual([-6, 9, -7, 7]);
    const turned = extentOf(ROBOT, 90);
    [-7, 7, -6, 9].forEach((v, i) => expect(turned[i]).toBeCloseTo(v));
  });

  it("finds edges that go into a convex polygon", () => {
    const square: [number, number][] = [
      [0, 0],
      [2, 0],
      [2, 2],
      [0, 2],
    ];
    expect(entersConvex([-1, 1], [3, 1], square, 0.01)).toBe(true); // straight through
    expect(entersConvex([-1, 2], [3, 2], square, 0.01)).toBe(false); // along its edge
    expect(entersConvex([3, 1], [-1, 1], [...square].reverse(), 0.01)).toBe(true); // either way round
  });
});

describe("a robot without a shape", () => {
  it("is its footprint, given as a size or as the robot's scene", () => {
    const scene = { footprint: [18, 14] as const, outline: null };
    const obstacles = [{ name: "goal", solid: true, shape: "circle" as const, x: 15, y: 0, radius: 6.5 }];
    for (const body of [[18, 14] as const, scene, { footprint: [18, 14] as const }]) {
      expect(handlePoint([0, 0, 0], body, 2)).toEqual([11, 0]);
      expect(hitStart([0, 0, 0], body, [8.9, 6.9], 2, 0.5)).toBe("move");
      expect(keepInside([80, 0, 0], body, FIELD)).toEqual([63, 0, 0]);
      expect(blockedBy([0, 0, 0], body, { size: FIELD, obstacles })).toEqual(["goal"]);
      expect(blockedBy([-0.6, 0, 0], body, { size: FIELD, obstacles })).toEqual([]);
    }
  });
});

describe("dragging a shaped robot to its start", () => {
  it("grabs it by its shape and turns it by a handle ahead of its front", () => {
    expect(handlePoint([0, 0, 0], ROBOT, 2)).toEqual([9, 0]);
    expect(hitStart([0, 0, 0], ROBOT, [8, 4], 2, 0.5)).toBe("move");
    expect(hitStart([0, 0, 0], ROBOT, [7.6, 0], 2, 0.5)).toBeNull(); // the notch is empty
    expect(hitStart([0, 0, 0], ROBOT, [9, 0.2], 2, 0.5)).toBe("rotate");
  });

  it("keeps it inside the walls by how far each side reaches", () => {
    expect(keepInside([80, 0, 0], ROBOT, FIELD)).toEqual([63, 0, 0]); // its jaws at the wall
    expect(keepInside([-80, 0, 0], ROBOT, FIELD)).toEqual([-66, 0, 0]); // its back
    expect(moved([0, 0, 90], [0, 100], ROBOT, FIELD, { move: 0.5, turn: 15 })).toEqual([0, 63, 90]);
  });

  it("is blocked by what its shape overlaps", () => {
    const post = (x: number) => ({ size: FIELD, obstacles: [{ name: "post", solid: true, shape: "circle" as const, x, y: 0, radius: 1.5 }] });
    expect(blockedBy([0, 0, 0], ROBOT, post(7 + 1.5 * NOTCH_SIDE + 0.01))).toEqual([]); // sits in the notch
    expect(blockedBy([0, 0, 0], ROBOT, post(7 + 1.5 * NOTCH_SIDE - 0.05))).toEqual(["post"]);
    const bar = { size: FIELD, obstacles: [{ name: "bar", solid: true, shape: "polygon" as const, points: [[-30, -0.5], [30, -0.5], [30, 0.5], [-30, 0.5]] as [number, number][] }] };
    expect(blockedBy([0, 0, 0], ROBOT, bar)).toEqual(["bar"]); // right through it, no corner inside
    expect(blockedBy([0, 7.5, 0], ROBOT, bar)).toEqual([]); // touching its side
    const inside = { size: FIELD, obstacles: [{ name: "peg", solid: true, shape: "polygon" as const, points: [[-1, -1], [1, -1], [1, 1], [-1, 1]] as [number, number][] }] };
    expect(blockedBy([0, 0, 0], ROBOT, inside)).toEqual(["peg"]); // all inside the shape
    expect(blockedBy([63, 0, 0], ROBOT, { size: FIELD, obstacles: [] })).toEqual([]);
    expect(blockedBy([63.1, 0, 0], ROBOT, { size: FIELD, obstacles: [] })).toEqual(["the walls"]);
  });
});

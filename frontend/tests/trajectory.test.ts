// vexsim's own motions' plans (src/trajectory.ts) against the Python they're ported from
// (vexsim/algorithms/control/trajectory.py), which the C++ is tested against too: the
// expected numbers are the Python's.
import { describe, expect, it } from "vitest";
import type { Limits } from "../src/trajectory";
import { planArc, planPath } from "../src/trajectory";

const LIMITS: Limits = { maxVelocity: 64.1, maxAccel: 221.3, maxLateralAccel: 12.9, trackWidth: 10 };
const FIELDS = ["t", "s", "x", "y", "heading", "v", "omega", "a", "alpha"] as const;

interface Case {
  kind: "arc" | "path";
  x: number;
  y: number;
  heading: number;
  radius?: number;
  turn?: number;
  points?: [number, number][];
  end?: number | null;
  forwards: boolean;
  speed: number;
  count: number;
  states: number[][]; // index, then the fields
}

const PYTHON: Case[] = [
  {
    "kind": "arc", "x": 0, "y": 0, "heading": 1.5707963267948966, "radius": 18, "turn": -1.5707963267948966, "forwards": true, "speed": 64.1, "count": 194,
    states: [
      [0, 0.0, 0.0, 0.0, 0.0, 1.570796326795, 0.0, 0.0, 221.3, -12.294444444444],
      [64, 0.64, 9.224689779912, 2.312695603419, 8.826034796876, 1.058313561244, 15.23811011904, -0.84656167328, 0.0, 0.0],
      [129, 1.29, 19.129461357288, 9.24357613412, 15.726352079149, 0.508048473612, 15.23811011904, -0.84656167328, 0.0, 0.0],
      [193, 1.924761997763, 28.274333882308, 18.0, 18.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ],
  },
  {
    "kind": "arc", "x": 48, "y": 0, "heading": 2.5, "radius": 12, "turn": 1.5707963267948966, "forwards": false, "speed": 30, "count": 159,
    states: [
      [0, 0.0, 0.0, 48.0, 0.0, 2.5, 0.0, 0.0, -221.3, 18.441666666667],
      [53, 0.53, 6.231897384242, 53.71813731401, -2.296410349475, 3.01932478202, -12.441864811997, 1.036822067666, 0.0, 0.0],
      [106, 1.06, 12.8260857346, 60.153861296717, -1.307114744098, 3.568840477883, -12.441864811997, 1.036822067666, 0.0, 0.0],
      [158, 1.573247913359, 18.849555921539, 64.795389115811, 2.432057657316, 4.070796326795, 0.0, 0.0, 0.0, 0.0],
    ],
  },
  {
    "kind": "path", "x": 0, "y": 0, "heading": 1.5707963267948966, "points": [[24, 24], [48, 0]], "end": null, "forwards": true, "speed": 64.1, "count": 359,
    states: [
      [0, 0.0, 0.0, 0.0, 0.0, 1.570796326795, 0.0, 0.0, 221.3, -18.441666666667],
      [119, 1.19, 20.767952930043, 10.275188143099, 17.363438285229, 0.700217565111, 22.863060757443, -0.56422893357, -0.33145981802, 0.008179972998],
      [239, 2.39, 39.315670692971, 26.945920515784, 23.32073067213, -0.4192776297, 11.159700388489, -1.156340768234, 12.85501249917, -1.332004848829],
      [358, 3.57991426049, 70.939939738394, 48.0, 0.0, -0.785398163397, 0.0, 0.0, 0.0, 0.0],
    ],
  },
  {
    "kind": "path", "x": 50, "y": 0, "heading": 0, "points": [[36, 12], [24, 36]], "end": null, "forwards": false, "speed": 64.1, "count": 194,
    states: [
      [0, 0.0, 0.0, 50.0, 0.0, 0.0, 0.0, 0.0, -221.3, -23.431764705882],
      [64, 0.64, 7.013589585241, 43.622053642218, 2.532185999169, -0.699685830888, -14.026600359204, -0.919931922589, -17.562653169307, -1.151843275067],
      [129, 1.29, 22.503420849669, 34.198984591915, 14.768329175195, -1.03477454033, -24.988003888032, -0.51636748922, -47.523149162792, -0.982047598639],
      [193, 1.929538682088, 46.067251798217, 24.0, 36.0, -1.107148717794, 0.0, 0.0, 0.0, 0.0],
    ],
  },
  {
    "kind": "path", "x": -48, "y": -24, "heading": 0.3, "points": [[0, -24], [24, 0], [24, 24]], "end": 3.141592653589793, "forwards": true, "speed": 40, "count": 514,
    states: [
      [0, 0.0, 0.0, -48.0, -24.0, 0.3, 0.0, 0.0, 221.3, -8.333370423447],
      [171, 1.71, 46.636845370793, -1.672989960523, -24.465116881405, 0.224068816833, 15.928828224517, 0.809959767859, -14.896791702002, -0.757482080836],
      [342, 3.42, 86.755714249341, 25.457529503357, 3.280528480217, 1.19261201174, 25.278914731153, 0.510329929988, 18.171810631183, 0.366851937506],
      [513, 5.122593327911, 110.417757974477, 24.0, 24.0, 3.14159265359, 0.0, 0.0, 0.0, 0.0],
    ],
  },
];

describe("vexsim's own motions plan as the Python does", () => {
  it.each(PYTHON.map((c, i) => [i, c] as const))("case %i", (_, c) => {
    const plan = c.kind === "arc" ? planArc(c.x, c.y, c.heading, c.radius!, c.turn!, c.forwards, c.speed, LIMITS) : planPath(c.x, c.y, c.heading, c.points!, c.forwards, c.end ?? null, c.speed, LIMITS);
    expect(plan.length).toBe(c.count);
    for (const [index, ...values] of c.states) {
      FIELDS.forEach((field, k) => expect(plan[index][field]).toBeCloseTo(values[k], 9));
    }
  });

  it("ends where it's going, at a standstill", () => {
    const arc = planArc(0, 0, Math.PI / 2, 18, -Math.PI / 2, true, 64.1, LIMITS); // 90° clockwise, from facing +y
    const end = arc[arc.length - 1];
    expect([end.x, end.y, end.heading, end.v]).toEqual([expect.closeTo(18, 9), expect.closeTo(18, 9), expect.closeTo(0, 9), 0]);
    const back = planPath(0, 0, 0, [[-24, 0]], false, null, 40, LIMITS); // straight back
    expect(back[back.length - 1].x).toBeCloseTo(-24, 9);
    expect(Math.min(...back.map((s) => s.v))).toBeLessThan(-30); // backwards: negative speeds
    expect(Math.max(...back.map((s) => Math.abs(s.v)))).toBeLessThanOrEqual(40 + 1e-9);
  });
});

import { describe, expect, it } from "vitest";
import { lerpAngle, Playback } from "../src/playback";
import type { FrameState, Tape } from "../src/protocol";

function sample(t: number, x: number, heading: number, phase: string, estimate: boolean): FrameState {
  return {
    t,
    phase,
    pose: [x, 0, heading],
    estimate: estimate ? [x + 1, 0, heading] : null,
    speed_in_s: x,
    battery: [12, 1],
    wheels: [[x, 5, heading, 0.5, 1]],
    distance: {},
    pieces: [[10 + x, 0]],
    contacts: [],
    motors: [],
    controller: { analog: {}, digital: [] },
    imu: {},
    gps: {},
    mechanisms: [],
    period_left: null,
  };
}

const TAPE: Tape = {
  scene: {
    robot: { name: "bot", footprint: [18, 18], wheels: [], sensors: [], mechanisms: [] },
    field: { name: "empty", size: [144, 144], obstacles: [], pieces: [] },
    mode: "autonomous",
    start: [0, 0, 0],
    seed: 0,
    spec: { robot: "bot.yaml" },
    command: "vexsim run bot.yaml",
    run_id: "20261027-120000-abcd",
  },
  samples: [
    sample(0, 0, 170, "initialize", false),
    sample(0.05, 1, -170, "initialize", false),
    sample(0.1, 2, -170, "autonomous", true),
    sample(0.15, 3, -170, "autonomous", true),
  ],
  events: {
    overlay: [
      [0, { path: null, target: null }],
      [0.1, { path: [[0, 0], [10, 0]], target: [10, 0, null] }],
    ],
    lcd: [[0, ["hello"]]],
    controller_screen: [],
    drawings: [
      [0.05, { mcl: [["point", 1, 2, "violet", 3]] }],
      [0.1, { mcl: [["point", 1, 2, "violet", 3]], plan: [["line", 0, 0, 5, 5, "orange"]] }],
    ],
  },
};

describe("playing a recorded run back", () => {
  const playback = new Playback(TAPE);

  it("knows where the tape starts and ends, and the sample at a time", () => {
    expect([playback.start, playback.end]).toEqual([0, 0.15]);
    expect(playback.index(-1)).toBe(0);
    expect(playback.index(0.05)).toBe(1);
    expect(playback.index(0.07)).toBe(1);
    expect(playback.index(9)).toBe(3);
  });

  it("interpolates between samples, turning the short way round", () => {
    const frame = playback.frameAt(0.025)!;
    expect(frame.pose[0]).toBeCloseTo(0.5);
    expect(frame.pose[2]).toBeCloseTo(180); // 170 -> -170 through 180, not through 0
    expect(frame.wheels[0][0]).toBeCloseTo(0.5);
    expect(frame.pieces[0][0]).toBeCloseTo(10.5);
    expect(frame.estimate).toBeNull(); // no estimate yet
    expect(frame.lcd).toEqual(["hello"]);
    expect(frame.t).toBe(0.025);
    expect(playback.frameAt(5)!.t).toBe(0.15); // held at the end
  });

  it("draws the paths up to the moment, and the motion's overlay of the moment", () => {
    expect(playback.trail("truth", 0.07).length).toBe(2);
    expect(playback.trail("estimate", 0.07).length).toBe(0);
    expect(playback.trail("estimate", 0.15).length).toBe(2);
    expect(playback.overlayAt(0.05)).toEqual({ type: "overlay", path: null, target: null });
    expect(playback.overlayAt(0.12)?.target).toEqual([10, 0, null]);
  });

  it("has what the robot code had drawn at each moment", () => {
    expect(playback.drawingsAt(0)).toEqual({});
    expect(Object.keys(playback.drawingsAt(0.07))).toEqual(["mcl"]);
    expect(Object.keys(playback.drawingsAt(0.15))).toEqual(["mcl", "plan"]);
    expect(playback.drawnLayers()).toEqual(["mcl", "plan"]);
    const older = new Playback({ ...TAPE, events: { ...TAPE.events, drawings: undefined } }); // from before drawings
    expect([older.drawingsAt(0.1), older.drawnLayers()]).toEqual([{}, []]);
  });

  it("lists the phases for the timeline", () => {
    expect(playback.phases()).toEqual([
      { name: "initialize", start: 0, end: 0.1 },
      { name: "autonomous", start: 0.1, end: 0.15 },
    ]);
  });

  it("turns angles the short way", () => {
    expect(lerpAngle(350, 10, 0.5)).toBeCloseTo(360);
    expect(lerpAngle(10, 350, 0.5)).toBeCloseTo(0);
    expect(lerpAngle(-90, 90, 0.25)).toBeCloseTo(-135); // 180 apart: either way is short
  });
});

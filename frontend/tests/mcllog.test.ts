import { describe, expect, it } from "vitest";
import { isRobotLog, LogPlayback, logSummary } from "../src/mcllog";
import type { MclLogTape, RobotLogTape } from "../src/protocol";

const TAPE: MclLogTape = {
  name: "mcl_log7.1239e",
  path: "logs/mcl_log7.1239e",
  summary: {
    updates: 3,
    duration_s: 0.06,
    sensors: 1,
    particles: 1,
    start: [0, 0, 170],
    interval_ms: [30, 30, 30],
    no_reading_pct: 33.3,
    spread_in: [2.5, 3],
  },
  times: [0, 0.03, 0.06],
  estimate: [
    [0, 0, 170],
    [3, 0, -170],
    [6, 3, -160],
  ],
  drawings: [
    [0, { rays: [["line", 0, 0, 10, 0, "muted"]], particles: [], spread: [] }],
    [0.03, { rays: [["line", 3, 0, 9, 0, "yellow"]], particles: [["point", 3, 1, "violet", 4]], spread: [] }],
    [0.06, { rays: [], particles: [], spread: [["ellipse", 6, 3, 2, 2, 0, "blue"]] }],
  ],
};

describe("a real robot's MCL log, played back", () => {
  const log = new LogPlayback(TAPE);

  it("has nothing to show before its first update", () => {
    expect([log.start, log.end]).toEqual([0, 0.06]);
    expect(log.index(-0.5)).toBe(-1);
    expect(log.estimateAt(-0.5)).toBeNull();
    expect(log.drawingsAt(-0.5)).toEqual({});
    expect(log.trail(-0.5).length).toBe(0);
  });

  it("draws each update's estimate, path and what it saw", () => {
    expect(log.index(0.03)).toBe(1);
    expect(log.index(0.05)).toBe(1);
    expect(log.drawingsAt(0.05).particles).toEqual([["point", 3, 1, "violet", 4]]);
    const between = log.estimateAt(0.015)!;
    expect(between[0]).toBeCloseTo(1.5);
    expect(between[2]).toBeCloseTo(180); // the short way round
    expect(log.estimateAt(9)).toEqual([6, 3, -160]); // held at the end
    expect(log.trail(0.04).length).toBe(2);
    expect(log.layers()).toEqual(["rays", "particles", "spread"]);
  });

  it("sums itself up in a line", () => {
    expect(logSummary(TAPE)).toBe("3 updates over 0.1 s · every 30 ms (95%: 30) · spread 2.5 in · 33% of readings saw nothing");
  });
});

const ROBOT_TAPE: RobotLogTape = {
  kind: "robot",
  name: "Left 40",
  path: "card/vexsim_0001_left_40.csv",
  summary: {
    rows: 400,
    duration_s: 3.99,
    interval_ms: 10,
    pose: "lemlib",
    poses: ["lemlib", "mcl"],
    start: [60, 0, 0],
    distance_sensors: 5,
    no_reading_pct: 12.4,
    robot: null,
    field: null,
    test: null,
    routine: "Left 40",
  },
  times: [0, 1, 2, 3],
  estimate: [
    [60, 0, 0],
    [50, 0, 0],
    [40, 0, 0],
    [30, 0, 0],
  ],
  drawings: [
    [0, { rays: [] }],
    [1, { rays: [] }],
    [2, { rays: [] }],
    [3, { rays: [] }],
  ],
  paths: [{ name: "mcl", color: "violet", first: 1, xs: [51, 41, 31], ys: [1, 1, 1] }],
};

describe("a robot log of vexsim's logger, played back", () => {
  const log = new LogPlayback(ROBOT_TAPE);

  it("draws its other poses' paths, each from its first reading", () => {
    expect(log.paths(0.5)).toEqual([{ name: "mcl", color: "violet", trail: { xs: [51, 41, 31], ys: [1, 1, 1], length: 0 } }]);
    expect(log.paths(2.5)[0].trail.length).toBe(2);
    expect(log.paths(9)[0].trail.length).toBe(3);
    expect(new LogPlayback(TAPE).paths(0.05)).toEqual([]); // an MCL log has no others
  });

  it("is told from an MCL log, and sums itself up in a line", () => {
    expect([isRobotLog(ROBOT_TAPE), isRobotLog(TAPE)]).toEqual([true, false]);
    expect(isRobotLog({ kind: "none", path: "x.csv", why: "nothing to play" })).toBe(false);
    expect(logSummary(ROBOT_TAPE)).toBe("400 rows over 4.0 s · every 10 ms · its code's lemlib pose · 5 distance sensors · 12% of readings saw nothing");
  });
});

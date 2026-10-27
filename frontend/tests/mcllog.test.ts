import { describe, expect, it } from "vitest";
import { LogPlayback, logSummary } from "../src/mcllog";
import type { MclLogTape } from "../src/protocol";

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

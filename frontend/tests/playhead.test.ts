import { describe, expect, it } from "vitest";
import { Playhead } from "../src/playhead";
import { shortName, when } from "../src/recording";

describe("the playhead", () => {
  it("stays on the tape", () => {
    const playhead = new Playhead();
    playhead.load(1, 5);
    expect(playhead.t).toBe(5); // a tape opens at its end, the whole path drawn
    playhead.seek(-3);
    expect(playhead.t).toBe(1);
    playhead.seek(99);
    expect(playhead.t).toBe(5);
  });

  it("plays at its speed, from the top when at the end, and stops at the end", () => {
    const playhead = new Playhead();
    playhead.load(0, 2);
    playhead.play();
    expect(playhead.t).toBe(0);
    playhead.setSpeed(4);
    playhead.tick(0.25);
    expect(playhead.t).toBeCloseTo(1);
    playhead.tick(1);
    expect([playhead.t, playhead.playing]).toEqual([2, false]);
    playhead.tick(1); // paused: stays
    expect(playhead.t).toBe(2);
  });

  it("tells its listeners when it moves, but not on every frame", () => {
    const playhead = new Playhead();
    playhead.load(0, 10, 0);
    let heard = 0;
    const stop = playhead.subscribe(() => heard++);
    playhead.play(); // heard at once
    for (let i = 0; i < 10; i++) playhead.tick(0.001); // well within one notice's time
    expect(heard).toBe(1);
    playhead.pause();
    expect(heard).toBe(2);
    stop();
    playhead.seek(3);
    expect(heard).toBe(2);
  });
});

describe("recorded runs' names", () => {
  it("are short enough to label a robot", () => {
    expect(shortName("short")).toBe("short");
    expect(shortName("a".repeat(40))).toBe(`${"a".repeat(27)}…`);
  });

  it("say when today's runs were made, and the day of older ones", () => {
    const noon = new Date(2026, 9, 27, 12, 0).getTime();
    const today = when(new Date(2026, 9, 27, 9, 5, 7).getTime() / 1000, noon);
    const before = when(new Date(2026, 9, 20, 9, 5, 7).getTime() / 1000, noon);
    expect(today).toMatch(/0?9:05:07/);
    expect(before).toContain(today);
    expect(before.length).toBeGreaterThan(today.length);
  });
});

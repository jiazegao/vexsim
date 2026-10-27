import { describe, expect, it, vi } from "vitest";
import type { FrameMessage, SceneMessage, SessionInfo } from "../src/protocol";
import { isLive, MAX_LINES, SessionStore } from "../src/session";

const INFO: SessionInfo = {
  id: "s1",
  spec: { robot: "bot.yaml" },
  command: "vexsim run bot.yaml",
  state: "running",
  message: null,
  mode: "autonomous",
  created: 0,
  run_id: null,
};

const SCENE: SceneMessage = {
  type: "scene",
  robot: { name: "bot", footprint: [18, 18], wheels: [], sensors: [], mechanisms: [] },
  field: { name: "empty", size: [144, 144], obstacles: [], pieces: [] },
  mode: "autonomous",
  start: [0, 0, 0],
  seed: 0,
  spec: { robot: "bot.yaml" },
  command: "vexsim run bot.yaml",
  run_id: null,
};

function frame(t: number, x: number, estimate: [number, number, number] | null = null): FrameMessage {
  return {
    type: "frame",
    t,
    phase: "autonomous",
    state: "running",
    speed: 1,
    rate: 1,
    pose: [x, 0, 0],
    estimate,
    speed_in_s: 0,
    battery: [12.8, 100],
    wheels: [],
    distance: {},
    pieces: [],
    contacts: [],
    motors: [],
    lcd: [],
    controller_screen: [],
    controller: { analog: { LEFT_X: 0, LEFT_Y: 0, RIGHT_X: 0, RIGHT_Y: 0 }, digital: [] },
    imu: {},
    gps: {},
    mechanisms: [],
    period_left: null,
  };
}

describe("a session store", () => {
  it("folds the server's messages into the run's state", () => {
    const store = new SessionStore("s1");
    store.apply({ type: "session", session: INFO });
    expect(store.state).toBe("running");
    store.apply({ type: "build", lines: ["compiling"] });
    store.apply(SCENE);
    store.apply({ type: "console", lines: ["autonomous start"] });
    store.apply(frame(0.1, 0, [0, 0, 0]));
    store.apply(frame(0.2, 1, [0.9, 0, 0]));
    expect(store.frame?.t).toBe(0.2);
    expect(store.frames).toBe(2);
    expect(store.truth.xs).toEqual([0, 1]);
    expect(store.estimate.xs).toEqual([0, 0.9]);
    store.apply({ type: "overlay", path: [[0, 0], [24, 0]], target: [24, 0, null] });
    expect(store.overlay?.target).toEqual([24, 0, null]);

    store.apply({ type: "status", state: "finished", message: "autonomous finished at 15.00 s", mode: "autonomous" });
    expect(store.state).toBe("finished");
    expect(store.lines.map((line) => line.text)).toEqual([
      "compiling",
      "autonomous start",
      "autonomous finished at 15.00 s",
    ]);
  });

  it("starts over on a new scene, keeping only the build's lines", () => {
    const store = new SessionStore("s1");
    store.apply({ type: "build", lines: ["compiling"] });
    store.apply(SCENE);
    store.apply({ type: "console", lines: ["hello"] });
    store.apply(frame(5, 10));
    store.apply({ type: "drawings", layers: { mcl: [["pose", 1, 2, 90, "blue"]] } });
    expect(store.drawings.mcl).toHaveLength(1);
    store.apply(SCENE); // restarted
    expect(store.frame).toBeNull();
    expect(store.drawings).toEqual({});
    expect(store.truth.length).toBe(0);
    expect(store.lines).toEqual([{ kind: "build", text: "compiling" }]);
  });

  it("clears its paths when time goes backwards", () => {
    const store = new SessionStore("s1");
    store.apply(frame(5, 10));
    store.apply(frame(5.1, 11));
    store.apply(frame(0, 0));
    expect(store.truth.xs).toEqual([0]);
  });

  it("shows an error's issues and traceback", () => {
    const store = new SessionStore("s1");
    store.apply({
      type: "error",
      message: "bot.yaml: invalid robot config",
      issues: [{ severity: "error", location: "drivetrain.wheels", message: "is required" }],
      traceback: "Traceback:\n  line 1\n",
    });
    expect(store.error?.message).toBe("bot.yaml: invalid robot config");
    expect(store.lines.map((line) => [line.kind, line.text])).toEqual([
      ["error", "bot.yaml: invalid robot config"],
      ["error", "  drivetrain.wheels: is required"],
      ["error", "Traceback:"],
      ["error", "  line 1"],
    ]);
  });

  it("finds where a build failed, and where the program failed", () => {
    const store = new SessionStore("s1", "/home/me/bot");
    store.apply({ type: "build", lines: ["compiling 2 of 2 source file(s)", "/home/me/bot/src/a.cpp:3:1: warning: unused 'x'"] });
    store.apply({
      type: "error",
      message: "compile errors:\n/home/me/bot/src/main.cpp:12:5: error: 'x' was not declared in this scope",
      issues: [],
      traceback: null,
    });
    expect(store.problems.map((p) => `${p.severity} ${p.file}:${p.line}`)).toEqual([
      "warning /home/me/bot/src/a.cpp:3",
      "error /home/me/bot/src/main.cpp:12",
    ]);
    const traceback = 'Traceback (most recent call last):\n  File "/home/me/bot/auton.py", line 4, in autonomous\n    spin()\nNameError: name \'spin\' is not defined\n';
    store.apply({ type: "error", message: "NameError: name 'spin' is not defined", issues: [], traceback });
    expect(store.problems.at(-1)).toMatchObject({ file: "/home/me/bot/auton.py", line: 4, message: "NameError: name 'spin' is not defined" });
    store.apply(SCENE); // restarted: the program's problem goes, the build's stay
    expect(store.problems).toHaveLength(2);
  });

  it("keeps at most MAX_LINES lines, the newest", () => {
    const store = new SessionStore("s1");
    const lines = Array.from({ length: MAX_LINES + 10 }, (_, i) => `line ${i}`);
    store.apply({ type: "console", lines });
    expect(store.lines.length).toBe(MAX_LINES);
    expect(store.lines.at(-1)?.text).toBe(`line ${MAX_LINES + 9}`);
  });

  it("tells its subscribers at once, and about frames at most every 100 ms", () => {
    vi.useFakeTimers();
    try {
      const store = new SessionStore("s1");
      const heard = vi.fn();
      const unsubscribe = store.subscribe(heard);
      store.apply({ type: "console", lines: ["hi"] });
      expect(heard).toHaveBeenCalledTimes(1);
      for (let i = 0; i < 10; i++) store.apply(frame(i / 60, i));
      expect(heard).toHaveBeenCalledTimes(1);
      vi.advanceTimersByTime(100);
      expect(heard).toHaveBeenCalledTimes(2);
      expect(store.getVersion()).toBe(2);
      unsubscribe();
      store.apply({ type: "console", lines: ["bye"] });
      expect(heard).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("holds commands until it's connected, and drops them once closed", () => {
    const store = new SessionStore("s1");
    store.send({ cmd: "pause" });
    store.send({ cmd: "speed", value: 4 });
    expect((store as unknown as { pending: unknown[] }).pending).toEqual([
      { cmd: "pause" },
      { cmd: "speed", value: 4 },
    ]);
    store.close();
    store.send({ cmd: "resume" });
    expect((store as unknown as { pending: unknown[] }).pending).toHaveLength(2);
  });
});

describe("live states", () => {
  it("are running and paused", () => {
    expect(isLive("running") && isLive("paused")).toBe(true);
    expect(isLive("finished") || isLive("building") || isLive("stopped")).toBe(false);
  });
});

import { describe, expect, it } from "vitest";
import { firstSteps } from "../src/components/FirstRun";
import { sessionSteps } from "../src/pages/calibrate/steps";
import type { CalibrationSessionState, ProgramPlan, RunRecord, SessionRun, WorkspaceItem } from "../src/protocol";

const item = (kind: WorkspaceItem["kind"], path: string, problem = ""): WorkspaceItem => ({ kind, path, name: path, detail: "", problem });
const record = (program: string | null) => ({ id: "r", name: "run", spec: { robot: "robot.yaml", program } }) as unknown as RunRecord;

describe("a first run's steps", () => {
  it("are done by what the folder and its run history hold", () => {
    expect(firstSteps([], [])).toEqual({ robot: false, driven: false, program: false, ran: false });
    expect(firstSteps([item("robot", "robot.yaml", "drivetrain: missing")], [])).toMatchObject({ robot: false }); // one that doesn't load isn't one to run
    expect(firstSteps([item("robot", "robot.yaml")], [record(null)])).toEqual({ robot: true, driven: true, program: false, ran: false });
    expect(firstSteps([item("robot", "robot.yaml"), item("project", "bot")], [])).toMatchObject({ program: true, ran: false });
    expect(firstSteps([item("robot", "robot.yaml"), item("program", "p.py")], [record(null), record("p.py")])).toEqual({ robot: true, driven: true, program: true, ran: true });
  });

  it("count the run on the page now, which isn't in the history until it ends", () => {
    const items = [item("robot", "robot.yaml"), item("program", "p.py")];
    expect(firstSteps(items, [], { program: null })).toMatchObject({ driven: true, ran: false }); // driving, no program
    expect(firstSteps(items, [], { program: "p.py" })).toMatchObject({ driven: true, ran: true });
    expect(firstSteps(items, [], {})).toMatchObject({ driven: true, ran: false }); // just started: nothing known of it yet
  });
});

describe("a calibration session's steps", () => {
  const plan = { tests: [{ key: "free_spin" }, { key: "drive" }] } as unknown as ProgramPlan;
  const run = (test: string, quality = "good", use = true) => ({ file: `${test}.csv`, test, run: 1, quality, use }) as unknown as SessionRun;
  const session = (runs: SessionRun[], report = false, practice = false) =>
    ({ path: "calibration/today", exists: true, runs, practice, report: report ? { fitted: "today" } : null }) as unknown as CalibrationSessionState;
  const states = (...args: Parameters<typeof sessionSteps>) => sessionSteps(...args).map((s) => s.state);

  it("go from the robot to the fit, one next at a time", () => {
    expect(states("", "", null, null)).toEqual(["next", "todo", "todo", "todo", "todo"]);
    expect(states("robot.yaml", "field.yaml", null, null)).toEqual(["done", "next", "todo", "todo", "todo"]);
    expect(states("robot.yaml", "field.yaml", plan, session([]))).toEqual(["done", "done", "next", "todo", "todo"]);
    expect(states("robot.yaml", "field.yaml", plan, session([run("free_spin")]))).toEqual(["done", "done", "done", "next", "todo"]);
    expect(states("robot.yaml", "field.yaml", plan, session([run("free_spin"), run("drive")]))).toEqual(["done", "done", "done", "done", "next"]);
    expect(states("robot.yaml", "field.yaml", plan, session([run("free_spin"), run("drive")], true))).toEqual(["done", "done", "done", "done", "done"]);
  });

  it("count a test as run only by a good run that's in use", () => {
    const some = [run("free_spin"), run("drive", "too short"), run("drive", "good", false)];
    const found = sessionSteps("robot.yaml", "field.yaml", plan, session(some));
    expect(found[3]).toMatchObject({ key: "runs", state: "next", detail: "1 of 2 tests has a good run" });
    expect(found[2].detail).toBe("3 runs collected");
    expect(sessionSteps("robot.yaml", "field.yaml", plan, session(some, false, true))[2].detail).toBe("3 runs collected (practice)");
  });

  it("go by the session's own tests when its program isn't in the folder", () => {
    // logs collected from a card, their program written elsewhere: the steps before stay to do
    expect(states("robot.yaml", "field.yaml", null, session([run("drive")], true))).toEqual(["done", "next", "done", "done", "done"]);
  });
});

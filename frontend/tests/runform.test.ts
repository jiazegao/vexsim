import { describe, expect, it } from "vitest";
import type { WorkspaceItem } from "../src/protocol";
import { emptyForm, formToSpec, reconcile, sameRun, specToForm } from "../src/runform";

function item(kind: WorkspaceItem["kind"], path: string, problem = ""): WorkspaceItem {
  return { kind, path, name: path, detail: "", problem };
}

describe("the run form", () => {
  it("needs a robot", () => {
    expect(formToSpec(emptyForm())).toEqual({ error: "Pick a robot" });
  });

  it("turns into a run spec, and back", () => {
    const form = {
      ...emptyForm(),
      robot: "robots/bot.yaml",
      program: "src/auton.py",
      mode: "driver" as const,
      x: " -12 ",
      y: "3.5",
      heading: "90",
      seed: "4",
      env: "VEXSIM_AUTON=Left 40\n\n  X = 1=2  \n",
    };
    const result = formToSpec(form);
    expect(result).toEqual({
      spec: {
        robot: "robots/bot.yaml",
        program: "src/auton.py",
        routine: null,
        field: null,
        mode: "driver",
        start: [-12, 3.5, 90],
        seed: 4,
        noise: null,
        input: null,
        follow: null,
        env: { VEXSIM_AUTON: "Left 40", X: " 1=2" },
        busy_timeout: 5,
      },
    });
    if (!("spec" in result)) throw new Error("no spec");
    const again = specToForm(result.spec);
    expect(formToSpec(again)).toEqual(result);
  });

  it("picks a PROS project's routine, which goes with its program", () => {
    const form = { ...emptyForm(), robot: "bot.yaml", program: "pros/1239e", routine: "right30" };
    const result = formToSpec(form);
    if (!("spec" in result)) throw new Error(result.error);
    expect(result.spec.routine).toBe("right30");
    expect(specToForm(result.spec).routine).toBe("right30");
    expect(sameRun(form, result.spec)).toBe(true);
    expect(sameRun({ ...form, routine: "" }, result.spec)).toBe(false); // as the project picks
    const none = formToSpec({ ...form, program: "" }); // no program, no routine
    expect("spec" in none && none.spec.routine).toBe(null);
  });

  it("follows a log, or any log a saved run is given", () => {
    const form = { ...emptyForm(), robot: "bot.yaml", program: "tank.py" };
    const spec = (f: typeof form) => {
      const result = formToSpec(f);
      if (!("spec" in result)) throw new Error(result.error);
      return result.spec;
    };
    expect(spec(form).follow).toBeNull();
    expect(spec({ ...form, sticks: "arcade", curve: "15, 20, 1.05" }).follow).toBeNull(); // not following
    const following = { ...form, follow: "logs/mcl_log1.1239e", following: true, sticks: "arcade" as const, curve: "15, 20, 1.05" };
    expect(spec(following).follow).toEqual({ log: "logs/mcl_log1.1239e", sticks: "arcade", curve: [15, 20, 1.05] });
    const template = { robot: "bot.yaml", program: "tank.py", follow: { curve: [15, 20, 1.05] as [number, number, number] } };
    const filled = specToForm(template, "Replay");
    expect([filled.following, filled.follow, filled.sticks, filled.curve]).toEqual([true, "", "tank", "15, 20, 1.05"]);
    expect(spec(filled).follow).toEqual({ log: null, sticks: "tank", curve: [15, 20, 1.05] });
    expect(sameRun(filled, template)).toBe(true);
    expect(sameRun({ ...filled, follow: "logs/mcl_log1.1239e" }, template)).toBe(false);
    expect(formToSpec({ ...following, curve: "15, 20" })).toEqual({ error: "The drive curve is three numbers: deadband, min output, curve (15, 20, 1.05)" });
    // a log that's gone from the workspace is let go of
    expect(reconcile(following, [item("robot", "bot.yaml"), item("program", "tank.py")]).follow).toBe("");
    expect(reconcile(following, [item("robot", "bot.yaml"), item("mcllog", "logs/mcl_log1.1239e")]).follow).toBe("logs/mcl_log1.1239e");
  });

  it("says what's wrong with what was typed", () => {
    const form = { ...emptyForm(), robot: "bot.yaml" };
    expect(formToSpec({ ...form, x: "" })).toEqual({ error: "Start x must be a number" });
    expect(formToSpec({ ...form, heading: "north" })).toEqual({ error: "Heading must be a number" });
    expect(formToSpec({ ...form, seed: "1.5" })).toEqual({ error: "Seed must be a whole number" });
    expect(formToSpec({ ...form, env: "=1" })).toEqual({ error: 'environment lines are KEY=VALUE, not "=1"' });
    expect(formToSpec({ ...form, busy: "-1" })).toEqual({ error: "Busy timeout can't be negative" });
  });

  it("knows whether it still matches the configuration it was filled from", () => {
    const saved = { robot: "bot.yaml", program: "auton.py", start: [60, 0, 0] as [number, number, number], env: { B: "2", A: "1" } };
    const form = specToForm(saved, "Left");
    expect(form.config).toBe("Left");
    expect(sameRun(form, saved)).toBe(true);
    expect(sameRun({ ...form, x: "60.0", env: "A=1\nB=2" }, saved)).toBe(true); // the same run, written differently
    expect(sameRun({ ...form, seed: "3" }, saved)).toBe(false);
    expect(sameRun({ ...form, x: "oops" }, saved)).toBe(false);
  });

  it("forgets picks the workspace no longer has, and picks a working robot", () => {
    const items = [
      item("robot", "broken.yaml", "invalid robot config"),
      item("robot", "bot.yaml"),
      item("project", "pros"),
      item("field", "field.yaml"),
    ];
    const form = { ...emptyForm(), robot: "gone.yaml", program: "pros", field: "old.yaml", input: "in.csv" };
    expect(reconcile(form, items)).toEqual({ ...form, robot: "bot.yaml", field: "", input: "" });
    const kept = { ...emptyForm(), robot: "broken.yaml", field: "field.yaml" };
    expect(reconcile(kept, items)).toEqual(kept); // a pick that's there stays, even a broken one
  });
});

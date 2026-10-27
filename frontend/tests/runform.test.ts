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
        field: null,
        mode: "driver",
        start: [-12, 3.5, 90],
        seed: 4,
        noise: null,
        input: null,
        env: { VEXSIM_AUTON: "Left 40", X: " 1=2" },
        busy_timeout: 5,
      },
    });
    if (!("spec" in result)) throw new Error("no spec");
    const again = specToForm(result.spec);
    expect(formToSpec(again)).toEqual(result);
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

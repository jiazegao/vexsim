import { describe, expect, it } from "vitest";
import type { WorkspaceItem } from "../src/protocol";
import { emptyForm, formToSpec, reconcile, specToForm } from "../src/runform";

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

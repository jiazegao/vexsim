import { describe as group, expect, it } from "vitest";
import type { RouteData, RouteFunctionInfo, RouteStepData } from "../src/protocol";
import { bearing, describe, dropEdit, newRoutePath, newStep, numbersText, plan, relativePath, rotateAbout, routeFileName, stepValue, turnAmount, withDrag, wrap360 } from "../src/route";

function step(kind: string, target: number[], extra: Partial<RouteStepData> = {}): RouteStepData {
  return { kind, target, timeout: 1000, side: null, options: {}, function: null, args: {}, label: kind, ...extra };
}

function route(start: [number, number, number], steps: RouteStepData[]): RouteData {
  return { name: "test", start, robot: null, field: null, functions: [], steps };
}

const close = (actual: readonly number[], expected: number[]) => actual.forEach((v, i) => expect(v).toBeCloseTo(expected[i], 6));

const MOVE_FORWARD: RouteFunctionInfo = {
  name: "moveForward",
  header: "include/custom/util_funcs.hpp",
  line: 7,
  declaration: "void moveForward(float inches, int timeout, float maxSpeed = 127)",
  params: [
    { name: "inches", type: "float", kind: "number", default: null, value: null, values: [] },
    { name: "timeout", type: "int", kind: "integer", default: null, value: null, values: [] },
    { name: "maxSpeed", type: "float", kind: "number", default: "127", value: 127, values: [] },
  ],
  required: 2,
  hint: { motion: "drive", args: ["inches"] },
  hint_problem: null,
};

group("LemLib's angles", () => {
  it("measures headings clockwise from +y, and turns the way it's told", () => {
    expect([bearing([0, 0], [0, 10]), bearing([0, 0], [10, 0]), bearing([0, 0], [0, -10]), bearing([0, 0], [-10, 0])]).toEqual([0, 90, 180, 270]);
    expect(wrap360(-90)).toBe(270);
    expect(turnAmount(350, 10, "auto")).toBeCloseTo(20);
    expect(turnAmount(10, 350, "cw")).toBeCloseTo(340);
    expect(turnAmount(350, 10, "ccw")).toBeCloseTo(-340);
    close(rotateAbout([1, 0], [0, 0], 90), [0, -1]); // clockwise
  });
});

group("planned endpoints", () => {
  it("follows LemLib's targets: a point, facing the way it went, a pose, turns in place", () => {
    const planned = plan(
      route([0, 0, 0], [
        step("move_to_point", [24, 24]),
        step("move_to_point", [24, 0], { options: { forwards: false } }),
        step("turn_to_heading", [270]),
        step("turn_to_point", [0, 0]),
        step("move_to_pose", [-24, 0, 180], { options: { lead: 0.5 } }),
        step("wait", [100]),
      ]),
      [],
      12,
    );
    close(planned[0].pose, [24, 24, 45]);
    close(planned[1].pose, [24, 0, 0]); // backwards: facing away from where it went
    close(planned[2].pose, [24, 0, 270]);
    close(planned[3].pose, [24, 0, 270]); // (0, 0) is straight ahead of it
    close(planned[4].pose, [-24, 0, 180]);
    close(planned[4].path[0], [24, 0]);
    close(planned[4].path.at(-1)!, [-24, 0]);
    expect(planned[5].path).toEqual([]);
    expect(planned.every((p) => p.known)).toBe(true);
  });

  it("swings about the locked side, the drive's track across", () => {
    const [left, right] = [
      plan(route([0, 0, 0], [step("swing_to_heading", [90], { side: "left" })]), [], 10)[0],
      plan(route([0, 0, 0], [step("swing_to_heading", [90], { side: "right" })]), [], 10)[0],
    ];
    close(left.pose, [-5, -5, 90]); // about its left wheels: back and to the left
    close(right.pose, [5, 5, 90]); // about its right wheels: ahead and to the right
    const toward = plan(route([0, 0, 0], [step("swing_to_point", [40, 0], { side: "right" })]), [], 10)[0];
    expect(toward.pose[2]).toBeCloseTo(bearing([toward.pose[0], toward.pose[1]], [40, 0]), 3); // facing it, from where it ended
  });

  it("follows the team's functions as their comments say, and carries the others on", () => {
    const steps = [step("call", [], { function: "moveForward", args: { inches: -10, timeout: 800 } }), step("call", [], { function: "startIntake" }), step("move_to_point", [0, 0])];
    const planned = plan(route([60, 0, 90], steps), [MOVE_FORWARD], 12);
    close(planned[0].pose, [50, 0, 90]); // 10 in back along its heading
    expect([planned[1].known, planned[1].ran]).toEqual([false, false]);
    close(planned[1].pose, [50, 0, 90]); // stays put: nothing says where it goes
    // after a run, the plan goes on from where the robot really was
    const after = plan(route([60, 0, 90], steps), [MOVE_FORWARD], 12, [null, [49, 2, 95]]);
    expect(after[1].ran).toBe(true);
    close(after[2].path[0], [49, 2]);
    const unknown = plan(route([60, 0, 90], [step("call", [], { function: "moveForward", args: { timeout: 800 } })]), [MOVE_FORWARD], 12);
    expect(unknown[0].known).toBe(false); // inches has no value to plan with
  });
});

group("writing steps", () => {
  it("writes a step as its YAML has it, its keys in LemLib's order", () => {
    const swing = step("swing_to_point", [24, 0], { side: "right", timeout: 900, options: { async: false, early_exit: 2, direction: "cw" } });
    expect(JSON.stringify(stepValue(swing))).toBe('{"swing_to_point":[24,0],"locked_side":"right","timeout":900,"direction":"cw","early_exit":2,"async":false}');
    expect(stepValue(step("wait_until_done", []))).toBe("wait_until_done");
    expect(stepValue(step("turn_to_heading", [90]))).toEqual({ turn_to_heading: 90, timeout: 1000 });
    expect(stepValue(step("call", [], { function: "startIntake" }))).toEqual({ call: "startIntake" });
  });

  it("starts a new step 24 inches ahead of where the robot is, or a quarter turn on", () => {
    expect(newStep("move_to_point", [0, 0, 90]).target).toEqual([24, 0]);
    expect(newStep("turn_to_heading", [0, 0, 300]).target).toEqual([30]);
    expect(newStep("call", [0, 0, 0], MOVE_FORWARD).args).toEqual({ inches: 0, timeout: 1000 });
  });

  it("makes a new motion wait until it's done, with time to get there", () => {
    const move = newStep("move_to_point", [0, 0, 90]); // 24 in ahead
    expect([move.options, move.timeout]).toEqual([{ async: false }, 1600]);
    expect(newStep("move_to_point", [0, 0, 90], undefined, [60, 0]).timeout).toBe(3000); // farther: longer
    expect(newStep("turn_to_heading", [0, 0, 0]).timeout).toBe(1000); // a quarter turn
    expect(newStep("wait", [0, 0, 0]).options).toEqual({});
    expect(stepValue(move)).toEqual({ move_to_point: [24, 0], timeout: 1600, async: false });
  });

  it("numbers the steps that end in one place as one marker", () => {
    expect([numbersText([4]), numbersText([1, 2]), numbersText([1, 2, 3, 5]), numbersText([1, 2, 4, 5])]).toEqual(["4", "1,2", "1–3,5", "1,2,4,5"]);
  });

  it("describes each step in a few words", () => {
    expect(describe(step("move_to_point", [14, 0], { options: { max_speed: 60 } }))).toBe("Move to (14, 0) · max 60 · async");
    expect(describe(step("turn_to_heading", [270], { options: { async: false, direction: "ccw" } }))).toBe("Turn to 270° · ccw · waits");
    expect(describe(step("call", [], { function: "moveForward", args: { inches: -10, timeout: 800 } }))).toBe("moveForward(inches -10, timeout 800)");
  });
});

group("dragging on the field", () => {
  it("moves what's dragged at once, and writes just its numbers when it's dropped", () => {
    const start = route([0, 0, 0], [step("move_to_pose", [24, 0, 90]), step("turn_to_heading", [90])]);
    const moved = withDrag(start, { grip: { kind: "target", index: 0 }, value: [30, 6] });
    expect(moved.steps[0].target).toEqual([30, 6, 90]); // its heading stays
    close(plan(moved, [], 12)[0].pose, [30, 6, 90]); // the plan follows the drag
    expect(withDrag(start, { grip: { kind: "heading", index: 0 }, value: [180] }).steps[0].target).toEqual([24, 0, 180]);
    expect(withDrag(start, { grip: { kind: "start" }, value: [-12, 6, 0] }).start).toEqual([-12, 6, 0]);
    expect(withDrag(start, null)).toBe(start);
    expect(dropEdit(start, { grip: { kind: "target", index: 0 }, value: [30, 6] })).toEqual({ op: "set", location: "steps[0].move_to_pose", value: [30, 6, 90] });
    expect(dropEdit(start, { grip: { kind: "heading", index: 1 }, value: [180] })).toEqual({ op: "set", location: "steps[1].turn_to_heading", value: 180 });
    expect(dropEdit(start, { grip: { kind: "start-heading" }, value: [0, 0, 45] })).toEqual({ op: "set", location: "start", value: [0, 0, 45] });
  });
});

group("a route's files", () => {
  it("writes its robot and field relative to it", () => {
    expect(relativePath("examples/pros_projects/p/routes/a.yaml", "examples/robots/r.yaml")).toBe("../../../robots/r.yaml");
    expect(relativePath("routes/a.yaml", "robot.yaml")).toBe("../robot.yaml");
    expect(relativePath("p/routes/a.yaml", "p/routes/field.yaml")).toBe("field.yaml");
  });

  it("names a new route's file as the server does, never over another", () => {
    expect(routeFileName("Left 40 (fast)!")).toBe("left_40_fast.yaml");
    expect(routeFileName("!!!")).toBe("route.yaml");
    expect(newRoutePath("p", "Left", ["p/routes/left.yaml", "p/routes/left_2.yaml"])).toBe("p/routes/left_3.yaml");
    expect(newRoutePath(".", " ", [])).toBe("routes/new_route.yaml"); // a project at the workspace's root
  });
});

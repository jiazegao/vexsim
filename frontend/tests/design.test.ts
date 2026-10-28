import { describe, expect, it } from "vitest";
import type { Copied, ShapePart } from "../src/design";
import {
  circleTo,
  copiedPart,
  copyOf,
  copyPart,
  describePart,
  describeUser,
  fileStem,
  freePorts,
  frontOf,
  mirroredPart,
  movedPart,
  nameProblem,
  newGroup,
  newMechanism,
  newRobotPath,
  newSensor,
  newWheel,
  outlineProblem,
  pasteEdits,
  partAt,
  partContains,
  partEdits,
  portMap,
  ratioValue,
  readPorts,
  readRatio,
  rectBetween,
  removeWheelEdits,
  renameWheelEdits,
  reshaped,
  robotFolder,
  shapeOf,
  shown,
  snapTo,
  uniqueName,
  wheelTypeEdits,
  written,
} from "../src/design";
import type { RobotConfig } from "../src/protocol";

// A tank drive on an 18 x 14 in footprint, an intake on port 5, an IMU and a tracking wheel.
const TANK: RobotConfig = {
  name: "bot",
  body: { mass_kg: 6, footprint_in: [18, 14], cg_in: [0, 0, 4] },
  drivetrain: {
    type: "differential",
    wheels: [
      { name: "lf", pos_in: [5, 7], type: "omni", diameter_in: 3.25 },
      { name: "lb", pos_in: [-5, 7], type: "omni", diameter_in: 3.25 },
      { name: "rf", pos_in: [5, -7], type: "omni", diameter_in: 3.25 },
      { name: "rb", pos_in: [-5, -7], type: "omni", diameter_in: 3.25 },
    ],
    gearing: {
      left: { motors: [1, 2], cartridge: "blue", ratio: "36:48", wheels: ["lf", "lb"] },
      right: { motors: [-3, -4], cartridge: "blue", ratio: "36:48", wheels: ["rf", "rb"] },
    },
  },
  mechanisms: { intake: { motors: [5], cartridge: "green" } },
  sensors: [
    { type: "imu", port: 6 },
    { type: "rotation", port: 8, tracking_wheel: { pos_in: [0, -1.5], heading_deg: 0, diameter_in: 2 } },
  ],
};
const BASE: ShapePart = { type: "rect", pos_in: [0, 0], size_in: [15, 15], heading_deg: 0 };
const INTAKE: ShapePart = { type: "circle", pos_in: [7.5, 0], diameter_in: 5 };
const SHAPED: RobotConfig = { ...TANK, body: { ...TANK.body, footprint_in: null, shape: [BASE, INTAKE] } };

describe("a new robot's file", () => {
  it("is named for the robot, beside the other robots, and over no file", () => {
    expect(fileStem("Test bot #2")).toBe("test_bot_2");
    expect(fileStem("###")).toBe("robot");
    expect(robotFolder(["examples/robots/a.yaml", "examples/robots/b.yaml", "c.yaml"])).toBe("examples/robots");
    expect(robotFolder(["c.yaml", "d.yaml", "x/e.yaml"])).toBe("");
    expect(robotFolder([])).toBe("robots");
    expect(newRobotPath("examples/robots", "Test bot", ["examples/robots/test_bot.yaml"])).toBe("examples/robots/test_bot_2.yaml");
    expect(newRobotPath("", "Bot", [])).toBe("bot.yaml");
  });
});

describe("the robot's shape", () => {
  it("is a footprint's rectangle until its first change makes it a shape", () => {
    expect(shapeOf(TANK.body)).toEqual([{ type: "rect", pos_in: [0, 0], size_in: [18, 14], heading_deg: 0 }]);
    expect(partEdits(TANK, null, INTAKE)).toEqual([
      { location: "body.footprint_in", op: "remove" },
      {
        location: "body.shape",
        op: "set",
        value: [
          { type: "rect", size_in: [18, 14] }, // what's at its default isn't written
          { type: "circle", pos_in: [7.5, 0], diameter_in: 5 },
        ],
      },
    ]);
  });

  it("changes part by part, and in a part just what changed", () => {
    expect(partEdits(SHAPED, 1, { ...INTAKE, diameter_in: 6 })).toEqual([{ location: "body.shape[1].diameter_in", op: "set", value: 6 }]);
    expect(partEdits(SHAPED, 0, movedPart(BASE, 1, 0.5))).toEqual([{ location: "body.shape[0].pos_in", op: "set", value: [1, 0.5] }]);
    expect(partEdits(SHAPED, 1, null)).toEqual([{ location: "body.shape[1]", op: "remove" }]);
    const tail: ShapePart = { type: "outline", points_in: [[-7.5, 4], [-9, 2], [-9, -2], [-7.5, -4]] };
    expect(partEdits(SHAPED, null, tail)).toEqual([{ location: "body.shape", op: "add", value: written(tail) }]);
    expect(written({ ...BASE, heading_deg: 0.1 + 0.2 })).toEqual({ type: "rect", size_in: [15, 15], heading_deg: 0.3 });
  });

  it("mirrors across the robot's center line, unless a part is its own mirror image", () => {
    expect(mirroredPart(BASE)).toBeNull();
    expect(mirroredPart(INTAKE)).toBeNull();
    expect(mirroredPart({ type: "rect", pos_in: [-8, 5], size_in: [2, 3], heading_deg: 10 })).toEqual({ type: "rect", pos_in: [-8, -5], size_in: [2, 3], heading_deg: -10 });
    // an outline's points run the same way round
    expect(mirroredPart({ type: "outline", points_in: [[0, 1], [2, 1], [1, 3]] })).toEqual({ type: "outline", points_in: [[1, -3], [2, -1], [0, -1]] });
    expect(mirroredPart({ type: "outline", points_in: [[0, 1], [2, 1], [2, -1], [0, -1]] })).toBeNull();
  });

  it("is drawn corner to corner, center out, and reshaped by its handles on the snap", () => {
    expect(rectBetween([0, 0], [4, -2])).toEqual({ type: "rect", pos_in: [2, -1], size_in: [4, 2], heading_deg: 0 });
    expect(rectBetween([1, 1], [1, 5])).toBeNull(); // no area
    expect(circleTo([0, 0], [3, 4], 0.25)).toEqual({ type: "circle", pos_in: [0, 0], diameter_in: 10 });
    expect(circleTo([0, 0], [0.05, 0], 0.25)).toBeNull(); // a click, not a drag
    // a 4 x 2 rectangle's front-left corner dragged: the back-right one stays put
    const box: ShapePart = { type: "rect", pos_in: [0, 0], size_in: [4, 2], heading_deg: 0 };
    expect(reshaped(box, 0, 3.1, 1.9, 0.25)).toEqual({ ...box, pos_in: [0.5, 0.5], size_in: [5, 3] });
    expect(reshaped(INTAKE, 0, 11, 0, 0.25)).toEqual({ ...INTAKE, diameter_in: 7 });
    expect(snapTo(0.13, 0.25)).toBe(0.25);
    expect(Object.is(snapTo(-0.1, 0.25), 0)).toBe(true); // never -0
  });

  it("knows which part is where, the last drawn on top", () => {
    const shape = shapeOf(SHAPED.body);
    expect(partAt(shape, 9, 0)).toBe(1); // the intake
    expect(partAt(shape, 7, 0)).toBe(1); // both: the one on top
    expect(partAt(shape, 0, 7)).toBe(0);
    expect(partAt(shape, 0, 8)).toBeNull();
    const tail: ShapePart = { type: "outline", points_in: [[0, 0], [4, 0], [0, 4]] };
    expect(partContains(tail, 1, 1)).toBe(true);
    expect(partContains(tail, 3, 3)).toBe(false);
    expect(partContains(tail, 2.2, 2.2, 0.5)).toBe(true); // near its edge
    expect(frontOf(SHAPED.body)).toBe(10); // the intake's front, on the robot's axis
    expect(frontOf(TANK.body)).toBe(9);
    const jaw: ShapePart = { type: "rect", pos_in: [9, 3.75], size_in: [4, 2.5], heading_deg: 0 };
    const clamp = { ...TANK.body, footprint_in: null, shape: [BASE, jaw, mirroredPart(jaw)!] };
    expect(frontOf(clamp)).toBe(7.5); // between the jaws, not their tips
    expect(frontOf({ ...clamp, shape: [jaw] })).toBe(11); // the axis misses it: its furthest
    expect(describePart(BASE)).toBe("Rectangle 15 × 15 in at 0, 0");
    expect(describePart(INTAKE)).toBe("Circle ⌀ 5 in at 7.5, 0");
  });

  it("says what's wrong with an outline", () => {
    expect(outlineProblem([[0, 0], [2, 0]])).toMatch(/three points/);
    expect(outlineProblem([[0, 0], [2, 2], [2, 0], [0, 2]])).toBe("its edges cross");
    expect(outlineProblem([[0, 0], [2, 0], [2, 2], [0, 2]])).toBeNull();
  });
});

describe("motors and sensors", () => {
  it("map the ports, and new ones take the first free port", () => {
    const ports = portMap(TANK);
    expect(ports.get(3)).toEqual([{ name: "right", kind: "drive", reversed: true }]);
    expect(ports.get(8)?.map(describeUser)).toEqual(["rotation sensor"]);
    expect(describeUser({ name: "intake", kind: "mechanism", reversed: true })).toBe("intake motor, reversed");
    expect(freePorts(TANK).slice(0, 3)).toEqual([7, 9, 10]);
    const clash = portMap({ ...TANK, sensors: [{ type: "imu", port: 5 }] });
    expect(clash.get(5)?.map((u) => u.kind)).toEqual(["mechanism", "sensor"]);
    expect(newGroup(TANK)).toEqual(["group", { motors: [7], cartridge: "blue", wheels: ["lf"] }]);
    expect(newMechanism(TANK)).toEqual(["mechanism", { motors: [7], cartridge: "green" }]);
    expect(newWheel(TANK)).toEqual({ name: "wheel", pos_in: [0, 0], type: "omni", diameter_in: 3.25 });
  });

  it("put a new sensor where it's of use", () => {
    expect(newSensor(TANK, "imu")).toEqual({ type: "imu", port: 7, pos_in: [-2, 2] });
    expect(newSensor(TANK, "distance")).toEqual({ type: "distance", port: 7, pos_in: [8.5, 0], heading_deg: 0 }); // at the front
    expect(newSensor(SHAPED, "distance").pos_in).toEqual([9.5, 0]); // the intake's front
    // a forward tracking wheel is there: the next one rolls sideways
    expect(newSensor(TANK, "rotation")).toEqual({ type: "rotation", port: 7, tracking_wheel: { pos_in: [-2, 0], heading_deg: 90, diameter_in: 2 } });
    expect(newSensor({ ...TANK, sensors: [] }, "rotation").tracking_wheel).toEqual({ pos_in: [0, -1.5], heading_deg: 0, diameter_in: 2 });
  });

  it("keep the motor groups' wheels as the wheels are renamed and taken away", () => {
    expect(renameWheelEdits(TANK, 0, "front_left")).toEqual([
      { location: "drivetrain.wheels[0].name", op: "set", value: "front_left" },
      { location: "drivetrain.gearing.left.wheels", op: "set", value: ["front_left", "lb"] },
    ]);
    expect(removeWheelEdits(TANK, 1)).toEqual([
      { location: "drivetrain.wheels[1]", op: "remove" },
      { location: "drivetrain.gearing.left.wheels", op: "set", value: ["lf"] },
    ]);
    expect(wheelTypeEdits(TANK, 0, "mecanum")).toEqual([
      { location: "drivetrain.wheels[0].type", op: "set", value: "mecanum" },
      { location: "drivetrain.wheels[0].roller_angle_deg", op: "set", value: -45 }, // front left
    ]);
    expect(wheelTypeEdits(TANK, 2, "mecanum")[1].value).toBe(45); // front right
    const mecanum = { ...TANK, drivetrain: { ...TANK.drivetrain, wheels: [{ ...TANK.drivetrain.wheels[0], type: "mecanum" as const, roller_angle_deg: -45 }] } };
    expect(wheelTypeEdits(mecanum, 0, "omni")).toEqual([
      { location: "drivetrain.wheels[0].type", op: "set", value: "omni" },
      { location: "drivetrain.wheels[0].roller_angle_deg", op: "remove" },
    ]);
  });

  it("read ports, ratios, names and numbers as typed", () => {
    expect(readPorts("1, 2, -3")).toEqual([1, 2, -3]);
    expect(readPorts("4 5")).toEqual([4, 5]);
    for (const bad of ["", "0", "22", "1.5", "a"]) expect(readPorts(bad)).toBeNull();
    expect(readRatio("36:48")).toBe("36:48");
    expect(readRatio(" 36 : 48 ")).toBe("36:48");
    expect(readRatio("0.75")).toBe(0.75);
    for (const bad of ["", "x", "0:5", "-1"]) expect(readRatio(bad)).toBeNull();
    expect(ratioValue("36:48")).toBe(0.75);
    expect(ratioValue(undefined)).toBe(1);
    expect(nameProblem("lift_2")).toBeNull();
    expect(nameProblem("2nd")).toMatch(/can't be a name/);
    expect(nameProblem("left", ["left", "right"])).toMatch(/already/);
    expect(uniqueName("mechanism", ["mechanism", "mechanism2"])).toBe("mechanism3");
    expect(shown(0.1 + 0.2)).toBe("0.3");
    expect(shown(null)).toBe("");
  });
});

describe("copy and paste", () => {
  // the robot as the server sends it: every field, defaults and all
  const SERVED: RobotConfig = {
    ...TANK,
    drivetrain: { ...TANK.drivetrain, wheels: TANK.drivetrain.wheels.map((w) => ({ ...w, heading_deg: 0, drop_in: 0, roller_angle_deg: null })) },
    sensors: [
      { type: "imu", port: 6, pos_in: [0, 0], mount_yaw_deg: 0, noise: "default", scale_error: null },
      { type: "rotation", port: 8, reversed: false, noise: "default", tracking_wheel: { pos_in: [0, -1.5], heading_deg: 0, diameter_in: 2 } },
    ],
  };

  it("copies what's selected, as it would be written", () => {
    expect(copyOf(SERVED, null, "drivetrain.wheels[0]")).toEqual({
      kind: "wheel",
      value: { name: "lf", pos_in: [5, 7], type: "omni", diameter_in: 3.25 },
      groups: ["left"],
      label: "wheel lf",
      pastes: 0,
    });
    expect(copyOf(SERVED, null, "sensors[1].tracking_wheel")).toEqual({
      kind: "sensor",
      value: { type: "rotation", port: 8, tracking_wheel: { pos_in: [0, -1.5], diameter_in: 2 } },
      groups: [],
      label: "the rotation sensor on port 8",
      pastes: 0,
    });
    expect((copyOf(SERVED, null, "sensors[0]") as Copied).value).toEqual({ type: "imu", port: 6 });
    expect(copyOf(SHAPED, 1, "drivetrain.wheels[0]")).toMatchObject({ kind: "shape", value: { type: "circle", pos_in: [7.5, 0], diameter_in: 5 }, label: "the circle" });
    expect(copyOf(SERVED, null, "body")).toMatch(/center of gravity/);
    expect(copyOf(SERVED, null, null)).toBeNull();
    expect(copyOf(SERVED, null, "drivetrain.wheels[9]")).toBeNull();
    const copy = copyOf(SERVED, null, "sensors[0]") as Copied;
    copyPart(copy);
    expect(copiedPart()).toBe(copy); // one for the page: every robot's editor pastes it
  });

  it("pastes a wheel a step along, under the next of its name, in its motor groups", () => {
    const wheel = copyOf(SERVED, null, "drivetrain.wheels[0]") as Copied;
    expect(pasteEdits(SERVED, wheel)).toEqual({
      edits: [
        { location: "drivetrain.wheels", op: "add", value: { name: "lf2", pos_in: [6, 6], type: "omni", diameter_in: 3.25 } },
        { location: "drivetrain.gearing.left.wheels", op: "set", value: ["lf", "lb", "lf2"] },
      ],
      part: null,
      path: "drivetrain.wheels[4]",
      label: "wheel lf2",
    });
    wheel.pastes = 1; // the next lands a step further
    const two = { ...SERVED, drivetrain: { ...SERVED.drivetrain, wheels: [...SERVED.drivetrain.wheels, { ...SERVED.drivetrain.wheels[0], name: "lf2" }] } };
    expect(pasteEdits(two, wheel).edits[0].value).toEqual({ name: "lf3", pos_in: [7, 5], type: "omni", diameter_in: 3.25 });
    // into a robot that hasn't its name or its group: its own name, in no group
    const xdrive: RobotConfig = {
      ...SERVED,
      drivetrain: { type: "xdrive", wheels: [{ name: "fl", pos_in: [5, 5], type: "omni", diameter_in: 3.25 }], gearing: { front_left: { motors: [1], cartridge: "blue", wheels: ["fl"] } } },
    };
    expect(pasteEdits(xdrive, { ...wheel, pastes: 0 }).edits).toEqual([{ location: "drivetrain.wheels", op: "add", value: { name: "lf", pos_in: [6, 6], type: "omni", diameter_in: 3.25 } }]);
  });

  it("pastes a sensor on its port if it's free, else the first free one, and parts of the shape", () => {
    const tracking = copyOf(SERVED, null, "sensors[1].tracking_wheel") as Copied;
    expect(pasteEdits(SERVED, tracking)).toEqual({
      edits: [{ location: "sensors", op: "add", value: { type: "rotation", port: 7, tracking_wheel: { pos_in: [1, -2.5], diameter_in: 2 } } }],
      part: null,
      path: "sensors[2].tracking_wheel",
      label: "a rotation sensor on port 7",
    });
    const imu = copyOf(SERVED, null, "sensors[0]") as Copied;
    expect(pasteEdits({ ...SERVED, sensors: [] }, imu).label).toBe("an IMU on port 6"); // free there
    expect(pasteEdits(SHAPED, copyOf(SHAPED, 1, null) as Copied)).toEqual({
      edits: [{ location: "body.shape", op: "add", value: { type: "circle", pos_in: [8.5, -1], diameter_in: 5 } }],
      part: 2,
      path: null,
      label: "a copy of the circle",
    });
    // a footprint's rectangle, pasted: the footprint becomes a shape of the two
    const pasted = pasteEdits(TANK, copyOf(TANK, 0, null) as Copied);
    expect(pasted.edits).toEqual([
      { location: "body.footprint_in", op: "remove" },
      { location: "body.shape", op: "set", value: [{ type: "rect", size_in: [18, 14] }, { type: "rect", pos_in: [1, -1], size_in: [18, 14] }] },
    ]);
    expect(pasted.part).toBe(1);
  });
});

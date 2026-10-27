import { describe, expect, it } from "vitest";
import {
  fieldParts,
  issuesOf,
  moveEdits,
  partAtLine,
  robotParts,
  snapAxis,
  snapHeading,
  spanRange,
  textChange,
  turnEdits,
  wrapHeading,
} from "../src/configdoc";
import { handlePoint, hitPart } from "../src/plan";
import type { FieldConfig, PlacedIssue, RobotConfig } from "../src/protocol";
import type { View } from "../src/view";

const ROBOT: RobotConfig = {
  body: { mass_kg: 6, footprint_in: [18, 18], cg_in: [0.5, 0, 4] },
  drivetrain: {
    type: "differential",
    wheels: [
      { name: "l", pos_in: [0, 7], type: "omni", diameter_in: 3.25 },
      { name: "r", pos_in: [0, -7], type: "omni", diameter_in: 3.25 },
    ],
    gearing: { left: { motors: [1], cartridge: "blue", wheels: ["l"] }, right: { motors: [2], cartridge: "blue", wheels: ["r"] } },
  },
  sensors: [
    { type: "imu", port: 4 },
    { type: "distance", port: 3, pos_in: [8.5, 0], heading_deg: 30 },
    { type: "rotation", port: 5, tracking_wheel: { pos_in: [0, 2], diameter_in: 2 } },
    { type: "rotation", port: 6 },
  ],
};

describe("the parts of a config", () => {
  it("lists a robot's wheels, sensors and center of gravity, with where each is written", () => {
    const parts = robotParts(ROBOT);
    expect(parts.map((p) => [p.path, p.kind, p.label])).toEqual([
      ["drivetrain.wheels[0]", "wheel", "l"],
      ["drivetrain.wheels[1]", "wheel", "r"],
      ["sensors[0]", "imu", "IMU 4"],
      ["sensors[1]", "distance", "D3"],
      ["sensors[2].tracking_wheel", "tracking", "R5"], // the rotation sensor that isn't a wheel: nothing
      ["body", "cg", "CG"],
    ]);
    const imu = parts[2];
    expect([imu.x, imu.y, imu.heading, imu.headingKey]).toEqual([0, 0, 0, "mount_yaw_deg"]); // defaults
    expect(parts[4].place).toBe("sensors[2]");
  });

  it("lists a field's elements; only rect obstacles turn", () => {
    const field: FieldConfig = {
      elements: [
        { type: "obstacle", shape: "rect", pos_in: [0, 0], size_in: [48, 3] },
        { type: "obstacle", name: "goal", shape: "circle", pos_in: [-48, 48], diameter_in: 10 },
        { type: "piece", pos_in: [24, 24], diameter_in: 7, mass_kg: 0.25 },
      ],
    };
    const parts = fieldParts(field);
    expect(parts.map((p) => [p.label, p.headingKey, p.size])).toEqual([
      ["obstacle 1", "heading_deg", 48],
      ["goal", null, 10],
      ["piece 3", null, 7],
    ]);
  });
});

describe("dragging a part", () => {
  it("snaps what moved, and keeps what didn't exactly as written", () => {
    expect(snapAxis(4.656207, 0.03, 0.125)).toBe(4.656207); // less than half a step: untouched
    expect(snapAxis(4.656207, 0.5, 0.125)).toBe(5.125);
    expect(snapAxis(-2.999773, -1.01, 0.125)).toBe(-4);
  });

  it("turns to the step, the short way into (-180, 180]", () => {
    expect(snapHeading(1, 1, 15)).toBe(45);
    expect(snapHeading(-1, -0.0001, 15)).toBe(180);
    expect(snapHeading(1, -0.0001, 15)).toBe(0); // not -0
    expect(wrapHeading(270)).toBe(-90);
    expect(wrapHeading(-180)).toBe(180);
  });

  it("writes positions and headings where the config keeps them", () => {
    const [, , imu, distance, , cg] = robotParts(ROBOT);
    expect(moveEdits(distance, 9, 1)).toEqual([{ location: "sensors[1].pos_in", value: [9, 1] }]);
    expect(turnEdits(imu, 90)).toEqual([{ location: "sensors[0].mount_yaw_deg", value: 90 }]);
    expect(moveEdits(cg, 1, 0)).toEqual([{ location: "body.cg_in", value: [1, 0, 4] }]); // its height kept
    expect(turnEdits(cg, 10)).toEqual([]);
  });

  it("knows which issues are about a part", () => {
    const parts = robotParts(ROBOT);
    const issue = (location: string): PlacedIssue => ({ severity: "error", location, message: "", span: null });
    const issues = [issue("sensors[1].pos_in"), issue("sensors[10].port"), issue("body.cg_in"), issue("sensors[2].port")];
    expect(issuesOf(parts[3], issues).map((i) => i.location)).toEqual(["sensors[1].pos_in"]);
    expect(issuesOf(parts[5], issues).map((i) => i.location)).toEqual(["body.cg_in"]);
    expect(issuesOf(parts[4], issues).map((i) => i.location)).toEqual(["sensors[2].port"]); // the tracking wheel's sensor
  });
});

describe("finding parts on the screen", () => {
  const view: View = { scale: 10, cx: 0, cy: 0, width: 400, height: 400 };
  const parts = robotParts(ROBOT);

  it("grabs the part under the pointer, the smallest when they overlap", () => {
    expect(hitPart(parts, view, 200 + 85, 200, null)?.part.label).toBe("D3"); // at (8.5, 0)
    expect(hitPart(parts, view, 200, 200, null)?.part.label).toBe("CG"); // the IMU is bigger
    expect(hitPart(parts, view, 20, 20, null)).toBeNull();
  });

  it("grabs a selected part's turn handle first", () => {
    const distance = parts[3];
    const [hx, hy] = handlePoint(distance, view)!;
    expect(hx).toBeGreaterThan(285); // ahead of it, at 30 degrees
    expect(hy).toBeLessThan(200);
    expect(hitPart(parts, view, hx, hy, "sensors[1]")).toEqual({ part: distance, turn: true });
    expect(hitPart(parts, view, hx, hy, null)?.turn ?? false).toBe(false);
    expect(handlePoint(parts[5], view)).toBeNull(); // the CG doesn't turn
  });
});

describe("text", () => {
  const text = "a: 1\nbb: [2, 3]  # two\n";

  it("turns a line and column span into offsets", () => {
    expect(spanRange(text, { line: 2, column: 5, end_line: 2, end_column: 11 })).toEqual({ from: 9, to: 15 });
    expect(text.slice(9, 15)).toBe("[2, 3]");
    expect(spanRange(text, { line: 9, column: 1, end_line: 9, end_column: 1 }).from).toBeLessThanOrEqual(text.length);
  });

  it("finds the part written at a line", () => {
    const parts = robotParts(ROBOT);
    const places = { "sensors[1]": { line: 3, column: 3, end_line: 3, end_column: 40 } };
    expect(partAtLine(parts, places, 3)?.label).toBe("D3");
    expect(partAtLine(parts, places, 4)).toBeNull();
  });

  it("makes a patch one change, keeping what's the same at both ends", () => {
    expect(textChange(text, text)).toBeNull();
    const after = text.replace("[2, 3]", "[2.5, 3]");
    expect(textChange(text, after)).toEqual({ from: 11, to: 11, insert: ".5" }); // after the 2
    expect(textChange("abc", "")).toEqual({ from: 0, to: 3, insert: "" });
    expect(textChange("aaa", "aa")).toEqual({ from: 2, to: 3, insert: "" });
  });
});

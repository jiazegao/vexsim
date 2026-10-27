// A robot or field config in the editor: the parts its diagram draws and lets you drag,
// what a drag writes into the YAML, and where the server's issues and places are in the
// text. The text stays the source of truth: the server rewrites numbers in place.

import type { ConfigEdit, FieldConfig, PlacedIssue, RobotConfig, TextSpan } from "./protocol";

export type PartKind = "wheel" | "tracking" | "distance" | "imu" | "gps" | "cg" | "obstacle" | "piece";

/** Something the diagram draws that can be dragged (and maybe turned). */
export interface Part {
  path: string; // where it's written: "sensors[1]", "drivetrain.wheels[0]", "elements[3]", "body"
  place: string; // the key of its place in the text (ConfigCheck.places)
  kind: PartKind;
  label: string;
  x: number; // inches: the robot's frame (+x forward) or the field's
  y: number;
  heading: number | null; // degrees, counter-clockwise from +x; null if it can't be turned
  positionKey: string; // where its x and y are written, under `path`
  headingKey: string | null;
  extra: number[]; // numbers written after x and y in the same list (the CG's height)
  size: number; // inches across, for drawing and grabbing
}

/** The parts of a robot that can be dragged: wheels, sensors, its center of gravity. */
export function robotParts(robot: RobotConfig): Part[] {
  const parts: Part[] = robot.drivetrain.wheels.map((wheel, i) => ({
    path: `drivetrain.wheels[${i}]`,
    place: `drivetrain.wheels[${i}]`,
    kind: "wheel",
    label: wheel.name,
    x: wheel.pos_in[0],
    y: wheel.pos_in[1],
    heading: wheel.heading_deg ?? 0,
    positionKey: "pos_in",
    headingKey: "heading_deg",
    extra: [],
    size: wheel.diameter_in,
  }));
  (robot.sensors ?? []).forEach((sensor, i) => {
    const path = `sensors[${i}]`;
    if (sensor.type === "rotation") {
      const wheel = sensor.tracking_wheel;
      if (!wheel) return; // not a tracking wheel: nothing to place
      parts.push({
        path: `${path}.tracking_wheel`,
        place: path,
        kind: "tracking",
        label: `R${sensor.port}`,
        x: wheel.pos_in[0],
        y: wheel.pos_in[1],
        heading: wheel.heading_deg ?? 0,
        positionKey: "pos_in",
        headingKey: "heading_deg",
        extra: [],
        size: wheel.diameter_in,
      });
      return;
    }
    const position = sensor.pos_in ?? [0, 0];
    const turned = sensor.type === "distance" ? "heading_deg" : "mount_yaw_deg";
    const heading = sensor.type === "distance" ? sensor.heading_deg : sensor.mount_yaw_deg;
    parts.push({
      path,
      place: path,
      kind: sensor.type,
      label: sensor.type === "distance" ? `D${sensor.port}` : `${sensor.type.toUpperCase()} ${sensor.port}`,
      x: position[0],
      y: position[1],
      heading: heading ?? 0,
      positionKey: "pos_in",
      headingKey: turned,
      extra: [],
      size: sensor.type === "distance" ? 1 : 1.5,
    });
  });
  const [cx, cy, cz] = robot.body.cg_in;
  parts.push({
    path: "body",
    place: "body.cg_in",
    kind: "cg",
    label: "CG",
    x: cx,
    y: cy,
    heading: null,
    positionKey: "cg_in",
    headingKey: null,
    extra: [cz],
    size: 1.2,
  });
  return parts;
}

/** The elements of a field: obstacles (rects turn) and pieces. */
export function fieldParts(field: FieldConfig): Part[] {
  return (field.elements ?? []).map((element, i) => {
    const path = `elements[${i}]`;
    const name = element.name ?? `${element.type} ${i + 1}`;
    if (element.type === "piece") {
      return {
        path,
        place: path,
        kind: "piece",
        label: name,
        x: element.pos_in[0],
        y: element.pos_in[1],
        heading: null,
        positionKey: "pos_in",
        headingKey: null,
        extra: [],
        size: element.diameter_in,
      };
    }
    const rect = element.shape === "rect";
    const [length, width] = element.size_in ?? [0, 0];
    return {
      path,
      place: path,
      kind: "obstacle",
      label: name,
      x: element.pos_in[0],
      y: element.pos_in[1],
      heading: rect ? (element.heading_deg ?? 0) : null,
      positionKey: "pos_in",
      headingKey: rect ? "heading_deg" : null,
      extra: [],
      size: rect ? Math.max(length, width) : (element.diameter_in ?? 1),
    };
  });
}

// --- dragging --------------------------------------------------------------------------------

/** Steps a drag snaps to: inches, degrees; and finer ones while Shift is held. */
export interface Steps {
  move: number;
  fineMove: number;
  turn: number;
  fineTurn: number;
}

export const ROBOT_STEPS: Steps = { move: 0.125, fineMove: 0.01, turn: 15, fineTurn: 1 };
export const FIELD_STEPS: Steps = { move: 0.5, fineMove: 0.1, turn: 15, fineTurn: 1 };

function round(value: number, step: number): number {
  return Number((Math.round(value / step) * step).toFixed(6));
}

/** One coordinate after a drag of `delta`: a coordinate the drag didn't really move (less
 * than half a step) keeps its exact value, so measured numbers survive a drag along the
 * other axis; a moved one lands on the step. */
export function snapAxis(start: number, delta: number, step: number): number {
  return Math.abs(delta) < step / 2 ? start : round(start + delta, step);
}

/** An angle in (-180, 180]. */
export function wrapHeading(degrees: number): number {
  const wrapped = Number((((((degrees + 180) % 360) + 360) % 360) - 180).toFixed(6));
  return wrapped === -180 ? 180 : wrapped === 0 ? 0 : wrapped; // and never -0
}

/** The heading from a part's center to the pointer, on the step. */
export function snapHeading(dx: number, dy: number, step: number): number {
  return wrapHeading(round((Math.atan2(dy, dx) * 180) / Math.PI, step));
}

/** What moving a part to (x, y) writes. */
export function moveEdits(part: Part, x: number, y: number): ConfigEdit[] {
  return [{ location: `${part.path}.${part.positionKey}`, value: [x, y, ...part.extra] }];
}

/** What turning a part to `heading` writes. */
export function turnEdits(part: Part, heading: number): ConfigEdit[] {
  return part.headingKey ? [{ location: `${part.path}.${part.headingKey}`, value: heading }] : [];
}

/** The issues about a part (at it, or anywhere inside it). */
export function issuesOf(part: Part, issues: PlacedIssue[]): PlacedIssue[] {
  const roots = part.kind === "cg" ? ["body.cg_in"] : part.kind === "tracking" ? [part.place] : [part.path];
  return issues.filter((issue) => roots.some((root) => issue.location === root || issue.location.startsWith(`${root}.`)));
}

/** The part whose text holds line `line` (1-based), if any. */
export function partAtLine(parts: Part[], places: Record<string, TextSpan>, line: number): Part | null {
  for (const part of parts) {
    const span = places[part.place];
    if (span && span.line <= line && line <= span.end_line) return part;
  }
  return null;
}

// --- text ------------------------------------------------------------------------------------

/** A 1-based line/column span as offsets into `text`, at least one character long. */
export function spanRange(text: string, span: TextSpan): { from: number; to: number } {
  const starts = [0];
  for (let i = text.indexOf("\n"); i >= 0; i = text.indexOf("\n", i + 1)) starts.push(i + 1);
  const offset = (line: number, column: number) => {
    const start = starts[Math.min(Math.max(line, 1), starts.length) - 1];
    const end = line < starts.length ? starts[line] - 1 : text.length;
    return Math.min(start + Math.max(column, 1) - 1, end);
  };
  const from = offset(span.line, span.column);
  let to = offset(span.end_line, span.end_column);
  if (to <= from) to = Math.min(text.length, from + 1);
  return { from, to: Math.max(to, from) };
}

/** The one change that turns `before` into `after` (their common start and end kept), or
 * null if they're the same: so applying a patch is one undoable step in the editor. */
export function textChange(before: string, after: string): { from: number; to: number; insert: string } | null {
  if (before === after) return null;
  let start = 0;
  const shorter = Math.min(before.length, after.length);
  while (start < shorter && before[start] === after[start]) start++;
  let end = 0;
  while (end < shorter - start && before[before.length - 1 - end] === after[after.length - 1 - end]) end++;
  return { from: start, to: before.length - end, insert: after.slice(start, after.length - end) };
}

/** A config's file name, for its tab. */
export function fileName(path: string): string {
  return path.split("/").pop() || path;
}

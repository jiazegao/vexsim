// The Design view's logic: where a new robot's file goes, the drive presets, and the edits
// its drawing tools and forms make to a robot config. Everything is in the robot's frame,
// inches and degrees; edits go through the server, which writes them into the YAML in
// place (vexsim/app/yamledit.py), so the text and its comments stay the source of truth.

import type { BodyConfig, CirclePart, ConfigEdit, OutlinePart, RectPart, RobotConfig, WheelConfig } from "./protocol";

export type ShapePart = RectPart | CirclePart | OutlinePart;

/** The drivetrains a robot can start on, or have put on it (vexsim/app/newrobot.py). */
export const DRIVE_PRESETS: readonly (readonly [string, string])[] = [
  ["tank4", "4-motor tank drive"],
  ["tank6", "6-motor tank drive"],
  ["xdrive", "4-motor X-drive"],
  ["mecanum", "4-motor mecanum drive"],
  ["hdrive", "5-motor H-drive"],
];

// --- a new robot's file ----------------------------------------------------------------------

/** A robot's file name from its name, as the server makes it: `Test bot #2` -> `test_bot_2`. */
export function fileStem(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "robot"
  );
}

/** Where new robots go: the folder that has the most robot configs already (the nearer the
 * top, the better, then by name), or `robots` in a workspace that has none. */
export function robotFolder(robots: readonly string[]): string {
  const counts = new Map<string, number>();
  for (const path of robots) {
    const folder = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
    counts.set(folder, (counts.get(folder) ?? 0) + 1);
  }
  const ranked = [...counts].sort(([a, n], [b, m]) => m - n || a.split("/").length - b.split("/").length || a.localeCompare(b));
  return ranked.length ? ranked[0][0] : "robots";
}

/** A path for a new robot named `name`, in `folder`, that no file in `taken` has. */
export function newRobotPath(folder: string, name: string, taken: readonly string[]): string {
  const stem = fileStem(name);
  const prefix = folder ? `${folder}/` : "";
  const used = new Set(taken);
  for (let n = 1; ; n++) {
    const path = `${prefix}${stem}${n === 1 ? "" : `_${n}`}.yaml`;
    if (!used.has(path)) return path;
  }
}

// --- the robot's shape -----------------------------------------------------------------------

const DEG = Math.PI / 180;

/** The parts the Design view draws and edits: the robot's `body.shape`, or for a robot with a
 * footprint, that rectangle (the first change to the shape turns it into a shape part). */
export function shapeOf(body: BodyConfig): ShapePart[] {
  if (body.shape?.length) return body.shape;
  const [length, width] = body.footprint_in ?? [15, 15];
  return [{ type: "rect", pos_in: [0, 0], size_in: [length, width], heading_deg: 0 }];
}

/** Whether the robot's body is a footprint rectangle rather than a shape. */
export function isFootprint(body: BodyConfig): boolean {
  return !body.shape?.length;
}

/** `value` to the nearest multiple of `step` (never -0; six decimals at most). */
export function snapTo(value: number, step: number): number {
  const snapped = step > 0 ? Math.round(value / step) * step : value;
  const tidy = Number(snapped.toFixed(6));
  return tidy === 0 ? 0 : tidy;
}

/** The edits that make the shape `parts`, part by part: `index` changed to `part` (null:
 * removed), or `part` added when `index` is null. A footprint robot becomes a shape robot:
 * its rectangle is the first part. */
export function partEdits(robot: RobotConfig, index: number | null, part: ShapePart | null): ConfigEdit[] {
  const body = robot.body;
  if (isFootprint(body)) {
    const parts = shapeOf(body).map((p) => ({ ...p }));
    if (index === null && part) parts.push(part);
    else if (index !== null && part) parts[index] = part;
    else if (index !== null) parts.splice(index, 1);
    return [
      { location: "body.footprint_in", op: "remove" },
      { location: "body.shape", op: "set", value: parts.map(written) },
    ];
  }
  if (index === null) return part ? [{ location: "body.shape", op: "add", value: written(part) }] : [];
  if (!part) return [{ location: `body.shape[${index}]`, op: "remove" }];
  return changedKeys(body.shape![index], part).map((key) => ({ location: `body.shape[${index}].${key}`, op: "set", value: written(part)[key as keyof ShapePart] }));
}

/** A part as it's written: its type first, nothing that's at its default. */
export function written(part: ShapePart): Record<string, unknown> {
  if (part.type === "outline") return { type: "outline", points_in: part.points_in.map(([x, y]) => [tidy(x), tidy(y)]) };
  const out: Record<string, unknown> = { type: part.type };
  const [x, y] = part.pos_in ?? [0, 0];
  if (x !== 0 || y !== 0) out.pos_in = [tidy(x), tidy(y)];
  if (part.type === "rect") {
    out.size_in = [tidy(part.size_in[0]), tidy(part.size_in[1])];
    if (part.heading_deg) out.heading_deg = tidy(part.heading_deg);
  } else out.diameter_in = tidy(part.diameter_in);
  return out;
}

function tidy(value: number): number {
  return snapTo(value, 0);
}

/** The keys whose written values differ between two versions of a part. */
function changedKeys(before: ShapePart, after: ShapePart): string[] {
  const a = written(before);
  const b = written(after);
  if (a.type !== b.type) return Object.keys(b);
  return [...new Set([...Object.keys(a), ...Object.keys(b)])].filter((key) => JSON.stringify(a[key] ?? defaults(after)[key]) !== JSON.stringify(b[key] ?? defaults(after)[key]));
}

function defaults(part: ShapePart): Record<string, unknown> {
  return part.type === "outline" ? {} : part.type === "rect" ? { pos_in: [0, 0], heading_deg: 0 } : { pos_in: [0, 0] };
}

/** A part moved by (dx, dy). */
export function movedPart(part: ShapePart, dx: number, dy: number): ShapePart {
  if (part.type === "outline") return { ...part, points_in: part.points_in.map(([x, y]) => [x + dx, y + dy] as [number, number]) };
  const [x, y] = part.pos_in ?? [0, 0];
  return { ...part, pos_in: [x + dx, y + dy] };
}

/** A part's mirror image across the robot's center line (y = 0), or null if it is its own. */
export function mirroredPart(part: ShapePart): ShapePart | null {
  let mirror: ShapePart;
  if (part.type === "outline") mirror = { ...part, points_in: [...part.points_in].reverse().map(([x, y]) => [x, -y] as [number, number]) };
  else {
    const [x, y] = part.pos_in ?? [0, 0];
    mirror = part.type === "rect" ? { ...part, pos_in: [x, -y], heading_deg: -(part.heading_deg ?? 0) } : { ...part, pos_in: [x, -y] };
  }
  const same = (a: ShapePart, b: ShapePart) => {
    const points = (p: ShapePart) => (p.type === "outline" ? [...p.points_in].map(([x, y]) => `${tidy(x)},${tidy(y)}`).sort() : [JSON.stringify(written(p))]);
    return JSON.stringify(points(a)) === JSON.stringify(points(b));
  };
  return same(part, mirror) ? null : mirror;
}

/** The corners of a rectangle part, counter-clockwise from front-left (x+, y+). */
export function rectCorners(part: RectPart): [number, number][] {
  const [cx, cy] = part.pos_in ?? [0, 0];
  const [hx, hy] = [part.size_in[0] / 2, part.size_in[1] / 2];
  const c = Math.cos((part.heading_deg ?? 0) * DEG);
  const s = Math.sin((part.heading_deg ?? 0) * DEG);
  return [
    [hx, hy],
    [-hx, hy],
    [-hx, -hy],
    [hx, -hy],
  ].map(([u, v]) => [cx + c * u - s * v, cy + s * u + c * v]);
}

/** Whether a point is on a part (within `slop` inches of it). */
export function partContains(part: ShapePart, x: number, y: number, slop = 0): boolean {
  if (part.type === "circle") {
    const [cx, cy] = part.pos_in ?? [0, 0];
    return Math.hypot(x - cx, y - cy) <= part.diameter_in / 2 + slop;
  }
  if (part.type === "rect") {
    const [cx, cy] = part.pos_in ?? [0, 0];
    const c = Math.cos((part.heading_deg ?? 0) * DEG);
    const s = Math.sin((part.heading_deg ?? 0) * DEG);
    const u = c * (x - cx) + s * (y - cy);
    const v = -s * (x - cx) + c * (y - cy);
    return Math.abs(u) <= part.size_in[0] / 2 + slop && Math.abs(v) <= part.size_in[1] / 2 + slop;
  }
  const points = part.points_in;
  let inside = false;
  points.forEach(([x0, y0], i) => {
    const [x1, y1] = points[(i + 1) % points.length];
    if (y0 > y !== y1 > y && x < x0 + ((y - y0) * (x1 - x0)) / (y1 - y0)) inside = !inside;
  });
  if (inside || slop <= 0) return inside;
  return points.some(([x0, y0], i) => {
    const [x1, y1] = points[(i + 1) % points.length];
    const dx = x1 - x0;
    const dy = y1 - y0;
    const t = Math.max(0, Math.min(1, ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy || 1)));
    return Math.hypot(x - x0 - t * dx, y - y0 - t * dy) <= slop;
  });
}

/** The topmost part at a point (the last drawn), if any. */
export function partAt(parts: readonly ShapePart[], x: number, y: number, slop = 0): number | null {
  for (let i = parts.length - 1; i >= 0; i--) if (partContains(parts[i], x, y, slop)) return i;
  return null;
}

/** A part's handles, which reshape it: a rectangle's corners, a circle's rim (on its right),
 * an outline's points. */
export function handlesOf(part: ShapePart): [number, number][] {
  if (part.type === "rect") return rectCorners(part);
  if (part.type === "circle") {
    const [cx, cy] = part.pos_in ?? [0, 0];
    return [[cx + part.diameter_in / 2, cy]];
  }
  return part.points_in.map(([x, y]) => [x, y]);
}

/** A part with handle `handle` dragged to (x, y), sizes and places on `step`: a rectangle's
 * opposite corner stays put; a circle keeps its center; an outline's other points stay. */
export function reshaped(part: ShapePart, handle: number, x: number, y: number, step: number): ShapePart {
  if (part.type === "circle") {
    const [cx, cy] = part.pos_in ?? [0, 0];
    return { ...part, diameter_in: Math.max(step, snapTo(2 * Math.hypot(x - cx, y - cy), step)) };
  }
  if (part.type === "outline") {
    const points = part.points_in.map((p, i) => (i === handle ? ([snapTo(x, step), snapTo(y, step)] as [number, number]) : p));
    return { ...part, points_in: points };
  }
  const corners = rectCorners(part);
  const [fx, fy] = corners[(handle + 2) % 4]; // stays put
  const h = (part.heading_deg ?? 0) * DEG;
  const c = Math.cos(h);
  const s = Math.sin(h);
  // the dragged corner in the rectangle's own frame, from the fixed one
  const u = c * (x - fx) + s * (y - fy);
  const v = -s * (x - fx) + c * (y - fy);
  const length = Math.max(step, snapTo(Math.abs(u), step));
  const width = Math.max(step, snapTo(Math.abs(v), step));
  const su = (Math.sign(u) || 1) * length;
  const sv = (Math.sign(v) || 1) * width;
  const cx = fx + c * (su / 2) - s * (sv / 2);
  const cy = fy + s * (su / 2) + c * (sv / 2);
  return { ...part, pos_in: [snapTo(cx, step / 2), snapTo(cy, step / 2)], size_in: [length, width] };
}

/** A rectangle part between two corners, or null if it has no area. */
export function rectBetween(a: [number, number], b: [number, number]): RectPart | null {
  const length = Math.abs(b[0] - a[0]);
  const width = Math.abs(b[1] - a[1]);
  if (length <= 0 || width <= 0) return null;
  return { type: "rect", pos_in: [tidy((a[0] + b[0]) / 2), tidy((a[1] + b[1]) / 2)], size_in: [tidy(length), tidy(width)], heading_deg: 0 };
}

/** A circle part around `center` reaching `edge`, or null if it has no size. */
export function circleTo(center: [number, number], edge: [number, number], step: number): CirclePart | null {
  const diameter = snapTo(2 * Math.hypot(edge[0] - center[0], edge[1] - center[1]), step);
  return diameter > 0 ? { type: "circle", pos_in: center, diameter_in: diameter } : null;
}

/** What's wrong with an outline's points, if anything (the server checks too): fewer than
 * three, or edges that cross. */
export function outlineProblem(points: readonly [number, number][]): string | null {
  if (points.length < 3) return "an outline needs three points or more";
  const n = points.length;
  const cross = (a: [number, number], b: [number, number], c: [number, number]) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  for (let i = 0; i < n; i++) {
    for (let j = i + 2; j < n; j++) {
      if (i === 0 && j === n - 1) continue; // neighbours
      const [a, b] = [points[i], points[(i + 1) % n]];
      const [c, d] = [points[j], points[(j + 1) % n]];
      const d1 = cross(a, b, c);
      const d2 = cross(a, b, d);
      const d3 = cross(c, d, a);
      const d4 = cross(c, d, b);
      if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))) return "its edges cross";
    }
  }
  return null;
}

// --- ports, names and new things -------------------------------------------------------------

export const PORTS = 21;

/** Something on a port: a drive motor (of a motor group), a mechanism's motor, a sensor. */
export interface PortUser {
  name: string; // the motor group's or mechanism's name, or the sensor's kind
  kind: "drive" | "mechanism" | "sensor";
  reversed: boolean;
}

/** A port's user in words: "left drive motor, reversed". */
export function describeUser(user: PortUser): string {
  const what = user.kind === "drive" ? `${user.name} drive motor` : user.kind === "mechanism" ? `${user.name} motor` : user.name;
  return user.reversed ? `${what}, reversed` : what;
}

/** What's on each port: drive motors (by motor group), mechanism motors, sensors. */
export function portMap(robot: RobotConfig): Map<number, PortUser[]> {
  const map = new Map<number, PortUser[]>();
  const put = (port: number, user: PortUser) => map.set(Math.abs(port), [...(map.get(Math.abs(port)) ?? []), user]);
  for (const [name, group] of Object.entries(robot.drivetrain.gearing)) for (const port of group.motors) put(port, { name, kind: "drive", reversed: port < 0 });
  for (const [name, mechanism] of Object.entries(robot.mechanisms ?? {})) for (const port of mechanism.motors) put(port, { name, kind: "mechanism", reversed: port < 0 });
  for (const sensor of robot.sensors ?? []) put(sensor.port, { name: sensorName(sensor.type), kind: "sensor", reversed: false });
  return map;
}

/** The ports nothing uses yet, lowest first. */
export function freePorts(robot: RobotConfig): number[] {
  const used = portMap(robot);
  return Array.from({ length: PORTS }, (_, i) => i + 1).filter((port) => !used.has(port));
}

export function sensorName(type: string): string {
  return { imu: "IMU", rotation: "rotation sensor", distance: "distance sensor", gps: "GPS" }[type] ?? type;
}

/** `base` with a number after it that no name in `taken` has (`base` itself if free). */
export function uniqueName(base: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  if (!used.has(base)) return base;
  for (let n = 2; ; n++) if (!used.has(`${base}${n}`)) return `${base}${n}`;
}

/** Where the robot's front is: where its +x axis leaves its body (not the tip of a clamp's
 * jaw beside the axis), or if the axis misses it, the furthest forward it reaches. */
export function frontOf(body: BodyConfig): number {
  const parts = shapeOf(body);
  const spans = parts.flatMap((part) => onAxis(part)).sort((a, b) => a[0] - b[0]);
  let reach: number | null = null; // the end of the run of spans the origin is in
  for (const [from, to] of spans) {
    if (reach === null ? from <= 0 && to >= 0 : from <= reach) reach = Math.max(reach ?? to, to);
  }
  if (reach !== null) return reach;
  return Math.max(...parts.flatMap((part) => (part.type === "outline" ? part.points_in.map(([x]) => x) : part.type === "rect" ? rectCorners(part).map(([x]) => x) : [(part.pos_in?.[0] ?? 0) + part.diameter_in / 2])));
}

/** Where a part crosses the robot's x axis (y = 0): the spans of x it covers there. */
function onAxis(part: ShapePart): [number, number][] {
  const edges = (points: [number, number][]) => {
    const xs: number[] = [];
    points.forEach(([x0, y0], i) => {
      const [x1, y1] = points[(i + 1) % points.length];
      if (y0 > 0 !== y1 > 0) xs.push(x0 + ((0 - y0) * (x1 - x0)) / (y1 - y0));
    });
    xs.sort((a, b) => a - b);
    const spans: [number, number][] = [];
    for (let i = 0; i + 1 < xs.length; i += 2) spans.push([xs[i], xs[i + 1]]);
    return spans;
  };
  if (part.type === "circle") {
    const [cx, cy] = part.pos_in ?? [0, 0];
    const r = part.diameter_in / 2;
    if (Math.abs(cy) > r) return [];
    const half = Math.sqrt(r * r - cy * cy);
    return [[cx - half, cx + half]];
  }
  return edges(part.type === "rect" ? rectCorners(part) : part.points_in);
}

/** A sensor of a type, on a free port, somewhere sensible: an IMU near the middle, a distance
 * sensor at the front looking ahead, a tracking wheel beside the middle, a GPS behind it. */
export function newSensor(robot: RobotConfig, type: "imu" | "rotation" | "distance" | "gps"): Record<string, unknown> {
  const port = freePorts(robot)[0] ?? 1;
  if (type === "imu") return { type, port, pos_in: [-2, 2] }; // near the middle, beside the CG
  if (type === "distance") return { type, port, pos_in: [snapTo(frontOf(robot.body) - 0.5, 0.125), 0], heading_deg: 0 };
  if (type === "gps") return { type, port, pos_in: [-3, -2], mount_yaw_deg: 180 };
  const sideways = (robot.sensors ?? []).some((s) => s.type === "rotation" && s.tracking_wheel && (s.tracking_wheel.heading_deg ?? 0) === 0);
  const wheel = sideways ? { pos_in: [-2, 0], heading_deg: 90, diameter_in: 2 } : { pos_in: [0, -1.5], heading_deg: 0, diameter_in: 2 };
  return { type, port, tracking_wheel: wheel };
}

/** Renaming a wheel: its name, and every gear group's list that has it. */
export function renameWheelEdits(robot: RobotConfig, index: number, name: string): ConfigEdit[] {
  const old = robot.drivetrain.wheels[index].name;
  const edits: ConfigEdit[] = [{ location: `drivetrain.wheels[${index}].name`, op: "set", value: name }];
  for (const [group, gear] of Object.entries(robot.drivetrain.gearing)) {
    if (gear.wheels.includes(old)) edits.push({ location: `drivetrain.gearing.${group}.wheels`, op: "set", value: gear.wheels.map((w) => (w === old ? name : w)) });
  }
  return edits;
}

/** Taking a wheel away: it, and it from every gear group's list. */
export function removeWheelEdits(robot: RobotConfig, index: number): ConfigEdit[] {
  const old = robot.drivetrain.wheels[index].name;
  const edits: ConfigEdit[] = [{ location: `drivetrain.wheels[${index}]`, op: "remove" }];
  for (const [group, gear] of Object.entries(robot.drivetrain.gearing)) {
    if (!gear.wheels.includes(old)) continue;
    edits.push({ location: `drivetrain.gearing.${group}.wheels`, op: "set", value: gear.wheels.filter((w) => w !== old) });
  }
  return edits;
}

/** Motor ports as typed: "1, 2, -3" (negative: reversed). Null if they don't read. */
export function readPorts(text: string): number[] | null {
  const parts = text.split(/[\s,]+/).filter(Boolean);
  const ports = parts.map(Number);
  return ports.length && ports.every((p) => Number.isInteger(p) && p !== 0 && Math.abs(p) <= PORTS) ? ports : null;
}

/** A gear ratio as typed: "36:48" stays words, "0.75" a number. Null if it doesn't read. */
export function readRatio(text: string): string | number | null {
  const trimmed = text.trim();
  const teeth = trimmed.match(/^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$/);
  if (teeth && Number(teeth[1]) > 0 && Number(teeth[2]) > 0) return `${teeth[1]}:${teeth[2]}`;
  const value = Number(trimmed);
  return trimmed && Number.isFinite(value) && value > 0 ? value : null;
}

/** What a name in a config can be (a wheel's, a motor group's, a mechanism's): letters,
 * digits and _, not starting with a digit. The reason it can't, or null. */
export function nameProblem(name: string, taken: Iterable<string> = []): string | null {
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) return `"${name}" can't be a name: use letters, digits and _ (not a digit first)`;
  if ([...taken].includes(name)) return `there's already a "${name}"`;
  return null;
}

/** A number as a form shows it: no more than six decimals, no trailing zeros. */
export function shown(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(Number(value.toFixed(6)));
}

/** A part of the shape in a few words: "Rectangle 15 × 15 in at 0, 0". */
export function describePart(part: ShapePart): string {
  if (part.type === "outline") return `Outline of ${part.points_in.length} points`;
  const [x, y] = part.pos_in ?? [0, 0];
  const at = `at ${shown(x)}, ${shown(y)}`;
  if (part.type === "circle") return `Circle ⌀ ${shown(part.diameter_in)} in ${at}`;
  const turned = part.heading_deg ? `, turned ${shown(part.heading_deg)}°` : "";
  return `Rectangle ${shown(part.size_in[0])} × ${shown(part.size_in[1])} in ${at}${turned}`;
}

export const CARTRIDGE_RPM: Record<string, number> = { red: 100, green: 200, blue: 600 };

/** A gear ratio's value: the output's speed over the motor's ("36:48" is 0.75). */
export function ratioValue(ratio: string | number | null | undefined): number {
  if (ratio === null || ratio === undefined) return 1;
  if (typeof ratio === "number") return ratio;
  const [driving, driven] = ratio.split(":").map(Number);
  return driven ? driving / driven : Number(ratio);
}

/** A wheel's type changed: a mecanum wheel gets its rollers' angle (-45 at the front left
 * and back right, 45 at the others), and a wheel that stops being one loses it. */
export function wheelTypeEdits(robot: RobotConfig, index: number, type: WheelConfig["type"]): ConfigEdit[] {
  const wheel = robot.drivetrain.wheels[index];
  const at = `drivetrain.wheels[${index}]`;
  const edits: ConfigEdit[] = [{ location: `${at}.type`, op: "set", value: type }];
  if (type === "mecanum" && wheel.roller_angle_deg == null) {
    const [x, y] = wheel.pos_in;
    edits.push({ location: `${at}.roller_angle_deg`, op: "set", value: x * y >= 0 ? -45 : 45 });
  } else if (type !== "mecanum" && wheel.roller_angle_deg != null) {
    edits.push({ location: `${at}.roller_angle_deg`, op: "remove" });
  }
  return edits;
}

/** A new wheel, in the middle of the robot (to drag where it goes), not yet driven. */
export function newWheel(robot: RobotConfig): Record<string, unknown> {
  const name = uniqueName("wheel", robot.drivetrain.wheels.map((w) => w.name));
  const like = robot.drivetrain.wheels[robot.drivetrain.wheels.length - 1];
  return { name, pos_in: [0, 0], type: like?.type === "traction" ? "traction" : "omni", diameter_in: like?.diameter_in ?? 3.25 };
}

/** A new motor group: one motor on a free port, driving the wheels no group drives yet (or
 * the first wheel). */
export function newGroup(robot: RobotConfig): [string, Record<string, unknown>] {
  const name = uniqueName("group", Object.keys(robot.drivetrain.gearing));
  const driven = new Set(Object.values(robot.drivetrain.gearing).flatMap((g) => g.wheels));
  const loose = robot.drivetrain.wheels.map((w) => w.name).filter((w) => !driven.has(w));
  const wheels = loose.length ? loose : [robot.drivetrain.wheels[0].name];
  return [name, { motors: [freePorts(robot)[0] ?? 1], cartridge: "blue", wheels }];
}

/** A new mechanism: one green-cartridge motor on a free port. */
export function newMechanism(robot: RobotConfig): [string, Record<string, unknown>] {
  const name = uniqueName("mechanism", Object.keys(robot.mechanisms ?? {}));
  return [name, { motors: [freePorts(robot)[0] ?? 1], cartridge: "green" }];
}

// --- copy and paste ----------------------------------------------------------------------------

/** A part of a robot copied with Ctrl+C on its diagram: a part of its shape, a wheel or a
 * sensor, as it's written, to paste into this robot or another one open beside it. */
export interface Copied {
  kind: "shape" | "wheel" | "sensor";
  value: Record<string, unknown>;
  groups: string[]; // a wheel's motor groups: its copy goes in those the robot has
  label: string; // what it is, in a few words
  pastes: number; // how many copies have been pasted: each lands a step further along
}

/** Where each copy lands from the part it's a copy of: right of it and below, inches. */
export const PASTE_STEP: readonly [number, number] = [1, -1];

let copied: Copied | null = null; // one for the page: a part copied in one robot pastes into another

export function copyPart(part: Copied): void {
  copied = part;
}

export function copiedPart(): Copied | null {
  return copied;
}

const PART_NAMES = { rect: "rectangle", circle: "circle", outline: "outline" } as const;
const WHEEL_DEFAULTS = { heading_deg: 0, drop_in: 0 };
const SENSOR_DEFAULTS: Record<string, Record<string, unknown>> = {
  imu: { pos_in: [0, 0], mount_yaw_deg: 0, noise: "default" },
  rotation: { reversed: false, noise: "default" },
  distance: { heading_deg: 0, noise: "default" },
  gps: { mount_yaw_deg: 0, noise: "default" },
};

/** A config's part without what's at its default (the server sends every field). */
function plain(value: object, defaults: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(value).filter(([key, v]) => v !== null && v !== undefined && JSON.stringify(v) !== JSON.stringify(defaults[key])));
}

/** What's selected, to copy: the selected part of the shape, or the wheel or sensor selected
 * on the diagram (`selected`, its path). Null if nothing is; a reason if it can't be. */
export function copyOf(robot: RobotConfig, shapePart: number | null, selected: string | null): Copied | string | null {
  const part = shapePart === null ? undefined : shapeOf(robot.body)[shapePart];
  if (part) return { kind: "shape", value: written(part), groups: [], label: `the ${PART_NAMES[part.type]}`, pastes: 0 };
  if (selected === "body") return "The center of gravity can't be copied: a robot has just the one.";
  const wheel = selected && /^drivetrain\.wheels\[(\d+)\]$/.exec(selected);
  if (wheel) {
    const found = robot.drivetrain.wheels[Number(wheel[1])];
    if (!found) return null;
    const groups = Object.entries(robot.drivetrain.gearing).filter(([, g]) => g.wheels.includes(found.name));
    return { kind: "wheel", value: plain(found, WHEEL_DEFAULTS), groups: groups.map(([name]) => name), label: `wheel ${found.name}`, pastes: 0 };
  }
  const sensor = selected && /^sensors\[(\d+)\]/.exec(selected);
  if (sensor) {
    const found = (robot.sensors ?? [])[Number(sensor[1])];
    if (!found) return null;
    const value = plain(found, SENSOR_DEFAULTS[found.type] ?? {});
    if (found.type === "rotation" && found.tracking_wheel) value.tracking_wheel = plain(found.tracking_wheel, { heading_deg: 0 });
    return { kind: "sensor", value, groups: [], label: `the ${sensorName(found.type)} on port ${found.port}`, pastes: 0 };
  }
  return null;
}

/** A copy pasted into `robot`: the edits that add it, a step further along than the last
 * copy, and what to select once it's there (a part of the shape, or the path of a wheel or
 * sensor). A wheel takes its name if no wheel has it (else the next free number) and joins
 * the motor groups its original was in, where the robot has them; a sensor keeps its port if
 * it's free, else takes the first free one. */
export function pasteEdits(robot: RobotConfig, copy: Copied): { edits: ConfigEdit[]; part: number | null; path: string | null; label: string } {
  const along = copy.pastes + 1;
  const [dx, dy] = [PASTE_STEP[0] * along, PASTE_STEP[1] * along];
  const shift = (point: unknown): [number, number] => {
    const [x, y] = (point as [number, number] | undefined) ?? [0, 0];
    return [tidy(x + dx), tidy(y + dy)];
  };
  if (copy.kind === "shape") {
    const part = movedPart(copy.value as unknown as ShapePart, dx, dy);
    const edits = partEdits(robot, null, part);
    return { edits, part: shapeOf(robot.body).length, path: null, label: `a copy of ${copy.label}` };
  }
  if (copy.kind === "wheel") {
    const names = robot.drivetrain.wheels.map((w) => w.name);
    const original = String(copy.value.name);
    const base = original.replace(/\d+$/, "") || original;
    let name = original;
    for (let n = 2; names.includes(name); n++) name = `${base}${n}`;
    const edits: ConfigEdit[] = [{ location: "drivetrain.wheels", op: "add", value: { ...copy.value, name, pos_in: shift(copy.value.pos_in) } }];
    for (const group of copy.groups) {
      const gear = robot.drivetrain.gearing[group];
      if (gear) edits.push({ location: `drivetrain.gearing.${group}.wheels`, op: "set", value: [...gear.wheels, name] });
    }
    return { edits, part: null, path: `drivetrain.wheels[${names.length}]`, label: `wheel ${name}` };
  }
  const value: Record<string, unknown> = { ...copy.value };
  const taken = portMap(robot);
  if (taken.has(Number(value.port))) value.port = freePorts(robot)[0] ?? value.port;
  if ("pos_in" in value) value.pos_in = shift(value.pos_in);
  const wheel = value.tracking_wheel as Record<string, unknown> | undefined;
  if (wheel) value.tracking_wheel = { ...wheel, pos_in: shift(wheel.pos_in) };
  const index = (robot.sensors ?? []).length;
  return {
    edits: [{ location: "sensors", op: "add", value }],
    part: null,
    path: wheel ? `sensors[${index}].tracking_wheel` : `sensors[${index}]`,
    label: `${/^[aeiou]/i.test(sensorName(String(value.type))) ? "an" : "a"} ${sensorName(String(value.type))} on port ${value.port}`,
  };
}

// Dragging the robot to where it starts: what the pointer is on, snapping, and keeping
// the robot inside the walls. Field inches and degrees counter-clockwise from +x.

import type { Body, Size } from "./body";
import { bodyContains, entersConvex, extentOf, frontOf, loopsOf, outlineOf, signedDistance, sizeOf } from "./body";
import { wrapDegrees } from "./pose";

export type { Body, Size } from "./body";
export type Pose = [number, number, number];

const DEG = Math.PI / 180;

/** Where the rotate handle is: on the robot's center line, `offset` inches ahead of
 * its front. */
export function handlePoint(pose: Pose, body: Body, offset: number): [number, number] {
  const reach = frontOf(body) + offset;
  return [pose[0] + reach * Math.cos(pose[2] * DEG), pose[1] + reach * Math.sin(pose[2] * DEG)];
}

/** What a pointer at `point` grabs: the rotate handle, the robot, or neither. */
export function hitStart(pose: Pose, body: Body, point: [number, number], handleOffset: number, handleRadius: number): "rotate" | "move" | null {
  const [hx, hy] = handlePoint(pose, body, handleOffset);
  if (Math.hypot(point[0] - hx, point[1] - hy) <= handleRadius) return "rotate";
  const [along, across] = robotFrame(pose, point);
  return bodyContains(body, along, across) ? "move" : null;
}

/** A field point in the robot's frame, the robot at `pose`. */
function robotFrame(pose: Pose, point: readonly [number, number]): [number, number] {
  const c = Math.cos(pose[2] * DEG);
  const s = Math.sin(pose[2] * DEG);
  const dx = point[0] - pose[0];
  const dy = point[1] - pose[1];
  return [c * dx + s * dy, -s * dx + c * dy];
}

/** The pose moved as little as it takes for the robot to fit inside the walls. */
export function keepInside(pose: Pose, body: Body, field: Size): Pose {
  if (outlineOf(body)) {
    const [left, right, bottom, top] = extentOf(body, pose[2]);
    const fit = (v: number, lo: number, hi: number) => (lo > hi ? (lo + hi) / 2 : Math.min(hi, Math.max(lo, v)));
    return [fit(pose[0], -field[0] / 2 - left, field[0] / 2 - right), fit(pose[1], -field[1] / 2 - bottom, field[1] / 2 - top), pose[2]];
  }
  const footprint = sizeOf(body);
  const c = Math.abs(Math.cos(pose[2] * DEG));
  const s = Math.abs(Math.sin(pose[2] * DEG));
  const halfX = (footprint[0] / 2) * c + (footprint[1] / 2) * s;
  const halfY = (footprint[0] / 2) * s + (footprint[1] / 2) * c;
  const clamp = (v: number, room: number) => (room <= 0 ? 0 : Math.min(room, Math.max(-room, v)));
  return [clamp(pose[0], field[0] / 2 - halfX), clamp(pose[1], field[1] / 2 - halfY), pose[2]];
}

/** `value` to the nearest multiple of `step` (never -0). */
export function snap(value: number, step: number): number {
  const snapped = Math.round(value / step) * step;
  return Object.is(snapped, -0) ? 0 : Number(snapped.toFixed(6));
}

/** The heading from `center` toward `point`, in (-180, 180]. */
export function headingTo(center: [number, number], point: [number, number]): number {
  return wrapDegrees(Math.atan2(point[1] - center[1], point[0] - center[0]) / DEG);
}

/** A pose for the run form: two decimals at most. */
export function formatStart(value: number): string {
  return String(Number(value.toFixed(2)));
}

export interface DragStep {
  move: number; // inches
  turn: number; // degrees
}
export const SNAP: DragStep = { move: 0.5, turn: 15 };
export const FINE: DragStep = { move: 0.1, turn: 1 }; // with Shift held

/** The start pose after dragging the robot so its center is at `center`. */
export function moved(pose: Pose, center: [number, number], body: Body, field: Size, step: DragStep): Pose {
  return keepInside([snap(center[0], step.move), snap(center[1], step.move), pose[2]], body, field);
}

/** The start pose after turning the robot to face `point`. */
export function turned(pose: Pose, point: [number, number], body: Body, field: Size, step: DragStep): Pose {
  const heading = wrapDegrees(snap(headingTo([pose[0], pose[1]], point), step.turn));
  return keepInside([pose[0], pose[1], heading], body, field);
}

export interface Obstacle {
  name: string;
  solid: boolean;
  shape: "circle" | "polygon";
  x?: number;
  y?: number;
  radius?: number;
  points?: [number, number][];
}

/** What the robot at `pose` stands on: the solid elements it overlaps, and "the walls" if
 * it sticks out past them. (The server warns about the same when a run starts.) */
export function blockedBy(pose: Pose, body: Body, field: { size: Size; obstacles: readonly Obstacle[] }): string[] {
  if (outlineOf(body)) return shapeBlockedBy(pose, body, field);
  const footprint = sizeOf(body);
  const c = Math.cos(pose[2] * DEG);
  const s = Math.sin(pose[2] * DEG);
  const [hl, hw] = [footprint[0] / 2, footprint[1] / 2];
  const corners: [number, number][] = [
    [hl, hw],
    [-hl, hw],
    [-hl, -hw],
    [hl, -hw],
  ].map(([u, v]) => [pose[0] + c * u - s * v, pose[1] + s * u + c * v]);
  const blocked: string[] = [];
  const tolerance = 0.005; // inches: touching isn't overlapping
  if (corners.some(([x, y]) => Math.abs(x) > field.size[0] / 2 + tolerance || Math.abs(y) > field.size[1] / 2 + tolerance)) {
    blocked.push("the walls");
  }
  for (const o of field.obstacles) {
    if (!o.solid) continue;
    if (o.shape === "circle") {
      const dx = o.x! - pose[0];
      const dy = o.y! - pose[1];
      const u = c * dx + s * dy;
      const v = -s * dx + c * dy;
      const gap = Math.hypot(u - Math.max(-hl, Math.min(hl, u)), v - Math.max(-hw, Math.min(hw, v)));
      if (gap < o.radius! - tolerance) blocked.push(o.name);
    } else if (o.points && overlap(corners, o.points, tolerance)) {
      blocked.push(o.name);
    }
  }
  return blocked;
}

/** `blockedBy` for a robot with a shape: its outline against each element, in its frame. */
function shapeBlockedBy(pose: Pose, body: Body, field: { size: Size; obstacles: readonly Obstacle[] }): string[] {
  const loops = loopsOf(body);
  const tolerance = 0.005;
  const blocked: string[] = [];
  const [left, right, bottom, top] = extentOf(body, pose[2]);
  const [halfX, halfY] = [field.size[0] / 2 + tolerance, field.size[1] / 2 + tolerance];
  if (pose[0] + left < -halfX || pose[0] + right > halfX || pose[1] + bottom < -halfY || pose[1] + top > halfY) {
    blocked.push("the walls");
  }
  for (const o of field.obstacles) {
    if (!o.solid) continue;
    if (o.shape === "circle") {
      const [x, y] = robotFrame(pose, [o.x!, o.y!]);
      if (signedDistance(loops, x, y) < o.radius! - tolerance) blocked.push(o.name);
      continue;
    }
    if (!o.points) continue;
    const polygon = o.points.map((p) => robotFrame(pose, p));
    const enters = loops.some((loop) => loop.some((a, i) => entersConvex(a, loop[(i + 1) % loop.length], polygon, tolerance)));
    // no edge of the shape goes into the element: it's all inside the shape, or all outside
    const middle = polygon.reduce(([sx, sy], [x, y]) => [sx + x / polygon.length, sy + y / polygon.length], [0, 0]);
    if (enters || signedDistance(loops, middle[0], middle[1]) < -tolerance) blocked.push(o.name);
  }
  return blocked;
}

/** Whether two convex polygons overlap by more than `tolerance` (separating axes). */
function overlap(a: [number, number][], b: [number, number][], tolerance: number): boolean {
  for (const polygon of [a, b]) {
    for (let i = 0; i < polygon.length; i++) {
      const [x0, y0] = polygon[i];
      const [x1, y1] = polygon[(i + 1) % polygon.length];
      const length = Math.hypot(x1 - x0, y1 - y0) || 1;
      const axis = [-(y1 - y0) / length, (x1 - x0) / length];
      const project = (p: [number, number][]) => p.map(([x, y]) => x * axis[0] + y * axis[1]);
      const pa = project(a);
      const pb = project(b);
      if (Math.min(Math.max(...pa), Math.max(...pb)) - Math.max(Math.min(...pa), Math.min(...pb)) <= tolerance) return false;
    }
  }
  return true;
}

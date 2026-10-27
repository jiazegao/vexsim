// The config editor's diagram: a robot seen from above in its own frame (+x forward), or a
// field with its elements, drawn from the config being edited; and which part is under the
// pointer, or under its turn handle.

import type { Part } from "./configdoc";
import { drawField } from "./draw";
import type { Palette } from "./palette";
import { withAlpha } from "./palette";
import type { FieldConfig, RobotConfig } from "./protocol";
import type { View } from "./view";
import { toScreen } from "./view";

export const HANDLE_GAP_PX = 16; // from a part's edge to its turn handle
export const HANDLE_RADIUS_PX = 6;
const GRAB_SLOP_PX = 5;
const MIN_GRAB_PX = 9; // a small part is still easy to grab
const DEG = Math.PI / 180;
const WHEEL_WIDTH_IN = 1.1;
const TRACKING_WIDTH_IN = 0.6;
const BEAM_IN = 5; // how long a distance sensor's beam is drawn
const FONT = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";

export interface PlanPicture {
  robot: RobotConfig | null;
  field: FieldConfig | null;
  parts: Part[]; // as they are now (a part being dragged where it's been dragged to)
  selected: string | null; // a part's path
  hovered: string | null;
  errors: Set<string>; // parts with errors (their paths)
  warnings: Set<string>;
  stale: boolean; // the text doesn't parse just now: this is how it last did
}

/** The robot's area: its footprint and every part, with room around them. */
export function robotExtent(robot: RobotConfig, parts: Part[]): [number, number] {
  const [length, width] = robot.body.footprint_in;
  let half = Math.max(length, width) / 2;
  for (const part of parts) half = Math.max(half, Math.abs(part.x) + part.size / 2, Math.abs(part.y) + part.size / 2);
  return [2 * half + 8, 2 * half + 8];
}

export function drawPlan(ctx: CanvasRenderingContext2D, view: View, colors: Palette, picture: PlanPicture): void {
  ctx.save();
  ctx.fillStyle = colors.page;
  ctx.fillRect(0, 0, view.width, view.height);
  if (picture.stale) ctx.globalAlpha = 0.45;
  if (picture.robot) drawRobotPlan(ctx, view, colors, picture.robot, picture);
  else if (picture.field) drawFieldPlan(ctx, view, colors, picture.field, picture);
  ctx.globalAlpha = 1;
  ctx.restore();
}

// --- robots ----------------------------------------------------------------------------------

function drawRobotPlan(ctx: CanvasRenderingContext2D, view: View, colors: Palette, robot: RobotConfig, picture: PlanPicture): void {
  drawInchGrid(ctx, view, colors);
  const [length, width] = robot.body.footprint_in;
  const corners: [number, number][] = [
    [length / 2, width / 2],
    [length / 2, -width / 2],
    [-length / 2, -width / 2],
    [-length / 2, width / 2],
  ];
  polygon(ctx, view, corners);
  ctx.fillStyle = withAlpha(colors.ink, 0.04);
  ctx.fill();
  ctx.strokeStyle = colors.ink2;
  ctx.lineWidth = 1.5;
  ctx.stroke();
  // the front edge, thicker, as on the field
  line(ctx, view, corners[0], corners[1]);
  ctx.lineWidth = 4;
  ctx.stroke();
  label(ctx, view, colors, length / 2, 0, "front", "start", 8, 4);

  for (const part of picture.parts) {
    const state = partState(part, picture);
    if (part.kind === "wheel" || part.kind === "tracking") drawWheelPart(ctx, view, colors, part, state);
    else if (part.kind === "distance") drawDistance(ctx, view, colors, part, state);
    else if (part.kind === "imu" || part.kind === "gps") drawBox(ctx, view, colors, part, state);
    else if (part.kind === "cg") drawCg(ctx, view, colors, part, state);
  }
  drawSelection(ctx, view, colors, picture);
}

/** A light inch grid (heavier every 6 in) and the robot's axes through its origin. */
function drawInchGrid(ctx: CanvasRenderingContext2D, view: View, colors: Palette): void {
  const [x0, y1] = [view.cx - view.width / 2 / view.scale, view.cy - view.height / 2 / view.scale];
  const [x1, y0] = [view.cx + view.width / 2 / view.scale, view.cy + view.height / 2 / view.scale];
  ctx.lineWidth = 1;
  for (const major of [false, true]) {
    ctx.beginPath();
    for (let x = Math.ceil(x0); x <= x1; x++) {
      if ((x % 6 === 0) !== major) continue;
      const [sx] = toScreen(view, x, 0);
      ctx.moveTo(Math.round(sx) + 0.5, 0);
      ctx.lineTo(Math.round(sx) + 0.5, view.height);
    }
    for (let y = Math.ceil(y1); y <= y0; y++) {
      if ((y % 6 === 0) !== major) continue;
      const [, sy] = toScreen(view, 0, y);
      ctx.moveTo(0, Math.round(sy) + 0.5);
      ctx.lineTo(view.width, Math.round(sy) + 0.5);
    }
    ctx.strokeStyle = major ? colors.grid : withAlpha(colors.grid, 0.45);
    ctx.stroke();
  }
  ctx.strokeStyle = colors.axis;
  ctx.beginPath();
  const [ox, oy] = toScreen(view, 0, 0);
  ctx.moveTo(0, Math.round(oy) + 0.5);
  ctx.lineTo(view.width, Math.round(oy) + 0.5);
  ctx.moveTo(Math.round(ox) + 0.5, 0);
  ctx.lineTo(Math.round(ox) + 0.5, view.height);
  ctx.stroke();
}

interface PartState {
  selected: boolean;
  hovered: boolean;
  error: boolean;
  warning: boolean;
}

function partState(part: Part, picture: PlanPicture): PartState {
  return {
    selected: picture.selected === part.path,
    hovered: picture.hovered === part.path,
    error: picture.errors.has(part.path),
    warning: picture.warnings.has(part.path),
  };
}

function outline(colors: Palette, state: PartState, normal: string): string {
  return state.error ? colors.critical : state.warning ? colors.warning : normal;
}

function drawWheelPart(ctx: CanvasRenderingContext2D, view: View, colors: Palette, part: Part, state: PartState): void {
  const tracking = part.kind === "tracking";
  const half = [part.size / 2, (tracking ? TRACKING_WIDTH_IN : WHEEL_WIDTH_IN) / 2];
  const corners = rotated(part, [
    [half[0], half[1]],
    [half[0], -half[1]],
    [-half[0], -half[1]],
    [-half[0], half[1]],
  ]);
  polygon(ctx, view, corners);
  ctx.fillStyle = tracking ? withAlpha(colors.wheel, 0.25) : colors.wheel;
  ctx.fill();
  if (tracking) ctx.setLineDash([3, 2]);
  ctx.strokeStyle = outline(colors, state, tracking ? colors.wheel : colors.ink2);
  ctx.lineWidth = state.error || state.warning || state.hovered ? 2 : 1;
  ctx.stroke();
  ctx.setLineDash([]);
  label(ctx, view, colors, part.x, part.y, part.label, "center", 0, -(half[1] * view.scale + 5));
}

function drawDistance(ctx: CanvasRenderingContext2D, view: View, colors: Palette, part: Part, state: PartState): void {
  const heading = (part.heading ?? 0) * DEG;
  line(ctx, view, [part.x, part.y], [part.x + BEAM_IN * Math.cos(heading), part.y + BEAM_IN * Math.sin(heading)]);
  ctx.strokeStyle = colors.beam;
  ctx.lineWidth = 2;
  ctx.setLineDash([5, 3]);
  ctx.stroke();
  ctx.setLineDash([]);
  const half = part.size / 2;
  polygon(ctx, view, rotated(part, [[half, half], [half, -half], [-half, -half], [-half, half]]));
  ctx.fillStyle = colors.beam;
  ctx.fill();
  ctx.strokeStyle = outline(colors, state, colors.ink);
  ctx.lineWidth = state.error || state.warning || state.hovered ? 2 : 1;
  ctx.stroke();
  label(ctx, view, colors, part.x, part.y, part.label, "center", 0, -(half * view.scale + 5));
}

function drawBox(ctx: CanvasRenderingContext2D, view: View, colors: Palette, part: Part, state: PartState): void {
  const half = part.size / 2;
  polygon(ctx, view, rotated(part, [[half, half], [half, -half], [-half, -half], [-half, half]]));
  ctx.fillStyle = colors.surface;
  ctx.fill();
  ctx.strokeStyle = outline(colors, state, colors.ink);
  ctx.lineWidth = state.error || state.warning || state.hovered ? 2.5 : 1.5;
  ctx.stroke();
  // which way it faces: its x axis (an IMU's) or its camera (a GPS's)
  const heading = (part.heading ?? 0) * DEG;
  const [sx, sy] = toScreen(view, part.x, part.y);
  const reach = half * view.scale;
  ctx.beginPath();
  ctx.moveTo(sx, sy);
  ctx.lineTo(sx + reach * Math.cos(heading), sy - reach * Math.sin(heading));
  ctx.strokeStyle = colors.ink;
  ctx.lineWidth = 1.5;
  ctx.stroke();
  label(ctx, view, colors, part.x, part.y, part.label, "center", 0, -(reach + 5));
}

function drawCg(ctx: CanvasRenderingContext2D, view: View, colors: Palette, part: Part, state: PartState): void {
  const [sx, sy] = toScreen(view, part.x, part.y);
  const radius = Math.max(5, (part.size / 2) * view.scale);
  ctx.beginPath();
  ctx.arc(sx, sy, radius, 0, 2 * Math.PI);
  ctx.fillStyle = colors.surface;
  ctx.fill();
  ctx.strokeStyle = outline(colors, state, colors.ink);
  ctx.lineWidth = state.hovered ? 2 : 1.5;
  ctx.stroke();
  // the usual center-of-gravity mark: two opposite quarters filled
  ctx.beginPath();
  ctx.moveTo(sx, sy);
  ctx.arc(sx, sy, radius, -Math.PI / 2, 0);
  ctx.moveTo(sx, sy);
  ctx.arc(sx, sy, radius, Math.PI / 2, Math.PI);
  ctx.fillStyle = colors.ink;
  ctx.fill();
  label(ctx, view, colors, part.x, part.y, part.label, "start", radius + 4, 4);
}

// --- fields ----------------------------------------------------------------------------------

function drawFieldPlan(ctx: CanvasRenderingContext2D, view: View, colors: Palette, field: FieldConfig, picture: PlanPicture): void {
  drawField(ctx, view, colors, field.size_in ?? [144, 144]);
  const elements = field.elements ?? [];
  for (const part of picture.parts) {
    const element = elements[Number(/\[(\d+)\]/.exec(part.path)?.[1] ?? -1)];
    if (!element) continue;
    const state = partState(part, picture);
    const color = element.color ?? (element.type === "piece" ? colors.piece : colors.obstacle);
    if (element.type === "obstacle" && element.shape === "rect") {
      const [length, width] = element.size_in ?? [1, 1];
      polygon(ctx, view, rotated(part, [[length / 2, width / 2], [length / 2, -width / 2], [-length / 2, -width / 2], [-length / 2, width / 2]]));
    } else {
      const [sx, sy] = toScreen(view, part.x, part.y);
      ctx.beginPath();
      ctx.arc(sx, sy, Math.max(1.5, (part.size / 2) * view.scale), 0, 2 * Math.PI);
    }
    const solid = element.type === "piece" || element.solid !== false;
    ctx.fillStyle = withAlpha(color, solid ? 0.9 : 0.3);
    ctx.fill();
    if (!solid) ctx.setLineDash([4, 3]);
    ctx.strokeStyle = outline(colors, state, element.type === "piece" ? colors.surface : color);
    ctx.lineWidth = state.error || state.warning || state.hovered ? 2.5 : 1.5;
    ctx.stroke();
    ctx.setLineDash([]);
    if (state.hovered || state.selected) label(ctx, view, colors, part.x, part.y, part.label, "center", 0, -((part.size / 2) * view.scale + 6));
  }
  drawSelection(ctx, view, colors, picture);
}

// --- selection and handles -------------------------------------------------------------------

function drawSelection(ctx: CanvasRenderingContext2D, view: View, colors: Palette, picture: PlanPicture): void {
  const part = picture.parts.find((p) => p.path === picture.selected);
  if (!part) return;
  const [sx, sy] = toScreen(view, part.x, part.y);
  const radius = grabRadius(part, view);
  ctx.beginPath();
  ctx.arc(sx, sy, radius + 3, 0, 2 * Math.PI);
  ctx.strokeStyle = colors.focus;
  ctx.lineWidth = 2;
  ctx.stroke();
  const handle = handlePoint(part, view);
  if (handle) {
    const heading = (part.heading ?? 0) * DEG;
    ctx.beginPath();
    ctx.moveTo(sx + (radius + 3) * Math.cos(heading), sy - (radius + 3) * Math.sin(heading));
    ctx.lineTo(handle[0], handle[1]);
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(handle[0], handle[1], HANDLE_RADIUS_PX, 0, 2 * Math.PI);
    ctx.fillStyle = colors.surface;
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.stroke();
  }
}

/** How far from a part's center it can be grabbed, in pixels. */
export function grabRadius(part: Part, view: View): number {
  return Math.max(MIN_GRAB_PX, (part.size / 2) * view.scale);
}

/** Where a turnable part's handle is, on the screen; null if it can't be turned. */
export function handlePoint(part: Part, view: View): [number, number] | null {
  if (part.heading === null || part.headingKey === null) return null;
  const [sx, sy] = toScreen(view, part.x, part.y);
  const reach = grabRadius(part, view) + 3 + HANDLE_GAP_PX;
  const heading = part.heading * DEG;
  return [sx + reach * Math.cos(heading), sy - reach * Math.sin(heading)];
}

/** What's under the pointer at (px, py): the selected part's turn handle first, then the
 * nearest part that can be grabbed there (the smallest, when they overlap). */
export function hitPart(parts: Part[], view: View, px: number, py: number, selected: string | null): { part: Part; turn: boolean } | null {
  const chosen = parts.find((p) => p.path === selected);
  const handle = chosen ? handlePoint(chosen, view) : null;
  if (chosen && handle && Math.hypot(px - handle[0], py - handle[1]) <= HANDLE_RADIUS_PX + GRAB_SLOP_PX) {
    return { part: chosen, turn: true };
  }
  let best: Part | null = null;
  for (const part of parts) {
    const [sx, sy] = toScreen(view, part.x, part.y);
    if (Math.hypot(px - sx, py - sy) > grabRadius(part, view) + GRAB_SLOP_PX) continue;
    if (!best || part.size < best.size) best = part;
  }
  return best ? { part: best, turn: false } : null;
}

// --- drawing helpers -------------------------------------------------------------------------

function rotated(part: Part, points: [number, number][]): [number, number][] {
  const heading = (part.heading ?? 0) * DEG;
  const c = Math.cos(heading);
  const s = Math.sin(heading);
  return points.map(([x, y]) => [part.x + c * x - s * y, part.y + s * x + c * y]);
}

function polygon(ctx: CanvasRenderingContext2D, view: View, points: [number, number][]): void {
  ctx.beginPath();
  points.forEach(([x, y], i) => {
    const [sx, sy] = toScreen(view, x, y);
    if (i === 0) ctx.moveTo(sx, sy);
    else ctx.lineTo(sx, sy);
  });
  ctx.closePath();
}

function line(ctx: CanvasRenderingContext2D, view: View, a: [number, number], b: [number, number]): void {
  const [ax, ay] = toScreen(view, ...a);
  const [bx, by] = toScreen(view, ...b);
  ctx.beginPath();
  ctx.moveTo(ax, ay);
  ctx.lineTo(bx, by);
}

function label(
  ctx: CanvasRenderingContext2D,
  view: View,
  colors: Palette,
  x: number,
  y: number,
  text: string,
  align: CanvasTextAlign,
  dx: number,
  dy: number,
): void {
  const [sx, sy] = toScreen(view, x, y);
  ctx.font = FONT;
  ctx.textAlign = align;
  ctx.lineWidth = 3;
  ctx.strokeStyle = colors.page;
  ctx.strokeText(text, sx + dx, sy + dy);
  ctx.fillStyle = colors.ink2;
  ctx.fillText(text, sx + dx, sy + dy);
  ctx.textAlign = "start";
}

// Drawing a run on a canvas: the field, its elements, the robot and what it senses.
// Everything is in field inches (see view.ts) except line widths, which are pixels.

import type { Palette } from "./palette";
import { mix, withAlpha } from "./palette";
import type { Shape as DrawnShape, FieldScene, FrameMessage, OverlayMessage, RobotScene } from "./protocol";
import { handlePoint } from "./startpose";
import type { View } from "./view";
import { toScreen } from "./view";

export interface Layers {
  trails: boolean;
  estimate: boolean;
  beams: boolean;
  forces: boolean; // each wheel's sideways force
  drawings: boolean; // what the robot code draws (vexsim::draw_*, bot.draw)
}

/** What the robot code has drawn, by layer (only the layers to show). */
export type Drawings = Record<string, DrawnShape[]>;

/** A robot and a field: a run's scene, or a preview before any run. */
export interface Shape {
  robot: RobotScene;
  field: FieldScene;
}

/** The robot where it will start, which can be dragged: drawn as the robot itself when
 * no run is shown, or as a dashed outline over a finished run. */
export interface StartMarker {
  pose: [number, number, number];
  robot: RobotScene;
  outline: boolean;
  grabbed: "move" | "rotate" | null;
  blocked: string[]; // what it would start on top of (drawn red)
}

/** Another run drawn over this one, at the same moment: its path (in its dashes) and its
 * robot, labelled with its name. */
export interface Ghost {
  label: string;
  dash: readonly number[];
  robot: RobotScene;
  pose: readonly [number, number, number];
  path: TrailLike;
}

/** A path: the first `length` points of `xs`, `ys`. */
export interface TrailLike {
  xs: number[];
  ys: number[];
  length: number;
}

export interface Picture {
  scene: Shape | null;
  frame: FrameMessage | null;
  overlay: OverlayMessage | null;
  truth: TrailLike;
  estimate: TrailLike;
  pieces?: [number, number][]; // with no frame: where the field config puts the pieces
  start?: StartMarker | null;
  ghosts?: Ghost[];
  drawings?: Drawings | null;
  logged?: readonly [number, number, number] | null; // a real robot's estimate, from its log
  stamp?: string | null; // written in the corner (a video's run and time)
}

export const HANDLE_GAP_PX = 18; // from the robot's front edge to its rotate handle
export const HANDLE_RADIUS_PX = 7;
const NEWTONS_TO_IN = 0.6; // side-force ticks: inches per newton, as the pygame viewer
const DEG = Math.PI / 180;
const MM_PER_IN = 25.4;
const NO_READING_IN = 10; // how long a beam that sees nothing is drawn
const WHEEL_WIDTH_IN = 1.1;
const DEFAULT_FIELD: [number, number] = [144, 144];
const POSE_TICK_PX = 14; // a drawn pose's heading tick
const LABEL_FONT = "12px system-ui, -apple-system, 'Segoe UI', sans-serif";

export function draw(ctx: CanvasRenderingContext2D, view: View, colors: Palette, picture: Picture, layers: Layers): void {
  const { scene, frame } = picture;
  ctx.save();
  ctx.fillStyle = colors.page;
  ctx.fillRect(0, 0, view.width, view.height);
  const size = scene?.field.size ?? DEFAULT_FIELD;
  drawField(ctx, view, colors, size);
  if (scene) drawElements(ctx, view, colors, scene, frame?.pieces ?? picture.pieces ?? []);
  if (layers.trails) {
    drawTrail(ctx, view, picture.truth, colors.truth);
    if (layers.estimate) drawTrail(ctx, view, picture.estimate, colors.estimate);
  }
  if (picture.overlay) drawOverlay(ctx, view, colors, picture.overlay);
  const drawings = layers.drawings ? picture.drawings : null;
  if (drawings) drawShapes(ctx, view, colors, drawings, false);
  for (const ghost of picture.ghosts ?? []) drawGhostRun(ctx, view, colors, ghost);
  const start = picture.start;
  if (start && !start.outline) drawRobot(ctx, view, colors, start.robot, start.pose, mounted(start.robot, start.pose), false);
  if (scene && frame) {
    if (layers.beams) drawBeams(ctx, view, colors, scene.robot, frame);
    drawRobot(ctx, view, colors, scene.robot, frame.pose, frame.wheels, layers.forces);
    if (layers.estimate && frame.estimate) drawGhost(ctx, view, colors, scene.robot, frame.estimate);
    for (const [x, y] of frame.contacts) dot(ctx, view, x, y, 4, colors.slip);
  }
  if (layers.estimate && picture.logged) {
    // a log's estimate: the robot's outline where its code thought it was (a mark without a robot)
    if (scene) drawGhost(ctx, view, colors, scene.robot, picture.logged);
    else drawShapes(ctx, view, colors, { estimate: [["pose", ...picture.logged, "blue"]] }, false);
  }
  if (start) drawStart(ctx, view, colors, start);
  if (drawings) drawShapes(ctx, view, colors, drawings, true); // text over everything but labels
  for (const ghost of picture.ghosts ?? []) drawLabel(ctx, view, colors, ghost);
  if (picture.stamp) drawStamp(ctx, view, colors, picture.stamp);
  ctx.restore();
}

export function drawField(ctx: CanvasRenderingContext2D, view: View, colors: Palette, [w, h]: [number, number]): void {
  const [x0, y0] = toScreen(view, -w / 2, h / 2);
  const [x1, y1] = toScreen(view, w / 2, -h / 2);
  ctx.fillStyle = colors.surface;
  ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
  // 6 x 6 tiles
  ctx.strokeStyle = colors.grid;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 1; i < 6; i++) {
    const [gx] = toScreen(view, -w / 2 + (w * i) / 6, 0);
    const [, gy] = toScreen(view, 0, -h / 2 + (h * i) / 6);
    ctx.moveTo(Math.round(gx) + 0.5, y0);
    ctx.lineTo(Math.round(gx) + 0.5, y1);
    ctx.moveTo(x0, Math.round(gy) + 0.5);
    ctx.lineTo(x1, Math.round(gy) + 0.5);
  }
  ctx.stroke();
  // walls
  ctx.strokeStyle = colors.ink2;
  ctx.lineWidth = 3;
  ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
  // axes, from the origin: +x right, +y up
  const [ox, oy] = toScreen(view, 0, 0);
  const length = Math.min(40, (x1 - x0) / 8);
  ctx.strokeStyle = colors.axis;
  ctx.fillStyle = colors.muted;
  ctx.lineWidth = 1.5;
  arrow(ctx, ox, oy, ox + length, oy);
  arrow(ctx, ox, oy, ox, oy - length);
  ctx.font = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";
  ctx.fillText("x", ox + length + 4, oy + 4);
  ctx.fillText("y", ox - 3, oy - length - 5);
}

function drawElements(ctx: CanvasRenderingContext2D, view: View, colors: Palette, scene: Shape, pieces: [number, number][]): void {
  for (const element of scene.field.obstacles) {
    const color = element.color ?? colors.obstacle;
    ctx.beginPath();
    if (element.shape === "circle") {
      const [cx, cy] = toScreen(view, element.x, element.y);
      ctx.arc(cx, cy, element.radius * view.scale, 0, 2 * Math.PI);
    } else {
      element.points.forEach(([px, py], i) => {
        const [sx, sy] = toScreen(view, px, py);
        if (i === 0) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      });
      ctx.closePath();
    }
    ctx.fillStyle = withAlpha(color, element.solid ? 0.9 : 0.3);
    ctx.fill();
    if (!element.solid) {
      ctx.setLineDash([4, 3]);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }
  pieces.forEach(([x, y], i) => {
    const style = scene.field.pieces[i];
    dot(ctx, view, x, y, (style?.radius ?? 1.5) * view.scale, style?.color ?? colors.piece, colors.surface);
  });
}

function drawTrail(ctx: CanvasRenderingContext2D, view: View, trail: TrailLike, color: string): void {
  if (trail.length < 2) return;
  ctx.beginPath();
  for (let i = 0; i < trail.length; i++) {
    const [sx, sy] = toScreen(view, trail.xs[i], trail.ys[i]);
    if (i === 0) ctx.moveTo(sx, sy);
    else ctx.lineTo(sx, sy);
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.stroke();
}

function drawOverlay(ctx: CanvasRenderingContext2D, view: View, colors: Palette, overlay: OverlayMessage): void {
  if (overlay.path && overlay.path.length > 1) {
    ctx.beginPath();
    overlay.path.forEach(([x, y], i) => {
      const [sx, sy] = toScreen(view, x, y);
      if (i === 0) ctx.moveTo(sx, sy);
      else ctx.lineTo(sx, sy);
    });
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = colors.target;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.setLineDash([]);
  }
  if (overlay.target) {
    const [x, y, heading] = overlay.target;
    const [sx, sy] = toScreen(view, x, y);
    ctx.beginPath();
    ctx.arc(sx, sy, 7, 0, 2 * Math.PI);
    ctx.strokeStyle = colors.target;
    ctx.lineWidth = 2;
    ctx.stroke();
    if (heading !== null) {
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(sx + 14 * Math.cos(heading * DEG), sy - 14 * Math.sin(heading * DEG));
      ctx.stroke();
    }
  }
}

/** What the robot code drew: its marks (under the robot), or its text (over it). Text is in
 * ink, with a dot of its color before it when it has one. */
export function drawShapes(ctx: CanvasRenderingContext2D, view: View, colors: Palette, drawings: Drawings, text: boolean): void {
  ctx.lineWidth = 1.5;
  ctx.lineJoin = "round";
  for (const shapes of Object.values(drawings)) {
    for (const shape of shapes) {
      if ((shape[0] === "text") !== text) continue;
      switch (shape[0]) {
        case "point": {
          const [, x, y, color, size] = shape;
          const [sx, sy] = toScreen(view, x, y);
          ctx.beginPath();
          ctx.arc(sx, sy, Math.max(0.75, size / 2), 0, 2 * Math.PI);
          ctx.fillStyle = colors.hues[color];
          ctx.fill();
          break;
        }
        case "line": {
          const [, x1, y1, x2, y2, color] = shape;
          const [ax, ay] = toScreen(view, x1, y1);
          const [bx, by] = toScreen(view, x2, y2);
          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(bx, by);
          ctx.strokeStyle = colors.hues[color];
          ctx.stroke();
          break;
        }
        case "circle": {
          const [, x, y, radius, color] = shape;
          const [sx, sy] = toScreen(view, x, y);
          ctx.beginPath();
          ctx.arc(sx, sy, Math.max(0.5, radius * view.scale), 0, 2 * Math.PI);
          ctx.strokeStyle = colors.hues[color];
          ctx.stroke();
          break;
        }
        case "ellipse": {
          const [, x, y, rx, ry, rotation, color] = shape;
          const [sx, sy] = toScreen(view, x, y);
          ctx.beginPath();
          // the screen's y points down: a counter-clockwise turn on the field is clockwise here
          ctx.ellipse(sx, sy, Math.max(0.5, Math.abs(rx) * view.scale), Math.max(0.5, Math.abs(ry) * view.scale), -rotation * DEG, 0, 2 * Math.PI);
          ctx.fillStyle = withAlpha(colors.hues[color], 0.12);
          ctx.fill();
          ctx.strokeStyle = colors.hues[color];
          ctx.stroke();
          break;
        }
        case "pose": {
          const [, x, y, heading, color] = shape;
          const [sx, sy] = toScreen(view, x, y);
          ctx.beginPath();
          ctx.moveTo(sx, sy);
          ctx.lineTo(sx + POSE_TICK_PX * Math.cos(heading * DEG), sy - POSE_TICK_PX * Math.sin(heading * DEG));
          ctx.strokeStyle = colors.hues[color];
          ctx.lineWidth = 2;
          ctx.stroke();
          ctx.lineWidth = 1.5;
          dot(ctx, view, x, y, 4, colors.hues[color], colors.surface);
          break;
        }
        case "text": {
          const [, x, y, label, color] = shape;
          const [px, sy] = toScreen(view, x, y);
          let sx = px;
          if (color !== "ink" && color !== "muted") {
            dot(ctx, view, x, y, 3.5, colors.hues[color], colors.surface);
            sx += 7;
          }
          ctx.font = LABEL_FONT;
          ctx.textBaseline = "middle";
          ctx.lineWidth = 3;
          ctx.strokeStyle = colors.surface;
          ctx.strokeText(label, sx, sy);
          ctx.fillStyle = color === "muted" ? colors.muted : colors.ink;
          ctx.fillText(label, sx, sy);
          ctx.textBaseline = "alphabetic";
          ctx.lineWidth = 1.5;
          break;
        }
      }
    }
  }
}

/** Robot frame (x forward, y left) to field frame, for a robot at `pose`. */
function place(pose: readonly [number, number, number], x: number, y: number): [number, number] {
  const c = Math.cos(pose[2] * DEG);
  const s = Math.sin(pose[2] * DEG);
  return [pose[0] + c * x - s * y, pose[1] + s * x + c * y];
}

function drawBeams(ctx: CanvasRenderingContext2D, view: View, colors: Palette, robot: RobotScene, frame: FrameMessage): void {
  for (const sensor of robot.sensors) {
    if (sensor.kind !== "distance") continue;
    const reading = frame.distance[String(sensor.port)];
    const [ox, oy] = place(frame.pose, sensor.x, sensor.y);
    const angle = (frame.pose[2] + sensor.heading) * DEG;
    const length = reading === null || reading === undefined ? NO_READING_IN : reading / MM_PER_IN;
    const [sx, sy] = toScreen(view, ox, oy);
    const [ex, ey] = toScreen(view, ox + length * Math.cos(angle), oy + length * Math.sin(angle));
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(ex, ey);
    if (reading === null || reading === undefined) {
      ctx.setLineDash([3, 4]);
      ctx.strokeStyle = colors.muted;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.setLineDash([]);
    } else {
      ctx.strokeStyle = colors.beam;
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(ex, ey, 3.5, 0, 2 * Math.PI);
      ctx.fillStyle = colors.beam;
      ctx.fill();
    }
  }
}

function footprint(robot: RobotScene, pose: readonly [number, number, number], view: View): [number, number][] {
  const [length, width] = robot.footprint;
  const corners: [number, number][] = [
    [length / 2, width / 2],
    [length / 2, -width / 2],
    [-length / 2, -width / 2],
    [-length / 2, width / 2],
  ];
  return corners.map(([x, y]) => {
    const [fx, fy] = place(pose, x, y);
    return toScreen(view, fx, fy);
  });
}

type WheelState = FrameMessage["wheels"][number];

/** The wheels of a robot standing at `pose`: where they're mounted, no slip, no force. */
function mounted(robot: RobotScene, pose: readonly [number, number, number]): WheelState[] {
  return robot.wheels.map((w) => [...place(pose, w.x, w.y), pose[2] + w.heading, 0, 0]);
}

function drawRobot(
  ctx: CanvasRenderingContext2D,
  view: View,
  colors: Palette,
  robot: RobotScene,
  pose: readonly [number, number, number],
  wheels: WheelState[],
  forces: boolean,
): void {
  const corners = footprint(robot, pose, view);
  ctx.beginPath();
  corners.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
  ctx.closePath();
  ctx.fillStyle = withAlpha(colors.ink, 0.08);
  ctx.fill();
  ctx.strokeStyle = colors.ink;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.stroke();
  // the front edge, thicker
  ctx.beginPath();
  ctx.moveTo(corners[0][0], corners[0][1]);
  ctx.lineTo(corners[1][0], corners[1][1]);
  ctx.lineWidth = 4;
  ctx.stroke();
  // wheels, colored by how much of their grip they use
  wheels.forEach(([x, y, heading, slip, side], i) => {
    const mount = robot.wheels[i];
    const length = mount ? mount.diameter : 3.25;
    const c = Math.cos(heading * DEG);
    const s = Math.sin(heading * DEG);
    const half = [
      [length / 2, WHEEL_WIDTH_IN / 2],
      [length / 2, -WHEEL_WIDTH_IN / 2],
      [-length / 2, -WHEEL_WIDTH_IN / 2],
      [-length / 2, WHEEL_WIDTH_IN / 2],
    ];
    ctx.beginPath();
    half.forEach(([u, v], j) => {
      const [sx, sy] = toScreen(view, x + c * u - s * v, y + s * u + c * v);
      if (j === 0) ctx.moveTo(sx, sy);
      else ctx.lineTo(sx, sy);
    });
    ctx.closePath();
    ctx.fillStyle = mix(colors.wheel, colors.slip, slip);
    ctx.fill();
    const roller = mount?.roller ?? 0;
    if (roller) {
      // mecanum: a stroke along the ground rollers' axis
      const g = (heading + roller) * DEG;
      const q = 0.35 * length;
      const [ax, ay] = toScreen(view, x - q * Math.cos(g), y - q * Math.sin(g));
      const [bx, by] = toScreen(view, x + q * Math.cos(g), y + q * Math.sin(g));
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(bx, by);
      ctx.strokeStyle = colors.surface;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    if (forces && Math.abs(side) > 0.2) {
      // the sideways force on the wheel, across its rolling direction
      const n = (heading + roller + 90) * DEG;
      const reach = side * NEWTONS_TO_IN;
      const [sx, sy] = toScreen(view, x, y);
      const [ex, ey] = toScreen(view, x + reach * Math.cos(n), y + reach * Math.sin(n));
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(ex, ey);
      ctx.strokeStyle = colors.target;
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  });
  // heading: center to front
  const [cx, cy] = toScreen(view, pose[0], pose[1]);
  const [fx, fy] = toScreen(view, ...place(pose, robot.footprint[0] / 2, 0));
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(fx, fy);
  ctx.strokeStyle = colors.ink;
  ctx.lineWidth = 2;
  ctx.stroke();
  dot(ctx, view, pose[0], pose[1], 3, colors.ink);
}

function drawStart(ctx: CanvasRenderingContext2D, view: View, colors: Palette, start: StartMarker): void {
  const { robot, pose } = start;
  if (start.blocked.length) {
    const corners = footprint(robot, pose, view);
    ctx.beginPath();
    corners.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.closePath();
    ctx.fillStyle = withAlpha(colors.slip, 0.18);
    ctx.fill();
    ctx.strokeStyle = colors.slip;
    ctx.lineWidth = 2.5;
    ctx.stroke();
  } else if (start.outline) {
    const corners = footprint(robot, pose, view);
    ctx.beginPath();
    corners.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.closePath();
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = colors.ink2;
    ctx.lineWidth = start.grabbed === "move" ? 2.5 : 1.5;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(corners[0][0], corners[0][1]);
    ctx.lineTo(corners[1][0], corners[1][1]);
    ctx.lineWidth = 3;
    ctx.stroke();
  }
  // the rotate handle, on a stalk from the front edge
  const [ex, ey] = toScreen(view, ...place(pose, robot.footprint[0] / 2, 0));
  const [hx, hy] = toScreen(view, ...handlePoint([...pose], robot.footprint, HANDLE_GAP_PX / view.scale));
  ctx.beginPath();
  ctx.moveTo(ex, ey);
  ctx.lineTo(hx, hy);
  ctx.strokeStyle = colors.ink2;
  ctx.lineWidth = 1.5;
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(hx, hy, HANDLE_RADIUS_PX, 0, 2 * Math.PI);
  ctx.fillStyle = start.grabbed === "rotate" ? colors.ink2 : colors.surface;
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.stroke();
}

/** A compared run: its path so far, in its dashes, and its robot's outline, in grey ink. */
function drawGhostRun(ctx: CanvasRenderingContext2D, view: View, colors: Palette, ghost: Ghost): void {
  ctx.setLineDash([...ghost.dash]);
  drawTrail(ctx, view, ghost.path, colors.ink2);
  ctx.setLineDash([]);
  const corners = footprint(ghost.robot, ghost.pose, view);
  ctx.beginPath();
  corners.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
  ctx.closePath();
  ctx.fillStyle = withAlpha(colors.ink2, 0.08);
  ctx.fill();
  ctx.strokeStyle = colors.ink2;
  ctx.lineWidth = 1.5;
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(corners[0][0], corners[0][1]);
  ctx.lineTo(corners[1][0], corners[1][1]);
  ctx.lineWidth = 3.5;
  ctx.stroke();
}

/** A compared run's name, above its robot (drawn last, so nothing covers it). */
function drawLabel(ctx: CanvasRenderingContext2D, view: View, colors: Palette, ghost: Ghost): void {
  const corners = footprint(ghost.robot, ghost.pose, view);
  const x = corners.reduce((sum, [cx]) => sum + cx, 0) / corners.length;
  const top = Math.min(...corners.map(([, cy]) => cy));
  ctx.font = "12px system-ui, -apple-system, 'Segoe UI', sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  ctx.lineWidth = 3;
  ctx.strokeStyle = colors.surface;
  ctx.strokeText(ghost.label, x, top - 4);
  ctx.fillStyle = colors.ink2;
  ctx.fillText(ghost.label, x, top - 4);
  ctx.textAlign = "start";
  ctx.textBaseline = "alphabetic";
}

/** A line of text in the bottom-left corner, on a plate. */
function drawStamp(ctx: CanvasRenderingContext2D, view: View, colors: Palette, text: string): void {
  ctx.font = "13px system-ui, -apple-system, 'Segoe UI', sans-serif";
  const width = ctx.measureText(text).width;
  ctx.fillStyle = withAlpha(colors.surface, 0.85);
  ctx.fillRect(8, view.height - 30, width + 16, 22);
  ctx.fillStyle = colors.ink;
  ctx.fillText(text, 16, view.height - 14);
}

function drawGhost(ctx: CanvasRenderingContext2D, view: View, colors: Palette, robot: RobotScene, pose: readonly [number, number, number]): void {
  const corners = footprint(robot, pose, view);
  ctx.beginPath();
  corners.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
  ctx.closePath();
  ctx.setLineDash([5, 4]);
  ctx.strokeStyle = colors.estimate;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.setLineDash([]);
  const [cx, cy] = toScreen(view, pose[0], pose[1]);
  const [fx, fy] = toScreen(view, ...place(pose, robot.footprint[0] / 2, 0));
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(fx, fy);
  ctx.stroke();
}

function dot(ctx: CanvasRenderingContext2D, view: View, x: number, y: number, radiusPx: number, fill: string, ring?: string): void {
  const [sx, sy] = toScreen(view, x, y);
  ctx.beginPath();
  ctx.arc(sx, sy, Math.max(1.5, radiusPx), 0, 2 * Math.PI);
  ctx.fillStyle = fill;
  ctx.fill();
  if (ring) {
    ctx.strokeStyle = ring;
    ctx.lineWidth = 1;
    ctx.stroke();
  }
}

function arrow(ctx: CanvasRenderingContext2D, x0: number, y0: number, x1: number, y1: number): void {
  const angle = Math.atan2(y1 - y0, x1 - x0);
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x1, y1);
  ctx.lineTo(x1 - 6 * Math.cos(angle - 0.45), y1 - 6 * Math.sin(angle - 0.45));
  ctx.moveTo(x1, y1);
  ctx.lineTo(x1 - 6 * Math.cos(angle + 0.45), y1 - 6 * Math.sin(angle + 0.45));
  ctx.stroke();
}

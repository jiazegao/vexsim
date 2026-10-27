// Drawing a run on a canvas: the field, its elements, the robot and what it senses.
// Everything is in field inches (see view.ts) except line widths, which are pixels.

import type { Palette } from "./palette";
import { mix, withAlpha } from "./palette";
import type { FrameMessage, OverlayMessage, SceneMessage } from "./protocol";
import type { Trail } from "./trail";
import type { View } from "./view";
import { toScreen } from "./view";

export interface Layers {
  trails: boolean;
  estimate: boolean;
  beams: boolean;
}

export interface Picture {
  scene: SceneMessage | null;
  frame: FrameMessage | null;
  overlay: OverlayMessage | null;
  truth: Trail;
  estimate: Trail;
}

const DEG = Math.PI / 180;
const MM_PER_IN = 25.4;
const NO_READING_IN = 10; // how long a beam that sees nothing is drawn
const WHEEL_WIDTH_IN = 1.1;
const DEFAULT_FIELD: [number, number] = [144, 144];

export function draw(ctx: CanvasRenderingContext2D, view: View, colors: Palette, picture: Picture, layers: Layers): void {
  const { scene, frame } = picture;
  ctx.save();
  ctx.fillStyle = colors.page;
  ctx.fillRect(0, 0, view.width, view.height);
  const size = scene?.field.size ?? DEFAULT_FIELD;
  drawField(ctx, view, colors, size);
  if (scene) drawElements(ctx, view, colors, scene, frame);
  if (layers.trails) {
    drawTrail(ctx, view, picture.truth, colors.truth);
    if (layers.estimate) drawTrail(ctx, view, picture.estimate, colors.estimate);
  }
  if (picture.overlay) drawOverlay(ctx, view, colors, picture.overlay);
  if (scene && frame) {
    if (layers.beams) drawBeams(ctx, view, colors, scene, frame);
    drawRobot(ctx, view, colors, scene, frame);
    if (layers.estimate && frame.estimate) drawGhost(ctx, view, colors, scene, frame.estimate);
    for (const [x, y] of frame.contacts) dot(ctx, view, x, y, 4, colors.slip);
  }
  ctx.restore();
}

function drawField(ctx: CanvasRenderingContext2D, view: View, colors: Palette, [w, h]: [number, number]): void {
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

function drawElements(ctx: CanvasRenderingContext2D, view: View, colors: Palette, scene: SceneMessage, frame: FrameMessage | null): void {
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
  if (frame) {
    frame.pieces.forEach(([x, y], i) => {
      const style = scene.field.pieces[i];
      dot(ctx, view, x, y, (style?.radius ?? 1.5) * view.scale, style?.color ?? colors.piece, colors.surface);
    });
  }
}

function drawTrail(ctx: CanvasRenderingContext2D, view: View, trail: Trail, color: string): void {
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

/** Robot frame (x forward, y left) to field frame, for a robot at `pose`. */
function place(pose: readonly [number, number, number], x: number, y: number): [number, number] {
  const c = Math.cos(pose[2] * DEG);
  const s = Math.sin(pose[2] * DEG);
  return [pose[0] + c * x - s * y, pose[1] + s * x + c * y];
}

function drawBeams(ctx: CanvasRenderingContext2D, view: View, colors: Palette, scene: SceneMessage, frame: FrameMessage): void {
  for (const sensor of scene.robot.sensors) {
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

function footprint(scene: SceneMessage, pose: readonly [number, number, number], view: View): [number, number][] {
  const [length, width] = scene.robot.footprint;
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

function drawRobot(ctx: CanvasRenderingContext2D, view: View, colors: Palette, scene: SceneMessage, frame: FrameMessage): void {
  const pose = frame.pose;
  const corners = footprint(scene, pose, view);
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
  frame.wheels.forEach(([x, y, heading, slip], i) => {
    const mount = scene.robot.wheels[i];
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
  });
  // heading: center to front
  const [cx, cy] = toScreen(view, pose[0], pose[1]);
  const [fx, fy] = toScreen(view, ...place(pose, scene.robot.footprint[0] / 2, 0));
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(fx, fy);
  ctx.strokeStyle = colors.ink;
  ctx.lineWidth = 2;
  ctx.stroke();
  dot(ctx, view, pose[0], pose[1], 3, colors.ink);
}

function drawGhost(ctx: CanvasRenderingContext2D, view: View, colors: Palette, scene: SceneMessage, pose: readonly [number, number, number]): void {
  const corners = footprint(scene, pose, view);
  ctx.beginPath();
  corners.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
  ctx.closePath();
  ctx.setLineDash([5, 4]);
  ctx.strokeStyle = colors.estimate;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.setLineDash([]);
  const [cx, cy] = toScreen(view, pose[0], pose[1]);
  const [fx, fy] = toScreen(view, ...place(pose, scene.robot.footprint[0] / 2, 0));
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

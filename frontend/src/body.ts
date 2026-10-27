// A robot's body seen from above, in its own frame (inches, +x forward): its footprint
// rectangle, centered on the robot's origin, or the outline of its shape (`body.shape` in
// its config): closed loops with the shape on their left, holes going the other way.

import type { BodyConfig, CirclePart, OutlinePart, RectPart } from "./protocol";

export type Size = readonly [number, number];
export type Loop = readonly (readonly [number, number])[];

/** A footprint (length by width), or a robot scene, whose `outline` is its shape's. */
export type Body = Size | { readonly footprint: Size; readonly outline?: readonly Loop[] | null };

const DEG = Math.PI / 180;

export function sizeOf(body: Body): Size {
  return isSize(body) ? body : body.footprint;
}

/** The shape's loops; null for a footprint rectangle. */
export function outlineOf(body: Body): readonly Loop[] | null {
  if (isSize(body)) return null;
  return body.outline?.length ? body.outline : null;
}

function isSize(body: Body): body is Size {
  return Array.isArray(body);
}

/** The body's edge as loops: a footprint's corners go front-left, back-left, back-right,
 * front-right. */
export function loopsOf(body: Body): readonly Loop[] {
  const outline = outlineOf(body);
  if (outline) return outline;
  const [length, width] = sizeOf(body);
  return [
    [
      [length / 2, width / 2],
      [-length / 2, width / 2],
      [-length / 2, -width / 2],
      [length / 2, -width / 2],
    ],
  ];
}

/** How far ahead the body's front is: where its +x axis leaves it (the footprint's front
 * edge), or the furthest forward any of it reaches if the axis misses it. */
export function frontOf(body: Body): number {
  const outline = outlineOf(body);
  if (!outline) return sizeOf(body)[0] / 2;
  let front = -Infinity;
  let furthest = -Infinity;
  for (const loop of outline) {
    loop.forEach(([x0, y0], i) => {
      const [x1, y1] = loop[(i + 1) % loop.length];
      furthest = Math.max(furthest, x0);
      if (y0 > 0 !== y1 > 0) {
        const x = x0 + ((0 - y0) * (x1 - x0)) / (y1 - y0);
        if (x >= 0) front = Math.max(front, x);
      }
    });
  }
  return Number.isFinite(front) ? front : furthest;
}

/** Whether a point (robot frame) is on the body. */
export function bodyContains(body: Body, x: number, y: number): boolean {
  const outline = outlineOf(body);
  if (!outline) {
    const [length, width] = sizeOf(body);
    return Math.abs(x) <= length / 2 && Math.abs(y) <= width / 2;
  }
  return winding(outline, x, y) !== 0;
}

/** Winding number of the loops around a point: nonzero inside the shape. */
export function winding(loops: readonly Loop[], x: number, y: number): number {
  let turns = 0;
  for (const loop of loops) {
    loop.forEach(([x0, y0], i) => {
      const [x1, y1] = loop[(i + 1) % loop.length];
      const side = (x1 - x0) * (y - y0) - (x - x0) * (y1 - y0);
      if (y0 <= y && y1 > y && side > 0) turns += 1;
      else if (y0 > y && y1 <= y && side < 0) turns -= 1;
    });
  }
  return turns;
}

/** Signed distance from a point (robot frame) to the shape's edge: negative inside. */
export function signedDistance(loops: readonly Loop[], x: number, y: number): number {
  let nearest = Infinity;
  for (const loop of loops) {
    loop.forEach(([x0, y0], i) => {
      const [x1, y1] = loop[(i + 1) % loop.length];
      const dx = x1 - x0;
      const dy = y1 - y0;
      const t = Math.max(0, Math.min(1, ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy || 1)));
      nearest = Math.min(nearest, Math.hypot(x - x0 - t * dx, y - y0 - t * dy));
    });
  }
  return winding(loops, x, y) !== 0 ? -nearest : nearest;
}

/** How far the body reaches from its origin along the field's axes, turned to `heading`
 * degrees: [least x, most x, least y, most y]. */
export function extentOf(body: Body, heading: number): [number, number, number, number] {
  const c = Math.cos(heading * DEG);
  const s = Math.sin(heading * DEG);
  const extent: [number, number, number, number] = [Infinity, -Infinity, Infinity, -Infinity];
  for (const loop of loopsOf(body)) {
    for (const [u, v] of loop) {
      const x = c * u - s * v;
      const y = s * u + c * v;
      extent[0] = Math.min(extent[0], x);
      extent[1] = Math.max(extent[1], x);
      extent[2] = Math.min(extent[2], y);
      extent[3] = Math.max(extent[3], y);
    }
  }
  return extent;
}

/** Whether the segment a-b reaches more than `tolerance` into a convex polygon. */
export function entersConvex(a: readonly [number, number], b: readonly [number, number], polygon: readonly (readonly [number, number])[], tolerance: number): boolean {
  const turn = area(polygon) >= 0 ? 1 : -1;
  let lo = 0;
  let hi = 1;
  for (let i = 0; i < polygon.length; i++) {
    const [px, py] = polygon[i];
    const [qx, qy] = polygon[(i + 1) % polygon.length];
    const length = Math.hypot(qx - px, qy - py) || 1;
    const ex = (turn * (qx - px)) / length;
    const ey = (turn * (qy - py)) / length;
    const start = ex * (a[1] - py) - ey * (a[0] - px) - tolerance; // > 0: well inside this edge
    const rate = ex * (b[1] - a[1]) - ey * (b[0] - a[0]);
    if (rate === 0) {
      if (start <= 0) return false;
      continue;
    }
    const t = -start / rate;
    if (rate > 0) lo = Math.max(lo, t);
    else hi = Math.min(hi, t);
    if (lo >= hi) return false;
  }
  return true;
}

function area(points: readonly (readonly [number, number])[]): number {
  let total = 0;
  points.forEach(([x0, y0], i) => {
    const [x1, y1] = points[(i + 1) % points.length];
    total += x0 * y1 - x1 * y0;
  });
  return total / 2;
}

/** A part of a config's `body.shape` as points around its edge (a circle's, `sides` of them). */
export function partPoints(part: RectPart | CirclePart | OutlinePart, sides = 48): [number, number][] {
  if (part.type === "outline") return part.points_in.map(([x, y]) => [x, y]);
  const [cx, cy] = part.pos_in ?? [0, 0];
  if (part.type === "circle") {
    const r = part.diameter_in / 2;
    return Array.from({ length: sides }, (_, k) => [cx + r * Math.cos((2 * Math.PI * k) / sides), cy + r * Math.sin((2 * Math.PI * k) / sides)]);
  }
  const [hx, hy] = [part.size_in[0] / 2, part.size_in[1] / 2];
  const c = Math.cos((part.heading_deg ?? 0) * DEG);
  const s = Math.sin((part.heading_deg ?? 0) * DEG);
  const corners: [number, number][] = [
    [hx, hy],
    [-hx, hy],
    [-hx, -hy],
    [hx, -hy],
  ];
  return corners.map(([u, v]) => [cx + c * u - s * v, cy + s * u + c * v]);
}

/** Every point of a config's body that can reach furthest: its footprint's corners, or its
 * shape's parts' points. */
export function configPoints(body: BodyConfig): [number, number][] {
  if (body.shape?.length) return body.shape.flatMap((part) => partPoints(part));
  const [length, width] = body.footprint_in ?? [0, 0];
  return [
    [length / 2, width / 2],
    [-length / 2, width / 2],
    [-length / 2, -width / 2],
    [length / 2, -width / 2],
  ];
}

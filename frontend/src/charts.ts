// Chart data for the analysis pages: series lined up on one x axis, distributions as
// ECDFs, and x-y paths fitted to a canvas at one scale for both axes.

import type { View } from "./view";

export type Values = (number | null | undefined)[];

/** Series with x values of their own, on one x axis (all their x values, in order): a
 * series has `undefined` where it has no point, which uPlot draws straight across. */
export function join(series: { x: readonly number[]; y: readonly (number | null)[] }[]): { x: number[]; ys: Values[] } {
  const x = [...new Set(series.flatMap((s) => s.x))].sort((a, b) => a - b);
  const index = new Map(x.map((v, i) => [v, i]));
  const ys = series.map((s) => {
    const out: Values = new Array(x.length).fill(undefined);
    s.x.forEach((v, i) => {
      out[index.get(v)!] = s.y[i] ?? null;
    });
    return out;
  });
  return { x, ys };
}

/** Empirical cumulative distributions on one x axis: for each series, the fraction of
 * its values at or below each x (NaN and null values left out). */
export function ecdf(series: readonly (readonly (number | null | undefined)[])[]): { x: number[]; ys: number[][] } {
  const finite = series.map((values) => values.filter((v): v is number => typeof v === "number" && Number.isFinite(v)).sort((a, b) => a - b));
  const x = [...new Set(finite.flat())].sort((a, b) => a - b);
  const ys = finite.map((values) => {
    let at = 0;
    return x.map((v) => {
      while (at < values.length && values[at] <= v) at++;
      return values.length ? at / values.length : 0;
    });
  });
  return { x, ys };
}

/** A round grid spacing (1, 2 or 5 times a power of ten) for about `lines` lines. */
export function niceStep(span: number, lines = 6): number {
  if (!(span > 0)) return 1;
  const raw = span / lines;
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  return (unit < 1.5 ? 1 : unit < 3.5 ? 2 : unit < 7.5 ? 5 : 10) * power;
}

export type Point = readonly [number, number];

/** The smallest box around every point: [xmin, ymin, xmax, ymax], or null with none. */
export function bounds(paths: readonly (readonly Point[])[]): [number, number, number, number] | null {
  let box: [number, number, number, number] | null = null;
  for (const path of paths) {
    for (const [x, y] of path) {
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      if (!box) box = [x, y, x, y];
      else box = [Math.min(box[0], x), Math.min(box[1], y), Math.max(box[2], x), Math.max(box[3], y)];
    }
  }
  return box;
}

/** A view that shows the whole box on a canvas, at one scale for x and y, `margin`
 * pixels to spare (and at least `least` inches across). */
export function fit(box: [number, number, number, number], width: number, height: number, margin = 28, least = 6): View {
  const spanX = Math.max(box[2] - box[0], least);
  const spanY = Math.max(box[3] - box[1], least);
  const scale = Math.max(1e-6, Math.min((width - 2 * margin) / spanX, (height - 2 * margin) / spanY));
  return { scale, cx: (box[0] + box[2]) / 2, cy: (box[1] + box[3]) / 2, width, height };
}

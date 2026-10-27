// What the Plots tab draws: a chart per quantity (one unit, one axis each) from a run's
// telemetry columns, with the compared runs beside the shown one where a chart has a single
// quantity; and their rows lined up on one time axis.

import type { Telemetry } from "./protocol";

export const MAX_SERIES = 8; // the palette's hues; more motors than this split into charts

export interface SeriesSpec {
  label: string;
  column: string;
  run: number; // 0: the shown run; 1, 2, ...: the compared runs, in order
  slot: number | null; // the palette slot (1-8), or null: grey ink (a compared run)
  dash: readonly number[] | null; // a compared run's dashes
}

export interface ChartSpec {
  id: string;
  title: string;
  unit: string;
  series: SeriesSpec[];
}

export interface RunColumns {
  name: string;
  telemetry: Telemetry;
  dash?: readonly number[]; // a compared run's
}

const TRUE_SLOT = 3; // aqua: the true path's color on the field
const ESTIMATE_SLOT = 1; // blue: the estimate's

function has(telemetry: Telemetry, column: string): boolean {
  return (telemetry.columns[column] ?? []).some((v) => v !== null);
}

/** The charts for the shown run (`runs[0]`) and the compared ones. */
export function chartsFor(runs: RunColumns[], mechanisms: string[] = []): ChartSpec[] {
  if (runs.length === 0) return [];
  const shown = runs[0].telemetry;
  const charts: ChartSpec[] = [];
  /** One quantity: the shown run and every compared run that logged it. */
  const single = (id: string, title: string, unit: string, column: string) => {
    if (!has(shown, column)) return;
    const series: SeriesSpec[] = [];
    runs.forEach((run, i) => {
      if (has(run.telemetry, column)) {
        series.push({ label: run.name, column, run: i, slot: i === 0 ? TRUE_SLOT : null, dash: i === 0 ? null : (run.dash ?? null) });
      }
    });
    charts.push({ id, title, unit, series });
  };
  /** The true value and the robot code's estimate of it. */
  const pair = (id: string, title: string, unit: string, truth: string, estimate: string) => {
    if (!has(shown, truth)) return;
    const series: SeriesSpec[] = [{ label: "True", column: truth, run: 0, slot: TRUE_SLOT, dash: null }];
    if (has(shown, estimate)) series.push({ label: "Its code's estimate", column: estimate, run: 0, slot: ESTIMATE_SLOT, dash: null });
    charts.push({ id, title, unit, series });
  };
  /** One series per motor port (or mechanism), in fixed order, MAX_SERIES to a chart. */
  const group = (id: string, title: string, unit: string, entries: { label: string; column: string }[]) => {
    const present = entries.filter((e) => has(shown, e.column));
    for (let at = 0; at < present.length; at += MAX_SERIES) {
      const part = present.slice(at, at + MAX_SERIES);
      const split = present.length > MAX_SERIES;
      charts.push({
        id: split ? `${id}-${at / MAX_SERIES + 1}` : id,
        title: split ? `${title}, ${part[0].label}–${part.at(-1)!.label}` : title,
        unit,
        series: part.map((e, k) => ({ ...e, run: 0, slot: k + 1, dash: null })),
      });
    }
  };

  single("pose-error", "Pose error", "in", "error_in");
  single("heading-error", "Heading error", "°", "error_deg");
  pair("x", "x position", "in", "x_in", "est_x_in");
  pair("y", "y position", "in", "y_in", "est_y_in");
  pair("heading", "Heading", "°", "heading_deg", "est_heading_deg");
  single("speed", "Speed", "in/s", "speed_in_s");
  single("turn-rate", "Turn rate", "°/s", "yaw_rate_deg_s");
  single("battery", "Battery", "V", "battery_v");
  const ports = motorPorts(shown);
  const motors = (suffix: string) => ports.map((p) => ({ label: `port ${p}`, column: `motor${p}_${suffix}` }));
  group("motor-current", "Motor current", "A", motors("current_a"));
  group("motor-temp", "Motor temperature", "°C", motors("temp_c"));
  group("motor-volts", "Motor voltage", "V", motors("volts"));
  group(
    "mechanisms",
    "Mechanisms",
    "°",
    mechanisms.map((name) => ({ label: name, column: `${name}_deg` })),
  );
  return charts;
}

/** The motor ports a telemetry log has columns for, in order. */
export function motorPorts(telemetry: Telemetry): number[] {
  const ports = new Set<number>();
  for (const column of Object.keys(telemetry.columns)) {
    const m = /^motor(\d+)_current_a$/.exec(column);
    if (m) ports.add(Number(m[1]));
  }
  return [...ports].sort((a, b) => a - b);
}

/** A chart's data as uPlot takes it: one time axis (every run's times, in order) and a row
 * of values per series. A run with no sample at a time has `undefined` there, which uPlot
 * draws straight across; `null` (no value logged) stays a gap. */
export function chartData(chart: ChartSpec, runs: RunColumns[]): [number[], ...(number | null | undefined)[][]] {
  const times = runs.map((run) => (run.telemetry.columns.time_s ?? []) as number[]);
  const used = [...new Set(chart.series.map((s) => s.run))];
  if (used.length === 1) {
    const t = times[used[0]];
    return [t, ...chart.series.map((s) => runs[s.run].telemetry.columns[s.column] ?? [])];
  }
  const all = [...new Set(used.flatMap((run) => times[run]))].sort((a, b) => a - b);
  const row = new Map(all.map((t, i) => [t, i]));
  const ys = chart.series.map((s) => {
    const out = new Array<number | null | undefined>(all.length).fill(undefined);
    const values = runs[s.run].telemetry.columns[s.column] ?? [];
    times[s.run].forEach((t, i) => {
      out[row.get(t)!] = values[i] ?? null;
    });
    return out;
  });
  return [all, ...ys];
}

/** The value of `series` nearest before or at `t` (for the readout), or null. */
export function valueAt(xs: readonly number[], ys: readonly (number | null | undefined)[], t: number): number | null {
  let low = 0;
  let high = xs.length - 1;
  if (high < 0 || t < xs[0]) return null;
  while (low < high) {
    const middle = (low + high + 1) >> 1;
    if (xs[middle] <= t) low = middle;
    else high = middle - 1;
  }
  for (let i = low; i >= 0; i--) {
    const v = ys[i];
    if (v !== undefined) return v;
  }
  return null;
}

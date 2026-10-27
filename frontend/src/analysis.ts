// What the Analyze page draws from its jobs' results: motor curves, drift paths, and the
// odometry baselines against the truth.

import type { Values } from "./charts";
import { join } from "./charts";
import type { LineSeries, RefLine } from "./components/LineChart";
import type { PathSeries } from "./components/PathChart";
import type { Drift, MotorCurves, Odometry, WorkspaceItem } from "./protocol";

export interface ChartData {
  id: string;
  title: string;
  unit: string;
  digits: number;
  x: number[];
  series: LineSeries[];
  refs?: RefLine[];
}

/** Torque, current and output power against speed: a chart each, a series per command. */
export function motorCharts(result: MotorCurves): ChartData[] {
  const quantity = (key: "torque_nm" | "current_a" | "power_w") => {
    const joined = join(result.curves.map((c) => ({ x: c.speed_rpm, y: c[key] })));
    return { x: joined.x, series: result.curves.map((c, i): LineSeries => ({ label: c.label, values: joined.ys[i], slot: i + 1 })) };
  };
  const torque = quantity("torque_nm");
  const current = quantity("current_a");
  const power = quantity("power_w");
  return [
    { id: "torque", title: "Torque", unit: "N·m", digits: 3, ...torque },
    {
      id: "current",
      title: "Current",
      unit: "A",
      digits: 2,
      ...current,
      refs: [{ axis: "y", value: result.current_limit_a, label: `current limit ${result.current_limit_a} A` }],
    },
    { id: "power", title: "Output power", unit: "W", digits: 1, ...power },
  ];
}

/** Each roller friction's true path (solid) and what drive-encoder odometry believes
 * (dashed), in the same color. */
export function driftPaths(result: Drift): PathSeries[] {
  return result.runs.flatMap((run, i): PathSeries[] => [
    { label: `roller friction ${run.lateral_mu}`, points: run.true, slot: i + 1, end: true },
    { label: `odometry, roller friction ${run.lateral_mu}`, points: run.odometry, slot: i + 1, dash: [6, 4], end: true, key: false },
  ]);
}

/** The true path (in ink) and each localizer's estimate. */
export function odometryPaths(result: Odometry): PathSeries[] {
  return [
    { label: "true path", points: result.truth.map(([x, y]) => [x, y] as const), slot: null, width: 2.5, end: true },
    ...result.estimates.map((e, i): PathSeries => ({ label: e.name, points: e.path.map(([x, y]) => [x, y] as const), slot: i + 1, end: true })),
  ];
}

/** Each localizer's position and heading error over time. */
export function odometryCharts(result: Odometry): ChartData[] {
  const series = (key: "position_error_in" | "heading_error_deg") => result.estimates.map((e, i): LineSeries => ({ label: e.name, values: e[key] as Values, slot: i + 1 }));
  return [
    { id: "position-error", title: "Position error", unit: "in", digits: 2, x: result.time_s, series: series("position_error_in") },
    { id: "heading-error", title: "Heading error", unit: "°", digits: 2, x: result.time_s, series: series("heading_error_deg") },
  ];
}

/** Whether a robot item has a differential drivetrain (drift runs need one). */
export function isDifferential(item: WorkspaceItem): boolean {
  return item.detail.startsWith("differential");
}

/** Up to three roller frictions, from text like "0.4, 0.2, 0.1"; null if it isn't. */
export function parseFrictions(text: string): number[] | null {
  const parts = text
    .split(/[,\s]+/)
    .map((p) => p.trim())
    .filter(Boolean);
  if (parts.length === 0 || parts.length > 3) return null;
  const values = parts.map(Number);
  return values.every((v) => Number.isFinite(v) && v > 0 && v <= 2) ? values : null;
}

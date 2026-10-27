// What the Calibrate page shows of a fit: each logged channel against the simulation's
// replay of it, and how sure the fit is of each value.

import type { ChartData } from "./analysis";
import type { CalibrationResult } from "./protocol";

const SERIES_STYLE: Record<string, { slot: number; dash?: number[] }> = {
  "robot log": { slot: 3 },
  "simulated, before the fit": { slot: 2, dash: [6, 4] },
  simulated: { slot: 1 },
};

/** The charts of a calibration: each logged channel against the simulation's replay of it. */
export function calibrationCharts(result: CalibrationResult): ChartData[] {
  return result.panels.map((panel, i) => {
    // "left motor (port 1) velocity, rpm": the title, then its unit
    const comma = panel.title.lastIndexOf(", ");
    return {
      id: `panel-${i}`,
      title: comma > 0 ? panel.title.slice(0, comma) : panel.title,
      unit: comma > 0 ? panel.title.slice(comma + 2) : panel.unit,
      digits: 1,
      x: panel.time_s,
      series: panel.series.map((s) => ({ label: s.name, values: s.values, ...(SERIES_STYLE[s.name] ?? { slot: i + 1 }) })),
    };
  });
}

/** How sure a fit is of a value: its standard deviation, or that the log hardly says. */
export function uncertainty(spread: number): string {
  return spread < 0.5 ? `±${Math.max(0.1, +(spread * 100).toPrecision(2))}%` : "poorly determined by this log";
}

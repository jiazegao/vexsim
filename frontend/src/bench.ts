// What the Bench page shows of a benchmark's result: a row per localizer and controller
// combination, and the distribution of each metric across the seeds.

import type { ChartData } from "./analysis";
import { ecdf } from "./charts";
import { MAX_SERIES } from "./plots";
import { fixed } from "./pose";
import type { BenchResult, BenchSummary, Combination, Stats } from "./protocol";

export const ROBOT_CODE = "robot code"; // the localizer of a PROS project: its own

/** What a combination is called: its localizer and its controller. */
export function comboLabel(c: Combination): string {
  return c.localizer === ROBOT_CODE ? `${c.controller} (its own localization)` : `${c.localizer} / ${c.controller}`;
}

export const ECDF_METRICS: { key: string; title: string; unit: string }[] = [
  { key: "final_error_in", title: "Final position error", unit: "in" },
  { key: "loc_error_final_in", title: "Localization error at the end", unit: "in" },
  { key: "completion_time_s", title: "Completion time", unit: "s" },
  { key: "path_rms_in", title: "Path tracking error (RMS)", unit: "in" },
];

/** For each metric, the share of trials at or below each value, a line per combination
 * (the first MAX_SERIES of them): how often a combination does at least this well. */
export function ecdfCharts(result: BenchResult): ChartData[] {
  const combos = result.combos.slice(0, MAX_SERIES);
  const charts: ChartData[] = [];
  for (const metric of ECDF_METRICS) {
    const values = combos.map((c) =>
      result.rows.filter((r) => r.localizer === c.localizer && r.controller === c.controller).map((r) => r[metric.key] as number | null),
    );
    if (values.every((v) => v.every((x) => x === null || x === undefined))) continue;
    const { x, ys } = ecdf(values);
    const tolerance = result.scenario.tolerance_in;
    charts.push({
      id: metric.key,
      title: metric.title,
      unit: "share of trials",
      digits: 2,
      x,
      series: combos.map((c, i) => ({ label: comboLabel(c), values: ys[i], slot: i + 1 })),
      refs: metric.key === "final_error_in" && tolerance ? [{ axis: "x", value: tolerance, label: `tolerance ${tolerance} in` }] : undefined,
    });
  }
  return charts;
}

export function xUnitOf(chart: ChartData): string {
  return ECDF_METRICS.find((m) => m.key === chart.id)?.unit ?? "";
}

/** A metric's mean and 95th percentile, as the table shows them. */
export function meanP95(stats: Stats | null | undefined, digits = 2): string {
  return stats ? `${fixed(stats.mean, digits)} / ${fixed(stats.p95, digits)}` : "—";
}

export function percent(share: number | null | undefined): string {
  return share === null || share === undefined || !Number.isFinite(share) ? "—" : `${Math.round(share * 100)}%`;
}

/** The summary entry of a combination. */
export function summaryOf(result: BenchResult, c: Combination): BenchSummary | undefined {
  return result.summary.find((s) => s.localizer === c.localizer && s.controller === c.controller);
}

import { describe, expect, it } from "vitest";
import { chartData, chartsFor, MAX_SERIES, motorPorts, valueAt } from "../src/plots";
import type { Telemetry } from "../src/protocol";

/** A telemetry log of `rows` rows, 10 ms apart, with `motors` motors. */
function log(rows: number, motors: number, extra: Record<string, (number | null)[]> = {}): Telemetry {
  const t = Array.from({ length: rows }, (_, i) => i / 100);
  const columns: Record<string, (number | null)[]> = {
    time_s: t,
    x_in: t.map((v) => v * 10),
    y_in: t.map(() => 0),
    heading_deg: t.map(() => 90),
    est_x_in: t.map((v) => v * 10 + 1),
    est_y_in: t.map(() => 0),
    est_heading_deg: t.map(() => 91),
    speed_in_s: t.map(() => 10),
    yaw_rate_deg_s: t.map(() => 0),
    battery_v: t.map(() => 12.5),
    battery_soc: t.map(() => 1),
    error_in: t.map(() => 1),
    error_deg: t.map(() => 1),
    ...extra,
  };
  for (let p = 1; p <= motors; p++) {
    columns[`motor${p}_current_a`] = t.map(() => p);
    columns[`motor${p}_temp_c`] = t.map(() => 25);
    columns[`motor${p}_volts`] = t.map(() => 6);
  }
  return { columns, phases: [[0, "autonomous"]] };
}

describe("the plots of a run", () => {
  it("draws a chart per quantity, the estimate beside the truth in the field's colors", () => {
    const charts = chartsFor([{ name: "run", telemetry: log(10, 2) }], ["lift"]);
    expect(charts.map((c) => c.id)).toEqual([
      "pose-error",
      "heading-error",
      "x",
      "y",
      "heading",
      "speed",
      "turn-rate",
      "battery",
      "motor-current",
      "motor-temp",
      "motor-volts",
    ]); // no lift_deg column: no mechanisms chart
    const x = charts.find((c) => c.id === "x")!;
    expect(x.series.map((s) => [s.column, s.slot])).toEqual([
      ["x_in", 3],
      ["est_x_in", 1],
    ]);
    expect(charts.find((c) => c.id === "motor-current")!.series.map((s) => s.slot)).toEqual([1, 2]);
  });

  it("leaves out what wasn't logged, and splits motors past the palette's hues", () => {
    const telemetry = log(5, MAX_SERIES + 2, { error_in: [null, null, null, null, null], lift_deg: [0, 1, 2, 3, 4] });
    const charts = chartsFor([{ name: "run", telemetry }], ["lift"]);
    expect(charts.some((c) => c.id === "pose-error")).toBe(false); // never an estimate
    const current = charts.filter((c) => c.id.startsWith("motor-current"));
    expect(current.map((c) => [c.title, c.series.length])).toEqual([
      ["Motor current, port 1–port 8", 8],
      ["Motor current, port 9–port 10", 2],
    ]);
    expect(current[1].series.map((s) => s.slot)).toEqual([1, 2]); // each chart from the first hue
    expect(charts.at(-1)!.series.map((s) => s.column)).toEqual(["lift_deg"]);
  });

  it("puts compared runs in the single-quantity charts only, in grey and their dashes", () => {
    const runs = [
      { name: "shown", telemetry: log(10, 1) },
      { name: "other", telemetry: log(20, 1), dash: [2, 4] },
    ];
    const charts = chartsFor(runs);
    const speed = charts.find((c) => c.id === "speed")!;
    expect(speed.series.map((s) => [s.label, s.run, s.slot, s.dash])).toEqual([
      ["shown", 0, 3, null],
      ["other", 1, null, [2, 4]],
    ]);
    expect(charts.find((c) => c.id === "x")!.series.every((s) => s.run === 0)).toBe(true);
    expect(motorPorts(runs[0].telemetry)).toEqual([1]);
  });

  it("lines up runs logged at different times on one time axis", () => {
    const a: Telemetry = { columns: { time_s: [0, 0.02, 0.04], speed_in_s: [1, null, 3] }, phases: [] };
    const b: Telemetry = { columns: { time_s: [0, 0.01, 0.02], speed_in_s: [5, 6, 7] }, phases: [] };
    const runs = [
      { name: "a", telemetry: a },
      { name: "b", telemetry: b, dash: [8, 5] },
    ];
    const [chart] = chartsFor(runs).filter((c) => c.id === "speed");
    const [t, ya, yb] = chartData(chart, runs);
    expect(t).toEqual([0, 0.01, 0.02, 0.04]);
    expect(ya).toEqual([1, undefined, null, 3]); // undefined: no sample (drawn across); null: a gap
    expect(yb).toEqual([5, 6, 7, undefined]);
    expect(chartData(chartsFor([runs[0]]).find((c) => c.id === "speed")!, [runs[0]])).toEqual([[0, 0.02, 0.04], [1, null, 3]]);
  });

  it("reads the value at a moment: the last sample at or before it", () => {
    const xs = [0, 0.01, 0.02, 0.04];
    const ys = [1, undefined, null, 3];
    expect(valueAt(xs, ys, -1)).toBeNull();
    expect(valueAt(xs, ys, 0.015)).toBe(1); // skips the run's missing sample
    expect(valueAt(xs, ys, 0.03)).toBeNull(); // a gap in the log
    expect(valueAt(xs, ys, 9)).toBe(3);
  });
});

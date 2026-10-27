import { describe, expect, it } from "vitest";
import { driftPaths, isDifferential, motorCharts, odometryCharts, odometryPaths, parseFrictions } from "../src/analysis";
import { comboLabel, ecdfCharts, meanP95, percent, xUnitOf } from "../src/bench";
import { calibrationCharts, uncertainty } from "../src/calibration";
import type { BenchResult, CalibrationResult, Drift, MotorCurves, Odometry, WorkspaceItem } from "../src/protocol";

describe("the Analyze page", () => {
  it("charts torque, current and power against speed, a series per command", () => {
    const curves: MotorCurves = {
      cartridge: "green",
      supply_voltage: 12.8,
      current_limit_a: 2.5,
      curves: [
        { command: "velocity", label: "move_velocity(max)", speed_rpm: [0, 100, 200], torque_nm: [1, 1, 0], current_a: [2.5, 2.5, 0.1], power_w: [0, 10, 0] },
        { command: "voltage", label: "move_voltage(12000)", speed_rpm: [0, 150], torque_nm: [1.1, 0], current_a: [2.5, 0.2], power_w: [0, 0] },
      ],
    };
    const [torque, current, power] = motorCharts(curves);
    expect(torque.x).toEqual([0, 100, 150, 200]);
    expect(torque.series.map((s) => [s.label, s.slot])).toEqual([
      ["move_velocity(max)", 1],
      ["move_voltage(12000)", 2],
    ]);
    expect(torque.series[1].values).toEqual([1.1, undefined, 0, undefined]);
    expect(current.refs).toEqual([{ axis: "y", value: 2.5, label: "current limit 2.5 A" }]);
    expect([power.title, power.unit]).toEqual(["Output power", "W"]);
  });

  it("draws each friction's true path solid and its odometry dashed, in one color", () => {
    const drift: Drift = { left: 1, right: 0.4, seconds: 1.5, runs: [{ lateral_mu: 0.4, true: [[0, 0], [1, 1]], odometry: [[0, 0], [1, 2]], final_error_in: 1 }] };
    const [truth, odometry] = driftPaths(drift);
    expect([truth.slot, truth.dash, truth.key]).toEqual([1, undefined, undefined]);
    expect([odometry.slot, odometry.dash, odometry.key]).toEqual([1, [6, 4], false]); // not in the legend twice
  });

  it("draws the truth in ink and each localizer in its own color, with their errors", () => {
    const run: Odometry = {
      script: "gentle",
      noise: null,
      seed: 0,
      time_s: [0, 0.01],
      truth: [
        [0, 0, 0],
        [1, 0, 0],
      ],
      estimates: [
        { name: "drive encoders", path: [[0, 0, 0], [1, 1, 0]], position_error_in: [0, 1], heading_error_deg: [0, 2], final_in: 1, final_deg: 2, worst_in: 1 },
      ],
    }; // prettier-ignore
    const paths = odometryPaths(run);
    expect(paths.map((p) => [p.label, p.slot])).toEqual([
      ["true path", null],
      ["drive encoders", 1],
    ]);
    expect(odometryCharts(run).map((c) => [c.title, c.unit, c.series[0].values])).toEqual([
      ["Position error", "in", [0, 1]],
      ["Heading error", "°", [0, 2]],
    ]);
  });

  it("takes up to three roller frictions, and drives only differential robots in an arc", () => {
    expect(parseFrictions("0.4, 0.2 0.1")).toEqual([0.4, 0.2, 0.1]);
    expect(parseFrictions("0.4, 0.2, 0.1, 0.05")).toBeNull();
    expect(parseFrictions("0.4, x")).toBeNull();
    expect(parseFrictions("")).toBeNull();
    const robot = (detail: string) => ({ kind: "robot", path: "r.yaml", name: "r", detail, problem: "" }) as WorkspaceItem;
    expect(isDifferential(robot("differential, 6 drive motors"))).toBe(true);
    expect(isDifferential(robot("mecanum, 4 drive motors"))).toBe(false);
  });
});

describe("the Bench page", () => {
  const row = (localizer: string, controller: string, final: number | null) => ({ localizer, controller, final_error_in: final, loc_error_final_in: null });
  const result = {
    combos: [
      { localizer: "tracking wheels + IMU", controller: "pure pursuit" },
      { localizer: "robot code", controller: "LemLib" },
    ],
    rows: [row("tracking wheels + IMU", "pure pursuit", 1), row("tracking wheels + IMU", "pure pursuit", 3), row("robot code", "LemLib", 2)],
    scenario: { tolerance_in: 2 },
  } as unknown as BenchResult;

  it("names a PROS project's combination by its controller", () => {
    expect(comboLabel(result.combos[0])).toBe("tracking wheels + IMU / pure pursuit");
    expect(comboLabel(result.combos[1])).toBe("LemLib (its own localization)");
  });

  it("charts each metric's distribution, a line per combination", () => {
    const charts = ecdfCharts(result);
    expect(charts.map((c) => c.id)).toEqual(["final_error_in"]); // the others have no values
    const [final] = charts;
    expect(final.x).toEqual([1, 2, 3]);
    expect(final.series.map((s) => s.values)).toEqual([
      [0.5, 0.5, 1],
      [0, 1, 1],
    ]);
    expect(final.refs).toEqual([{ axis: "x", value: 2, label: "tolerance 2 in" }]);
    expect(xUnitOf(final)).toBe("in");
    expect(meanP95({ mean: 1.234, median: 1, p95: 2.5, max: 3 })).toBe("1.23 / 2.50");
    expect(meanP95(null)).toBe("—");
    expect([percent(0.95), percent(null)]).toEqual(["95%", "—"]);
  });
});

describe("the Calibrate page", () => {
  it("charts each channel as logged and as simulated, the unit out of the title", () => {
    const result = {
      panels: [
        {
          title: "left motor (port 1) velocity, rpm",
          unit: "rpm",
          time_s: [0, 0.01],
          series: [
            { name: "robot log", values: [0, 1] },
            { name: "simulated, before the fit", values: [0, 2] },
            { name: "simulated", values: [0, 1.1] },
          ],
        },
        { title: "IMU heading rate, deg/s (clockwise +)", unit: "deg/s", time_s: [0], series: [] },
      ],
    } as unknown as CalibrationResult;
    const [motor, imu] = calibrationCharts(result);
    expect([motor.title, motor.unit]).toEqual(["left motor (port 1) velocity", "rpm"]);
    expect([imu.title, imu.unit]).toEqual(["IMU heading rate", "deg/s (clockwise +)"]);
    expect(motor.series.map((s) => [s.label, s.slot, s.dash])).toEqual([
      ["robot log", 3, undefined],
      ["simulated, before the fit", 2, [6, 4]],
      ["simulated", 1, undefined],
    ]);
  });

  it("says how sure the fit is of a value", () => {
    expect(uncertainty(0.0234)).toBe("±2.3%");
    expect(uncertainty(0.0001)).toBe("±0.1%");
    expect(uncertainty(0.7)).toBe("poorly determined by this log");
  });
});

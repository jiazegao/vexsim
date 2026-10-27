import { describe, expect, it } from "vitest";
import type { RunConfiguration, Sweep, SweepTrial } from "../src/protocol";
import { emptyForm, formToSweep, missingRuns, seedsOf, sweepTable, sweepToForm, traceCharts, trialCount, trialName, variationLabel, variationsOf } from "../src/sweeps";

const SWEEP: Sweep = {
  name: "1239E: localization",
  description: "",
  runs: ["1239E: Left 40", "1239E: Right 40"],
  vary: { VEXSIM_TRACKING: ["rcl+mcl", "odom"] },
  seeds: 3,
  first_seed: 0,
  placement_sd: [0.5, 0.5, 1],
  max_seconds: 75,
};

function trial(run: string, variation: string, seed: number, patch: Partial<SweepTrial> = {}): SweepTrial {
  return {
    index: 0,
    run,
    variation,
    env: { VEXSIM_TRACKING: variation },
    seed,
    start: [60, 0, 0],
    spec: { robot: "r.yaml" },
    finished: true,
    error: null,
    seconds: 15,
    end: [0, 0, 0],
    end_estimate: [0, 0, 0],
    mean_in: 1,
    max_in: 5,
    final_in: 1,
    max_deg: 2,
    trace: [0, 1, 2],
    wall_s: 3,
    ...patch,
  };
}

describe("a sweep's form", () => {
  it("round-trips a sweep", () => {
    const form = sweepToForm(SWEEP);
    expect(form.vary).toEqual([{ key: "VEXSIM_TRACKING", values: "rcl+mcl, odom" }]);
    expect(formToSweep(form)).toEqual({ sweep: SWEEP });
  });

  it("says what's wrong with it", () => {
    const form = sweepToForm(SWEEP);
    const error = (patch: Partial<typeof form>) => {
      const checked = formToSweep({ ...form, ...patch });
      return "error" in checked ? checked.error : null;
    };
    expect(error({ name: " " })).toBe("Give the sweep a name.");
    expect(error({ runs: [] })).toBe("Pick at least one saved run.");
    expect(error({ vary: [{ key: "NOT OK", values: "a" }] })).toMatch(/isn't an environment variable's name/);
    expect(error({ vary: [{ key: "A", values: " , " }] })).toBe("Give A at least one value.");
    expect(error({ vary: [{ key: "A", values: "1" }, { key: "A", values: "2" }] })).toBe("A is varied twice.");
    expect(error({ vary: [{ key: "", values: "" }] })).toBeNull(); // an empty row is left out
    expect(error({ seeds: "2.5" })).toMatch(/Seeds/);
    expect(error({ placement: ["-1", "0", "0"] })).toMatch(/Placement/);
    expect(error({ maxSeconds: "0" })).toMatch(/time limit/);
    expect(error({ seeds: "1000", vary: [{ key: "A", values: "a, b, c" }] })).toBe("That's 6000 trials; a sweep runs at most 5000.");
    expect(formToSweep(emptyForm())).toEqual({ error: "Give the sweep a name." });
  });

  it("varies every combination, named as vexsim names them", () => {
    const both: Sweep = { ...SWEEP, vary: { A: ["1", "2"], B: ["x", "y"] } };
    expect(variationsOf(both).map((v) => v.label)).toEqual(["A=1, B=x", "A=1, B=y", "A=2, B=x", "A=2, B=y"]);
    expect(variationsOf({ ...SWEEP, vary: {} })).toEqual([{ label: "as saved", env: {} }]);
    expect(variationLabel({ VEXSIM_TRACKING: "odom" })).toBe("odom");
    expect(trialCount(SWEEP)).toBe(2 * 2 * 3);
    const saved = [{ name: "1239E: Left 40", robot: "r.yaml" }] as RunConfiguration[];
    expect(missingRuns(SWEEP, saved)).toEqual(["1239E: Right 40"]);
  });
});

describe("a sweep's results", () => {
  const trials = [
    trial("1239E: Left 40", "rcl+mcl", 0, { mean_in: 1, max_in: 4, final_in: 0.5, trace: [0, 1, 5] }),
    trial("1239E: Left 40", "rcl+mcl", 1, { mean_in: 2, max_in: 6, final_in: 1.5, seconds: 16 }),
    trial("1239E: Left 40", "odom", 0, { mean_in: 4, max_in: 7, final_in: 6, finished: false, trace: [0, 2] }),
    trial("1239E: Right 40", "odom", 0, { error: "it broke", finished: false, mean_in: null, max_in: null, final_in: null, seconds: null }),
  ];
  const labels = ["rcl+mcl", "odom"];

  it("averages each run's errors over the seeds, per variation, and marks the best", () => {
    const [left, right] = sweepTable(trials, SWEEP.runs, labels);
    expect(left.cells[0]).toEqual({ trials: 2, unfinished: 0, failed: 0, mean: 1.5, max: 5, final: 1 });
    expect(left.cells[1]).toMatchObject({ trials: 1, unfinished: 1, mean: 4 });
    expect(left.best).toBe(0);
    expect(left.seconds).toBeCloseTo(15.333, 3);
    expect(right.cells[0].trials).toBe(0); // not done yet
    expect(right.cells[1]).toMatchObject({ trials: 1, failed: 1, mean: null });
    expect(right.best).toBeNull();
    expect(sweepTable(trials, SWEEP.runs, ["odom"])[0].best).toBeNull(); // nothing to compare
  });

  it("charts one seed's error over time, a chart per run on one scale", () => {
    const { charts, top } = traceCharts(trials, SWEEP.runs, labels, 0, 0.1);
    expect(charts.map((c) => c.title)).toEqual(SWEEP.runs);
    expect(charts[0].x).toEqual([0, 0.1, 0.2]);
    expect(charts[0].series.map((s) => [s.label, s.slot, s.values])).toEqual([
      ["rcl+mcl", 1, [0, 1, 5]],
      ["odom", 2, [0, 2]],
    ]);
    expect(top).toBeCloseTo(5.25);
    expect(seedsOf(trials)).toEqual([0, 1]);
    expect(trialName(trials[2], true)).toBe("1239E: Left 40, odom, seed 0");
    expect(trialName(trials[2], false)).toBe("1239E: Left 40, seed 0");
  });
});

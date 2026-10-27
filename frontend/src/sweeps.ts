// Sweeps on the Sweeps page: the form that edits one, its variations and trials, and what
// its results show: per saved run and variation, the pose error averaged over the seeds,
// and the error over time.

import type { ChartData } from "./analysis";
import { MAX_SERIES } from "./plots";
import type { RunConfiguration, Sweep, SweepTrial, SweepVariation } from "./protocol";

export const MAX_TRIALS = 5000;
const ENV_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;

export interface SweepForm {
  name: string;
  description: string;
  runs: string[];
  vary: { key: string; values: string }[]; // values separated by commas
  seeds: string;
  firstSeed: string;
  placement: [string, string, string]; // x, y (in), heading (deg): standard deviations
  maxSeconds: string;
}

export function emptyForm(): SweepForm {
  return { name: "", description: "", runs: [], vary: [], seeds: "3", firstSeed: "0", placement: ["0.5", "0.5", "1"], maxSeconds: "60" };
}

export function sweepToForm(sweep: Sweep): SweepForm {
  return {
    name: sweep.name,
    description: sweep.description ?? "",
    runs: [...sweep.runs],
    vary: Object.entries(sweep.vary ?? {}).map(([key, values]) => ({ key, values: values.join(", ") })),
    seeds: String(sweep.seeds ?? 3),
    firstSeed: String(sweep.first_seed ?? 0),
    placement: (sweep.placement_sd ?? [0, 0, 0]).map(String) as [string, string, string],
    maxSeconds: String(sweep.max_seconds ?? 60),
  };
}

function whole(text: string, low: number, high: number): number | null {
  const value = Number(text);
  return text.trim() !== "" && Number.isInteger(value) && value >= low && value <= high ? value : null;
}

/** The sweep a form describes, or what's wrong with it. */
export function formToSweep(form: SweepForm): { sweep: Sweep } | { error: string } {
  const name = form.name.trim();
  if (!name) return { error: "Give the sweep a name." };
  if (name.length > 80) return { error: "The name is too long (80 characters at most)." };
  if (form.runs.length === 0) return { error: "Pick at least one saved run." };
  const vary: Record<string, string[]> = {};
  for (const row of form.vary) {
    const key = row.key.trim();
    const values = row.values
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
    if (!key && values.length === 0) continue; // an empty row
    if (!ENV_NAME.test(key)) return { error: `"${key}" isn't an environment variable's name (letters, digits and _).` };
    if (key in vary) return { error: `${key} is varied twice.` };
    if (values.length === 0) return { error: `Give ${key} at least one value.` };
    vary[key] = values;
  }
  const seeds = whole(form.seeds, 1, 1000);
  if (seeds === null) return { error: "Seeds: a whole number from 1 to 1000." };
  const firstSeed = whole(form.firstSeed, 0, 2 ** 31);
  if (firstSeed === null) return { error: "The first seed is a whole number, 0 or more." };
  const placement = form.placement.map(Number);
  if (placement.some((v, i) => form.placement[i].trim() === "" || !Number.isFinite(v) || v < 0)) {
    return { error: "Placement errors are standard deviations: numbers, 0 or more." };
  }
  const maxSeconds = Number(form.maxSeconds);
  if (!(maxSeconds > 0 && maxSeconds <= 3600)) return { error: "The time limit is more than 0 and at most 3600 s." };
  const sweep: Sweep = {
    name,
    description: form.description.trim(),
    runs: [...form.runs],
    vary,
    seeds,
    first_seed: firstSeed,
    placement_sd: placement as [number, number, number],
    max_seconds: maxSeconds,
  };
  const count = trialCount(sweep);
  if (count > MAX_TRIALS) return { error: `That's ${count} trials; a sweep runs at most ${MAX_TRIALS}.` };
  return { sweep };
}

/** What a variation is called, as vexsim names it: its value when one variable varies. */
export function variationLabel(env: Record<string, string>): string {
  const entries = Object.entries(env);
  if (entries.length === 0) return "as saved";
  if (entries.length === 1) return entries[0][1];
  return entries.map(([k, v]) => `${k}=${v}`).join(", ");
}

/** Every combination of the varied values, in vexsim's order. */
export function variationsOf(sweep: Sweep): SweepVariation[] {
  let combos: Record<string, string>[] = [{}];
  for (const [key, values] of Object.entries(sweep.vary ?? {})) {
    combos = combos.flatMap((env) => values.map((value) => ({ ...env, [key]: value })));
  }
  return combos.map((env) => ({ label: variationLabel(env), env }));
}

export function trialCount(sweep: Sweep): number {
  return sweep.runs.length * variationsOf(sweep).length * (sweep.seeds ?? 3);
}

/** The saved runs a sweep names that aren't saved (any more). */
export function missingRuns(sweep: Sweep, configurations: RunConfiguration[]): string[] {
  const names = new Set(configurations.map((c) => c.name));
  return sweep.runs.filter((run) => !names.has(run));
}

// --- results ---------------------------------------------------------------------------

export interface Cell {
  trials: number; // done so far
  unfinished: number; // the program didn't finish in time (or failed)
  failed: number;
  mean: number | null; // averaged over the seeds: mean, max and final position error (in)
  max: number | null;
  final: number | null;
}

export interface TableRow {
  run: string;
  seconds: number | null; // how long the program ran, averaged
  cells: Cell[]; // one per variation, in order
  best: number | null; // the variation with the lowest mean error
}

function average(values: (number | null)[]): number | null {
  const present = values.filter((v): v is number => v !== null && Number.isFinite(v));
  return present.length ? present.reduce((a, b) => a + b, 0) / present.length : null;
}

/** Per saved run and variation: the errors averaged over the seeds so far. */
export function sweepTable(trials: SweepTrial[], runs: string[], variations: string[]): TableRow[] {
  return runs.map((run) => {
    const mine = trials.filter((t) => t.run === run);
    const cells = variations.map((variation): Cell => {
      const these = mine.filter((t) => t.variation === variation);
      return {
        trials: these.length,
        unfinished: these.filter((t) => !t.finished).length,
        failed: these.filter((t) => t.error).length,
        mean: average(these.map((t) => t.mean_in)),
        max: average(these.map((t) => t.max_in)),
        final: average(these.map((t) => t.final_in)),
      };
    });
    let best: number | null = null;
    cells.forEach((cell, i) => {
      if (cell.mean !== null && (best === null || cell.mean < (cells[best].mean ?? Infinity))) best = i;
    });
    return { run, seconds: average(mine.map((t) => t.seconds)), cells, best: variations.length > 1 ? best : null };
  });
}

/** For one seed: a chart per saved run of its position error over time, a line per
 * variation (the first MAX_SERIES), all on one error scale. */
export function traceCharts(trials: SweepTrial[], runs: string[], variations: string[], seed: number, step: number): { charts: ChartData[]; top: number } {
  const shown = variations.slice(0, MAX_SERIES);
  let top = 0;
  const charts = runs.map((run, r): ChartData => {
    const lines = shown.map((variation) => trials.find((t) => t.run === run && t.variation === variation && t.seed === seed)?.trace ?? []);
    const length = Math.max(0, ...lines.map((l) => l.length));
    for (const line of lines) for (const v of line) if (v !== null && v > top) top = v;
    return {
      id: `run-${r}`,
      title: run,
      unit: "in",
      digits: 2,
      x: Array.from({ length }, (_, k) => +(k * step).toFixed(3)),
      series: shown.map((variation, i) => ({ label: variation, values: lines[i], slot: i + 1 })),
    };
  });
  return { charts, top: top > 0 ? top * 1.05 : 1 };
}

/** The seeds the trials so far have. */
export function seedsOf(trials: SweepTrial[]): number[] {
  return [...new Set(trials.map((t) => t.seed))].sort((a, b) => a - b);
}

/** A trial's name: its saved run, variation and seed. */
export function trialName(trial: SweepTrial, varied: boolean): string {
  return `${trial.run}${varied ? `, ${trial.variation}` : ""}, seed ${trial.seed}`;
}

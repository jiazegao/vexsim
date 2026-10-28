// The run form: text fields as typed, turned into a RunSpec (or a reason it can't be),
// and remembered per workspace in this browser.

import type { RunSpec, WorkspaceItem } from "./protocol";

export const MODES = ["autonomous", "driver", "match", "skills"] as const;
export const NOISE = ["ideal", "default", "harsh"] as const;
export const STICKS = ["tank", "arcade"] as const;
export type Mode = (typeof MODES)[number];
export type Noise = (typeof NOISE)[number];
export type Sticks = (typeof STICKS)[number];

export interface RunForm {
  config: string; // the saved run configuration it was filled from; "" = none
  robot: string;
  field: string; // "" = an empty field
  program: string; // "" = none: the controller drives
  routine: string; // a PROS project's routine, run inside autonomous(); "" = as the project picks
  route: string; // or a route of the project's (routes/*.yaml), run as a routine is; "" = none
  mode: "" | Mode; // "" = the program's default
  x: string;
  y: string;
  heading: string;
  seed: string;
  noise: "" | Noise; // "" = as each sensor is configured
  input: string; // "" = none
  follow: string; // a log whose path a virtual driver follows; "" = none
  sticks: Sticks; // how the program drives from the sticks (when following)
  curve: string; // its LemLib drive curve "deadband, min output, curve"; "" = none
  following: boolean; // a saved run that follows any log it's given (follow, sticks, curve)
  env: string; // KEY=VALUE, one per line
  busy: string; // PROS projects: seconds a task may run without blocking (0 = no limit)
}

export function emptyForm(): RunForm {
  return {
    config: "",
    robot: "",
    field: "",
    program: "",
    routine: "",
    route: "",
    mode: "",
    x: "0",
    y: "0",
    heading: "0",
    seed: "0",
    noise: "",
    input: "",
    follow: "",
    sticks: "tank",
    curve: "",
    following: false,
    env: "",
    busy: "5",
  };
}

function number(text: string, name: string): number {
  const value = Number(text.trim());
  if (text.trim() === "" || !Number.isFinite(value)) throw new Error(`${name} must be a number`);
  return value;
}

/** The spec the form describes, or why it doesn't describe one. */
export function formToSpec(form: RunForm): { spec: RunSpec } | { error: string } {
  if (!form.robot) return { error: "Pick a robot" };
  try {
    const env: Record<string, string> = {};
    for (const raw of form.env.split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      const at = line.indexOf("=");
      if (at <= 0) throw new Error(`environment lines are KEY=VALUE, not "${line}"`);
      env[line.slice(0, at).trim()] = line.slice(at + 1);
    }
    const seed = number(form.seed, "Seed");
    if (!Number.isInteger(seed)) throw new Error("Seed must be a whole number");
    const busy = number(form.busy, "Busy timeout");
    if (busy < 0) throw new Error("Busy timeout can't be negative");
    let curve: [number, number, number] | null = null;
    if (form.curve.trim()) {
      const values = form.curve.split(",").map((v) => (v.trim() === "" ? NaN : Number(v)));
      if (values.length !== 3 || !values.every(Number.isFinite)) throw new Error("The drive curve is three numbers: deadband, min output, curve (15, 20, 1.05)");
      curve = values as [number, number, number];
    }
    const following = !!form.follow || form.following;
    const spec: RunSpec = {
      robot: form.robot,
      program: form.program || null,
      routine: (form.program && !form.route && form.routine) || null,
      ...(form.program && form.route ? { route: form.route } : {}),
      field: form.field || null,
      mode: form.mode || null,
      start: [number(form.x, "Start x"), number(form.y, "Start y"), number(form.heading, "Heading")],
      seed,
      noise: form.noise || null,
      input: form.input || null,
      follow: following ? { log: form.follow || null, sticks: form.sticks, curve } : null,
      env,
      busy_timeout: busy,
    };
    return { spec };
  } catch (error) {
    return { error: (error as Error).message };
  }
}

export function specToForm(spec: RunSpec, config = ""): RunForm {
  const [x, y, heading] = spec.start ?? [0, 0, 0];
  return {
    config,
    robot: spec.robot,
    field: spec.field ?? "",
    program: spec.program ?? "",
    routine: spec.routine ?? "",
    route: spec.route ?? "",
    mode: (spec.mode ?? "") as RunForm["mode"],
    x: String(x),
    y: String(y),
    heading: String(heading),
    seed: String(spec.seed ?? 0),
    noise: (spec.noise ?? "") as RunForm["noise"],
    input: spec.input ?? "",
    follow: spec.follow?.log ?? "",
    sticks: spec.follow?.sticks ?? "tank",
    curve: spec.follow?.curve ? spec.follow.curve.join(", ") : "",
    following: !!spec.follow,
    env: Object.entries(spec.env ?? {})
      .map(([k, v]) => `${k}=${v}`)
      .join("\n"),
    busy: String(spec.busy_timeout ?? 5),
  };
}

/** A spec with its defaults filled in and its keys in order, to compare two. */
function canonical(spec: RunSpec): string {
  return JSON.stringify({
    robot: spec.robot,
    program: spec.program || null,
    routine: spec.routine || null,
    route: spec.route || null,
    field: spec.field || null,
    mode: spec.mode || null,
    start: (spec.start ?? [0, 0, 0]).map(Number),
    seed: spec.seed ?? 0,
    noise: spec.noise || null,
    input: spec.input || null,
    follow: spec.follow ? [spec.follow.log || null, spec.follow.sticks ?? "tank", spec.follow.curve?.map(Number) ?? null] : null,
    env: Object.entries(spec.env ?? {}).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)),
    busy_timeout: spec.busy_timeout ?? 5,
  });
}

/** Whether the form still describes `spec` (unchanged since it was filled from it). */
export function sameRun(form: RunForm, spec: RunSpec): boolean {
  const result = formToSpec(form);
  return "spec" in result && canonical(result.spec) === canonical(spec);
}

/** The form with picks that no longer exist in the workspace cleared, and a robot picked. */
export function reconcile(form: RunForm, items: WorkspaceItem[]): RunForm {
  const has = (kinds: string[], path: string) =>
    items.some((item) => kinds.includes(item.kind) && item.path === path);
  const next = { ...form };
  if (next.robot && !has(["robot"], next.robot)) next.robot = "";
  if (next.field && !has(["field"], next.field)) next.field = "";
  if (next.program && !has(["program", "project"], next.program)) next.program = "";
  if (next.route && !has(["route"], next.route)) next.route = "";
  if (next.input && !has(["input"], next.input)) next.input = "";
  if (next.follow && !has(["mcllog"], next.follow)) next.follow = "";
  if (!next.robot) {
    const robot = items.find((item) => item.kind === "robot" && !item.problem);
    if (robot) next.robot = robot.path;
  }
  return next;
}

const KEY = "vexsim.runForm:";

export function loadForm(workspace: string): RunForm | null {
  try {
    const text = localStorage.getItem(KEY + workspace);
    return text ? { ...emptyForm(), ...(JSON.parse(text) as Partial<RunForm>) } : null;
  } catch {
    return null; // storage off (private window) or garbled: start fresh
  }
}

export function saveForm(workspace: string, form: RunForm): void {
  try {
    localStorage.setItem(KEY + workspace, JSON.stringify(form));
  } catch {
    // storage off: the form just isn't remembered
  }
}

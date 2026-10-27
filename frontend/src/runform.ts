// The run form: text fields as typed, turned into a RunSpec (or a reason it can't be),
// and remembered per workspace in this browser.

import type { RunSpec, WorkspaceItem } from "./protocol";

export const MODES = ["autonomous", "driver", "match", "skills"] as const;
export const NOISE = ["ideal", "default", "harsh"] as const;
export type Mode = (typeof MODES)[number];
export type Noise = (typeof NOISE)[number];

export interface RunForm {
  robot: string;
  field: string; // "" = an empty field
  program: string; // "" = none: the controller drives
  mode: "" | Mode; // "" = the program's default
  x: string;
  y: string;
  heading: string;
  seed: string;
  noise: "" | Noise; // "" = as each sensor is configured
  input: string; // "" = none
  env: string; // KEY=VALUE, one per line
}

export function emptyForm(): RunForm {
  return {
    robot: "",
    field: "",
    program: "",
    mode: "",
    x: "0",
    y: "0",
    heading: "0",
    seed: "0",
    noise: "",
    input: "",
    env: "",
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
    const spec: RunSpec = {
      robot: form.robot,
      program: form.program || null,
      field: form.field || null,
      mode: form.mode || null,
      start: [number(form.x, "Start x"), number(form.y, "Start y"), number(form.heading, "Heading")],
      seed,
      noise: form.noise || null,
      input: form.input || null,
      env,
    };
    return { spec };
  } catch (error) {
    return { error: (error as Error).message };
  }
}

export function specToForm(spec: RunSpec): RunForm {
  const [x, y, heading] = spec.start ?? [0, 0, 0];
  return {
    robot: spec.robot,
    field: spec.field ?? "",
    program: spec.program ?? "",
    mode: (spec.mode ?? "") as RunForm["mode"],
    x: String(x),
    y: String(y),
    heading: String(heading),
    seed: String(spec.seed ?? 0),
    noise: (spec.noise ?? "") as RunForm["noise"],
    input: spec.input ?? "",
    env: Object.entries(spec.env ?? {})
      .map(([k, v]) => `${k}=${v}`)
      .join("\n"),
  };
}

/** The form with picks that no longer exist in the workspace cleared, and a robot picked. */
export function reconcile(form: RunForm, items: WorkspaceItem[]): RunForm {
  const has = (kinds: string[], path: string) =>
    items.some((item) => kinds.includes(item.kind) && item.path === path);
  const next = { ...form };
  if (next.robot && !has(["robot"], next.robot)) next.robot = "";
  if (next.field && !has(["field"], next.field)) next.field = "";
  if (next.program && !has(["program", "project"], next.program)) next.program = "";
  if (next.input && !has(["input"], next.input)) next.input = "";
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

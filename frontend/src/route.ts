// The autonomous maker (PLAN.md 13.2): a route's steps as the server reads them, where each
// one is planned to end, as LemLib's targets say, and the values the editor writes back.
// Poses here are LemLib's: x, y (inches) and theta, degrees clockwise from +y.

import type { MotionHintInfo, RouteData, RouteFunctionInfo, RouteStepData } from "./protocol";

export type LemPose = readonly [number, number, number];
export type Point = readonly [number, number];

export const MOTIONS = ["move_to_point", "move_to_pose", "turn_to_heading", "turn_to_point", "swing_to_heading", "swing_to_point"] as const;
export const PAUSES = ["wait", "wait_until", "wait_until_done"] as const;
export type Motion = (typeof MOTIONS)[number];

/** Each motion's own key: what it's written with, and its options in the order LemLib's
 * params structs have them (the order they're written in). */
export const MOTION_INFO: Record<Motion, { target: "point" | "pose" | "heading"; options: readonly string[]; swing?: boolean; wholeSpeeds?: boolean; title: string }> = {
  move_to_point: { target: "point", options: ["forwards", "max_speed", "min_speed", "early_exit"], title: "Move to a point" },
  move_to_pose: { target: "pose", options: ["forwards", "horizontal_drift", "lead", "max_speed", "min_speed", "early_exit"], title: "Move to a pose" },
  turn_to_heading: { target: "heading", options: ["direction", "max_speed", "min_speed", "early_exit"], wholeSpeeds: true, title: "Turn to a heading" },
  turn_to_point: { target: "point", options: ["forwards", "direction", "max_speed", "min_speed", "early_exit"], wholeSpeeds: true, title: "Turn to face a point" },
  swing_to_heading: { target: "heading", options: ["direction", "max_speed", "min_speed", "early_exit"], swing: true, title: "Swing to a heading" },
  swing_to_point: { target: "point", options: ["forwards", "direction", "max_speed", "min_speed", "early_exit"], swing: true, title: "Swing to face a point" },
};

/** LemLib's defaults for the options (as its params structs have them). */
export const OPTION_DEFAULTS: Record<string, number | boolean | string> = {
  forwards: true,
  horizontal_drift: 0,
  lead: 0.6,
  direction: "auto",
  max_speed: 127,
  min_speed: 0,
  early_exit: 0,
  async: true,
};

export function isMotion(kind: string): kind is Motion {
  return (MOTIONS as readonly string[]).includes(kind);
}

const DEG = Math.PI / 180;
const NEAR = 1e-6;

/** The direction from `from` to `to` as LemLib's theta: degrees clockwise from +y, [0, 360). */
export function bearing(from: Point, to: Point): number {
  return wrap360(Math.atan2(to[0] - from[0], to[1] - from[1]) / DEG);
}

export function wrap360(degrees: number): number {
  const wrapped = ((degrees % 360) + 360) % 360;
  return Math.abs(wrapped - 360) < 1e-9 ? 0 : wrapped;
}

/** An angle in (-180, 180]. */
export function shortest(degrees: number): number {
  const wrapped = wrap360(degrees);
  return wrapped > 180 ? wrapped - 360 : wrapped;
}

/** How far a turn from `from` to `to` goes (clockwise positive), the way it's told to:
 * `auto` the short way. */
export function turnAmount(from: number, to: number, direction: string): number {
  const delta = wrap360(to - from);
  if (direction === "cw") return delta;
  if (direction === "ccw") return delta === 0 ? 0 : delta - 360;
  return shortest(to - from);
}

/** `point` turned `clockwise` degrees about `center`. */
export function rotateAbout(point: Point, center: Point, clockwise: number): [number, number] {
  const c = Math.cos(clockwise * DEG);
  const s = Math.sin(clockwise * DEG);
  const dx = point[0] - center[0];
  const dy = point[1] - center[1];
  return [center[0] + c * dx + s * dy, center[1] - s * dx + c * dy];
}

/** Straight ahead, and to the right, of a robot facing `theta`. */
export function ahead(theta: number): [number, number] {
  return [Math.sin(theta * DEG), Math.cos(theta * DEG)];
}
function rightOf(theta: number): [number, number] {
  return [Math.cos(theta * DEG), -Math.sin(theta * DEG)];
}

function arc(from: Point, center: Point, clockwise: number): Point[] {
  const count = Math.max(2, Math.ceil(Math.abs(clockwise) / 6));
  return Array.from({ length: count + 1 }, (_, i) => rotateAbout(from, center, (clockwise * i) / count));
}

function curve(from: Point, control: Point, to: Point): Point[] {
  return Array.from({ length: 25 }, (_, i) => {
    const t = i / 24;
    const a = (1 - t) * (1 - t);
    const b = 2 * (1 - t) * t;
    const c = t * t;
    return [a * from[0] + b * control[0] + c * to[0], a * from[1] + b * control[1] + c * to[1]] as const;
  });
}

export interface Planned {
  pose: LemPose; // where it ends
  path: Point[]; // the way there, from where the step before ended (none: it stays put)
  known: boolean; // false: the planner can't tell (one of the team's functions that doesn't say)
  ran: boolean; // its end is where the last run's robot was, which the plan goes on from
}

/** Where each step of `route` is planned to end, and the way there: LemLib's targets for its
 * motions (a swing turns about its locked side, `track` inches across), and for the team's
 * functions, what their `// vexsim:` comments say. One that doesn't say stays put, unless the
 * last run (`ran`: each step's end in it, or null) says where it ended. */
export function plan(route: RouteData, functions: readonly RouteFunctionInfo[], track: number, ran: readonly (LemPose | null)[] = []): Planned[] {
  const byName = new Map(functions.map((f) => [f.name, f]));
  let at: LemPose = route.start;
  return route.steps.map((step, k) => {
    const made = planStep(at, step, byName.get(step.function ?? ""), track);
    let planned: Planned = { ...made, ran: false };
    if (!made.known && ran[k]) planned = { pose: ran[k]!, path: [], known: false, ran: true };
    at = planned.pose;
    return planned;
  });
}

function option(step: RouteStepData, name: string): number | boolean | string {
  return step.options[name] ?? OPTION_DEFAULTS[name];
}

/** One step from `at`: where it ends and the way there. */
export function planStep(at: LemPose, step: RouteStepData, fn: RouteFunctionInfo | undefined, track: number): Omit<Planned, "ran"> {
  const here: Point = [at[0], at[1]];
  const forwards = option(step, "forwards") !== false;
  const facing = (to: Point, from: Point = here) => (Math.hypot(to[0] - from[0], to[1] - from[1]) < NEAR ? at[2] : wrap360(bearing(from, to) + (forwards ? 0 : 180)));
  const [a, b, c] = step.target;
  switch (step.kind) {
    case "move_to_point": {
      const to: Point = [a, b];
      return { pose: [a, b, facing(to)], path: [here, to], known: true };
    }
    case "move_to_pose":
      return { pose: [a, b, wrap360(c)], path: boomerang(here, [a, b, c], Number(option(step, "lead")), forwards), known: true };
    case "turn_to_heading":
      return { pose: [at[0], at[1], wrap360(a)], path: [], known: true };
    case "turn_to_point":
      return { pose: [at[0], at[1], facing([a, b])], path: [], known: true };
    case "swing_to_heading":
    case "swing_to_point": {
      const side = step.side === "right" ? 1 : -1;
      const pivot: Point = [at[0] + (side * rightOf(at[2])[0] * track) / 2, at[1] + (side * rightOf(at[2])[1] * track) / 2];
      const direction = String(option(step, "direction"));
      let turn = step.kind === "swing_to_heading" ? turnAmount(at[2], a, direction) : turnAmount(at[2], facing([a, b]), direction);
      if (step.kind === "swing_to_point") {
        // facing the point from where the swing ends: a few rounds settle it
        for (let i = 0; i < 6; i++) turn = turnAmount(at[2], facing([a, b], rotateAbout(here, pivot, turn)), direction);
      }
      const end = rotateAbout(here, pivot, turn);
      return { pose: [end[0], end[1], wrap360(at[2] + turn)], path: arc(here, pivot, turn), known: true };
    }
    case "call":
      return fn?.hint ? hinted(at, fn.hint, fn, step) : { pose: at, path: [], known: false };
    case "invalid":
      return { pose: at, path: [], known: false };
    default: // the pauses
      return { pose: at, path: [], known: true };
  }
}

/** LemLib's moveToPose drives at a carrot point `lead` of the way back from the target along
 * its heading: drawn as the curve that makes. */
function boomerang(from: Point, target: LemPose, lead: number, forwards: boolean): Point[] {
  const distance = Math.hypot(target[0] - from[0], target[1] - from[1]);
  const [dx, dy] = ahead(target[2] + (forwards ? 0 : 180));
  const carrot: Point = [target[0] - dx * lead * distance, target[1] - dy * lead * distance];
  return curve(from, carrot, [target[0], target[1]]);
}

/** A call's motion, as its function's `// vexsim:` comment says (unknown if an argument it
 * names has no value). */
function hinted(at: LemPose, hint: MotionHintInfo, fn: RouteFunctionInfo, step: RouteStepData): Omit<Planned, "ran"> {
  const values = hint.args.map((arg) => {
    if (typeof arg === "number") return arg;
    const given = step.args[arg] ?? fn.params.find((p) => p.name === arg)?.value;
    return typeof given === "number" ? given : null;
  });
  if (values.some((v) => v === null)) return { pose: at, path: [], known: false };
  const [a, b, c] = values as number[];
  const here: Point = [at[0], at[1]];
  switch (hint.motion) {
    case "drive": {
      const [dx, dy] = ahead(at[2]);
      const to: Point = [at[0] + dx * a, at[1] + dy * a];
      return { pose: [to[0], to[1], at[2]], path: [here, to], known: true };
    }
    case "turn_by":
      return { pose: [at[0], at[1], wrap360(at[2] + a)], path: [], known: true };
    case "arc": {
      // a radius `a`, turning `b` degrees clockwise: about a center to the right (left, for
      // a turn the other way)
      const side = b >= 0 ? 1 : -1;
      const [rx, ry] = rightOf(at[2]);
      const center: Point = [at[0] + side * rx * a, at[1] + side * ry * a];
      const end = rotateAbout(here, center, b);
      return { pose: [end[0], end[1], wrap360(at[2] + b)], path: arc(here, center, b), known: true };
    }
    case "point":
      return { pose: [a, b, Math.hypot(a - at[0], b - at[1]) < NEAR ? at[2] : bearing(here, [a, b])], path: [here, [a, b]], known: true };
    case "pose":
      return { pose: [a, b, wrap360(c)], path: boomerang(here, [a, b, c], 0.6, true), known: true };
    default: // none: it doesn't move the robot
      return { pose: at, path: [], known: true };
  }
}

/** A pose as vexsim draws it: x, y and heading, degrees counter-clockwise from +x. */
export function toVexsim(pose: LemPose): [number, number, number] {
  return [pose[0], pose[1], wrap360(90 - pose[2])];
}

// --- writing steps ----------------------------------------------------------------------------

export type StepValue = string | Record<string, unknown>;

/** A step as its YAML has it, for the editor to write: `{move_to_point: [24, 0],
 * timeout: 1000}`, `{call: moveForward, args: {inches: 10}}`, `wait_until_done`. */
export function stepValue(step: RouteStepData): StepValue {
  if (step.kind === "wait_until_done") return "wait_until_done";
  if (step.kind === "call") {
    const args = Object.keys(step.args).length ? { args: { ...step.args } } : {};
    return { call: step.function, ...args };
  }
  if (step.kind === "wait" || step.kind === "wait_until") return { [step.kind]: step.target[0] };
  if (!isMotion(step.kind)) return { wait: 0 };
  const info = MOTION_INFO[step.kind];
  const value: Record<string, unknown> = { [step.kind]: info.target === "heading" ? step.target[0] : [...step.target] };
  if (info.swing) value.locked_side = step.side ?? "left";
  value.timeout = step.timeout ?? 1000;
  for (const name of [...info.options, "async"]) if (name in step.options) value[name] = step.options[name];
  return value;
}

/** A timeout that leaves a motion from `at` room to finish: longer the farther it goes and
 * the more it turns (milliseconds, in hundreds). */
export function timeoutFor(step: RouteStepData, at: LemPose, track = 12): number {
  const end = planStep(at, step, undefined, track).pose;
  const distance = Math.hypot(end[0] - at[0], end[1] - at[1]);
  const turn = Math.abs(shortest(end[2] - at[2]));
  const ms = 600 + 40 * distance + 4 * turn;
  return Math.min(5000, Math.max(800, Math.round(ms / 100) * 100));
}

/** A new step of `kind`, to add after `at` (where the robot is then): `target` if it's given,
 * else 24 inches ahead or a quarter turn on. A motion waits until it's done (LemLib's default
 * is to go on at once), so the route runs as it's drawn, one step after another. */
export function newStep(kind: string, at: LemPose, fn?: RouteFunctionInfo, target?: number[]): RouteStepData {
  const base: RouteStepData = { kind, target: [], timeout: null, side: null, options: {}, function: null, args: {}, label: kind };
  const [dx, dy] = ahead(at[2]);
  const round = (v: number) => Math.round(v * 10) / 10;
  const motion = (made: RouteStepData): RouteStepData => {
    const step = { ...made, target: target ?? made.target, options: { async: false } };
    return { ...step, timeout: timeoutFor(step, at) };
  };
  switch (kind) {
    case "move_to_point":
    case "turn_to_point":
    case "swing_to_point":
      return motion({ ...base, target: [round(at[0] + dx * 24), round(at[1] + dy * 24)], side: kind === "swing_to_point" ? "left" : null });
    case "move_to_pose":
      return motion({ ...base, target: [round(at[0] + dx * 24), round(at[1] + dy * 24), round(at[2])] });
    case "turn_to_heading":
    case "swing_to_heading":
      return motion({ ...base, target: [round(wrap360(at[2] + 90))], side: kind === "swing_to_heading" ? "left" : null });
    case "wait":
      return { ...base, target: [250] };
    case "wait_until":
      return { ...base, target: [6] };
    case "call": {
      // its arguments: those it needs, each its default or a start
      const args: Record<string, number | boolean | string> = {};
      for (const param of fn?.params.slice(0, fn.required) ?? []) {
        args[param.name] = param.kind === "bool" ? true : param.kind === "enum" ? (param.values?.[0] ?? "") : param.name.toLowerCase().includes("timeout") ? 1000 : 0;
      }
      return { ...base, function: fn?.name ?? null, args };
    }
    default:
      return base;
  }
}

/** A step in a few words, as the list shows it: `Move to (14, 0) · max 60 · async`. */
export function describe(step: RouteStepData): string {
  const n = (v: number) => String(Number(v.toFixed(2)));
  const extras: string[] = [];
  const opt = step.options;
  if (opt.forwards === false) extras.push("backwards");
  if (opt.max_speed !== undefined) extras.push(`max ${opt.max_speed}`);
  if (opt.min_speed !== undefined) extras.push(`min ${opt.min_speed}`);
  if (opt.early_exit !== undefined) extras.push(`exit ${opt.early_exit} early`);
  if (opt.lead !== undefined) extras.push(`lead ${opt.lead}`);
  if (opt.horizontal_drift !== undefined) extras.push(`drift ${opt.horizontal_drift}`);
  if (opt.direction !== undefined && opt.direction !== "auto") extras.push(String(opt.direction));
  if (isMotion(step.kind)) extras.push(opt.async === false ? "waits" : "async");
  const [a, b, c] = step.target;
  let head: string;
  switch (step.kind) {
    case "move_to_point":
      head = `Move to (${n(a)}, ${n(b)})`;
      break;
    case "move_to_pose":
      head = `Move to (${n(a)}, ${n(b)}) facing ${n(c)}°`;
      break;
    case "turn_to_heading":
      head = `Turn to ${n(a)}°`;
      break;
    case "turn_to_point":
      head = `Turn to face (${n(a)}, ${n(b)})`;
      break;
    case "swing_to_heading":
      head = `Swing to ${n(a)}° on the ${step.side} side`;
      break;
    case "swing_to_point":
      head = `Swing to face (${n(a)}, ${n(b)}) on the ${step.side} side`;
      break;
    case "wait":
      head = `Wait ${n(a)} ms`;
      break;
    case "wait_until":
      head = `Wait until ${n(a)} in along`;
      break;
    case "wait_until_done":
      head = "Wait until the motion is done";
      break;
    case "call": {
      const args = Object.entries(step.args).map(([k, v]) => `${k} ${typeof v === "number" ? n(v) : v}`);
      head = `${step.function}(${args.join(", ")})`;
      break;
    }
    default:
      head = "A step that doesn't read: fix it in the YAML";
  }
  return [head, ...extras].join(" · ");
}

// --- copying steps between routes -------------------------------------------------------------

let clipboard: StepValue[] | null = null;

export function copySteps(steps: StepValue[]): void {
  clipboard = steps.map((step) => structuredClone(step));
}

export function copiedSteps(): StepValue[] | null {
  return clipboard && clipboard.map((step) => structuredClone(step));
}

// --- dragging on the field ----------------------------------------------------------------------

/** What a drag on the field holds: the start (or its heading), a step's target, or its heading. */
export type Grip = { kind: "start" } | { kind: "start-heading" } | { kind: "target"; index: number } | { kind: "heading"; index: number };

/** A drag's value: the start's pose, a target's x and y, or a heading. */
export interface Dragged {
  grip: Grip;
  value: number[];
}

/** `route` as it would be with the drag dropped, for the plan to follow it at once. */
export function withDrag(route: RouteData, dragged: Dragged | null): RouteData {
  if (!dragged) return route;
  const [a, b, c] = dragged.value;
  const { grip } = dragged;
  if (grip.kind === "start" || grip.kind === "start-heading") return { ...route, start: [a, b, c] };
  const steps = route.steps.map((step, i) => {
    if (i !== grip.index) return step;
    if (grip.kind === "target") return { ...step, target: step.kind === "move_to_pose" ? [a, b, step.target[2]] : [a, b] };
    return { ...step, target: step.kind === "move_to_pose" ? [step.target[0], step.target[1], a] : [a] };
  });
  return { ...route, steps };
}

/** The edit a drag makes when it's dropped: the number(s) it moved, written in place. */
export function dropEdit(route: RouteData, dragged: Dragged): { op: "set"; location: string; value: unknown } {
  const moved = withDrag(route, dragged);
  const { grip } = dragged;
  if (grip.kind === "start" || grip.kind === "start-heading") return { op: "set", location: "start", value: [...moved.start] };
  const step = moved.steps[grip.index];
  const value = step.kind === "turn_to_heading" || step.kind === "swing_to_heading" ? step.target[0] : [...step.target];
  return { op: "set", location: `steps[${grip.index}].${step.kind}`, value };
}

/** `to` (a workspace path) as a path from the folder `from` is in: what a route writes for
 * its robot and field. */
export function relativePath(from: string, to: string): string {
  const base = from.split("/").slice(0, -1);
  const target = to.split("/");
  let same = 0;
  while (same < base.length && same < target.length - 1 && base[same] === target[same]) same++;
  return [...base.slice(same).map(() => ".."), ...target.slice(same)].join("/");
}

/** The file a route's name gives it, as the server names it: `Left 40` is `left_40.yaml`. */
export function routeFileName(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return `${slug || "route"}.yaml`;
}

/** Where the server puts a route called `name` in `project`: never over a file in `taken`. */
export function newRoutePath(project: string, name: string, taken: readonly string[]): string {
  const file = routeFileName(name.trim() || "New route");
  const stem = file.slice(0, -".yaml".length);
  const folder = project === "." ? "routes" : `${project}/routes`; // a project at the workspace's root
  let path = `${folder}/${file}`;
  for (let count = 2; taken.includes(path); count++) path = `${folder}/${stem}_${count}.yaml`;
  return path;
}

/** A marker's numbers, a run of three or more as a range: `1–3,5`. */
export function numbersText(numbers: readonly number[]): string {
  const parts: string[] = [];
  for (let i = 0; i < numbers.length; ) {
    let j = i;
    while (j + 1 < numbers.length && numbers[j + 1] === numbers[j] + 1) j++;
    parts.push(j - i >= 2 ? `${numbers[i]}–${numbers[j]}` : numbers.slice(i, j + 1).join(","));
    i = j + 1;
  }
  return parts.join(",");
}

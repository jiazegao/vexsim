// The autonomous maker (PLAN.md 13.2): a route's steps as the server reads them, where each
// one is planned to end, as LemLib's targets say, and the values the editor writes back.
// Poses here are LemLib's: x, y (inches) and theta, degrees clockwise from +y.

import type { MotionHintInfo, RouteData, RouteDriveInfo, RouteFunctionInfo, RouteStepData } from "./protocol";
import type { Limits } from "./trajectory";
import { planArc, planPath } from "./trajectory";

export type LemPose = readonly [number, number, number];
export type Point = readonly [number, number];

/** LemLib's motions, then vexsim's own (vexsim/motions.hpp): an arc, and a RAMSETE path. */
export const MOTIONS = ["move_to_point", "move_to_pose", "turn_to_heading", "turn_to_point", "swing_to_heading", "swing_to_point", "move_arc", "ramsete"] as const;
export const PAUSES = ["wait", "wait_until", "wait_until_done"] as const;
export type Motion = (typeof MOTIONS)[number];

/** Each motion's own key: what it's written with (a point, a pose, a heading, an arc's
 * radius and degrees, or a path's points), and its options in the order its params struct
 * has them (the order they're written in). */
export const MOTION_INFO: Record<Motion, { target: "point" | "pose" | "heading" | "arc" | "path"; options: readonly string[]; swing?: boolean; wholeSpeeds?: boolean; own?: boolean; title: string }> = {
  move_to_point: { target: "point", options: ["forwards", "max_speed", "min_speed", "early_exit"], title: "Move to a point" },
  move_to_pose: { target: "pose", options: ["forwards", "horizontal_drift", "lead", "max_speed", "min_speed", "early_exit"], title: "Move to a pose" },
  turn_to_heading: { target: "heading", options: ["direction", "max_speed", "min_speed", "early_exit"], wholeSpeeds: true, title: "Turn to a heading" },
  turn_to_point: { target: "point", options: ["forwards", "direction", "max_speed", "min_speed", "early_exit"], wholeSpeeds: true, title: "Turn to face a point" },
  swing_to_heading: { target: "heading", options: ["direction", "max_speed", "min_speed", "early_exit"], swing: true, title: "Swing to a heading" },
  swing_to_point: { target: "point", options: ["forwards", "direction", "max_speed", "min_speed", "early_exit"], swing: true, title: "Swing to face a point" },
  move_arc: { target: "arc", options: ["forwards", "max_velocity", "max_accel"], own: true, title: "Arc" },
  ramsete: { target: "path", options: ["forwards", "max_velocity", "max_accel", "end_heading"], own: true, title: "RAMSETE path" },
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

/** Whether `kind` is one of vexsim's own motions, planned on a speed profile. */
export function isOwn(kind: string): boolean {
  return isMotion(kind) && !!MOTION_INFO[kind].own;
}

/** A RAMSETE step's points, each (x, y): its target is them one after another. */
export function pointsOf(step: RouteStepData): Point[] {
  const points: Point[] = [];
  for (let i = 0; i + 1 < step.target.length; i += 2) points.push([step.target[i], step.target[i + 1]]);
  return points;
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
  speeds?: number[]; // vexsim's own motions: the speed (in/s) at each point of the path, every 10 ms
  seconds?: number; // and how long it takes
}

/** Where each step of `route` is planned to end, and the way there: LemLib's targets for its
 * motions (a swing turns about its locked side, `track` inches across), vexsim's own motions
 * as they plan, with the `drive` model's limits, and for the team's functions, what their
 * `// vexsim:` comments say. One that doesn't say stays put, unless the last run (`ran`: each
 * step's end in it, or null) says where it ended. */
export function plan(route: RouteData, functions: readonly RouteFunctionInfo[], track: number, ran: readonly (LemPose | null)[] = [], drive: RouteDriveInfo | null = null): Planned[] {
  const byName = new Map(functions.map((f) => [f.name, f]));
  let at: LemPose = route.start;
  return route.steps.map((step, k) => {
    const made = planStep(at, step, byName.get(step.function ?? ""), track, drive);
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
export function planStep(at: LemPose, step: RouteStepData, fn: RouteFunctionInfo | undefined, track: number, drive: RouteDriveInfo | null = null): Omit<Planned, "ran"> {
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
    case "move_arc":
    case "ramsete":
      return planOwn(at, step, track, drive);
    case "call":
      return fn?.hint ? hinted(at, fn.hint, fn, step) : { pose: at, path: [], known: false };
    case "invalid":
      return { pose: at, path: [], known: false };
    default: // the pauses
      return { pose: at, path: [], known: true };
  }
}

/** The limits one of vexsim's own motions plans within: the `drive` model's (without it, what
 * vexsim/motions.hpp takes for a limit left at 0), and the step's own, and its top speed. */
export function limitsOf(step: RouteStepData, track: number, drive: RouteDriveInfo | null): { limits: Limits; speed: number } {
  const own = (key: string) => (typeof step.options[key] === "number" && (step.options[key] as number) > 0 ? (step.options[key] as number) : null);
  const limits: Limits = {
    maxVelocity: drive?.max_velocity ?? 60,
    maxAccel: own("max_accel") ?? drive?.max_accel ?? 120,
    maxLateralAccel: drive?.max_lateral_accel ?? 20,
    trackWidth: track,
  };
  return { limits, speed: own("max_velocity") ?? limits.maxVelocity };
}

/** One of vexsim's own motions from `at`, as it plans (src/trajectory.ts): the way it goes,
 * and how fast, every 10 ms. */
function planOwn(at: LemPose, step: RouteStepData, track: number, drive: RouteDriveInfo | null): Omit<Planned, "ran"> {
  const { limits, speed } = limitsOf(step, track, drive);
  const forwards = option(step, "forwards") !== false;
  const heading = (90 - at[2]) * DEG; // radians counter-clockwise from +x
  const end = step.options.end_heading;
  const states =
    step.kind === "move_arc"
      ? planArc(at[0], at[1], heading, Math.abs(step.target[0]), -step.target[1] * DEG, forwards, speed, limits)
      : planPath(at[0], at[1], heading, pointsOf(step), forwards, typeof end === "number" ? (90 - end) * DEG : null, speed, limits);
  const last = states[states.length - 1];
  return {
    pose: [last.x, last.y, wrap360(90 - last.heading / DEG)],
    path: states.map((s) => [s.x, s.y] as const),
    speeds: states.map((s) => Math.abs(s.v)),
    seconds: last.t,
    known: true,
  };
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
  const target = info.target === "heading" ? step.target[0] : info.target === "path" ? pointsOf(step).map((p) => [...p]) : [...step.target];
  const value: Record<string, unknown> = { [step.kind]: target };
  if (info.swing) value.locked_side = step.side ?? "left";
  value.timeout = step.timeout ?? 1000;
  for (const name of [...info.options, "async"]) if (name in step.options) value[name] = step.options[name];
  return value;
}

/** A timeout that leaves a motion from `at` room to finish: longer the farther it goes and
 * the more it turns, or for one of vexsim's own, half a second more than its plan takes
 * (milliseconds, in hundreds). */
export function timeoutFor(step: RouteStepData, at: LemPose, track = 12, drive: RouteDriveInfo | null = null): number {
  if (isOwn(step.kind)) {
    const seconds = planStep(at, step, undefined, track, drive).seconds ?? 0;
    return Math.max(800, Math.ceil((seconds + 0.5) * 10) * 100);
  }
  const end = planStep(at, step, undefined, track).pose;
  const distance = Math.hypot(end[0] - at[0], end[1] - at[1]);
  const turn = Math.abs(shortest(end[2] - at[2]));
  const ms = 600 + 40 * distance + 4 * turn;
  return Math.min(5000, Math.max(800, Math.round(ms / 100) * 100));
}

/** A new step of `kind`, to add after `at` (where the robot is then): `target` if it's given,
 * else 24 inches ahead or a quarter turn on (an arc of 18 inches, a path curving off to the
 * right). A motion waits until it's done (LemLib's default is to go on at once), so the route
 * runs as it's drawn, one step after another. Its timeout fits its plan (vexsim's own motions
 * plan with the `drive` model's limits, `track` inches across). */
export function newStep(kind: string, at: LemPose, fn?: RouteFunctionInfo, target?: number[], drive: RouteDriveInfo | null = null, track = 12): RouteStepData {
  const base: RouteStepData = { kind, target: [], timeout: null, side: null, options: {}, function: null, args: {}, label: kind };
  const [dx, dy] = ahead(at[2]);
  const [rx, ry] = rightOf(at[2]);
  const round = (v: number) => Math.round(v * 10) / 10;
  const motion = (made: RouteStepData): RouteStepData => {
    const step = { ...made, target: target ?? made.target, options: { async: false } };
    return { ...step, timeout: isOwn(kind) ? timeoutFor(step, at, track, drive) : timeoutFor(step, at) };
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
    case "move_arc":
      return motion({ ...base, target: [18, 90] });
    case "ramsete":
      return motion({ ...base, target: [round(at[0] + dx * 24 + rx * 12), round(at[1] + dy * 24 + ry * 12), round(at[0] + dx * 48 + rx * 24), round(at[1] + dy * 48 + ry * 24)] });
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
  if (opt.max_velocity !== undefined) extras.push(`max ${opt.max_velocity} in/s`);
  if (opt.max_accel !== undefined) extras.push(`accel ${opt.max_accel} in/s²`);
  if (opt.end_heading !== undefined) extras.push(`ends facing ${opt.end_heading}°`);
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
    case "move_arc":
      head = `Arc ${n(Math.abs(b))}° ${b < 0 ? "counter-clockwise" : "clockwise"}, radius ${n(a)} in`;
      break;
    case "ramsete":
      head = `RAMSETE path through ${pointsOf(step)
        .map(([x, y]) => `(${n(x)}, ${n(y)})`)
        .join(", ")}`;
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

/** What a drag on the field holds: the start (or its heading), a step's target, its heading,
 * or one of a RAMSETE path's points. */
export type Grip = { kind: "start" } | { kind: "start-heading" } | { kind: "target"; index: number } | { kind: "heading"; index: number } | { kind: "waypoint"; index: number; point: number };

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
    if (grip.kind === "waypoint") return { ...step, target: step.target.map((v, k) => (k === 2 * grip.point ? a : k === 2 * grip.point + 1 ? b : v)) };
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
  if (grip.kind === "waypoint") return { op: "set", location: `steps[${grip.index}].ramsete[${grip.point}]`, value: [...pointsOf(step)[grip.point]] };
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

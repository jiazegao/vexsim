// A real robot's log, played on the field: an MCL log (where its code thought it was, its
// estimate, as a path and an outline, and what it saw, update by update: rays, particles,
// spread), or a robot log of vexsim's logger (its code's first logged pose, or a calibration
// log's odometry from its spot; its other poses, and each distance sensor's reading as a ray).
// There's no truth: only the real robot knew where it was. Times are from the log's first
// update (or pose); before it, nothing is drawn.

import type { TrailView } from "./playback";
import { lerpAngle } from "./playback";
import type { DrawColor, MclLogTape, NothingToPlay, RobotLogTape, Shape } from "./protocol";

export type LogTape = MclLogTape | RobotLogTape;
type Pose = [number, number, number];

/** Another pose the log's code logged, as a path to draw in its color. */
export interface LoggedPath {
  name: string;
  color: DrawColor;
  trail: TrailView;
}

const NOTHING: Record<string, Shape[]> = {};

export class LogPlayback {
  readonly start = 0;
  readonly end: number;
  private readonly xs: number[];
  private readonly ys: number[];

  constructor(readonly tape: LogTape) {
    this.end = tape.times.at(-1) ?? 0;
    this.xs = tape.estimate.map((p) => p[0]);
    this.ys = tape.estimate.map((p) => p[1]);
  }

  get name(): string {
    return this.tape.name;
  }

  /** The last update at or before `t`; -1 before the first. */
  index(t: number): number {
    const times = this.tape.times;
    let low = 0;
    let high = times.length;
    while (low < high) {
      const middle = (low + high) >> 1;
      if (times[middle] <= t + 1e-9) low = middle + 1;
      else high = middle;
    }
    return low - 1;
  }

  /** Where the robot's code thought it was at `t`, between updates as it moved; null before
   * the log begins. */
  estimateAt(t: number): Pose | null {
    const i = this.index(t);
    if (i < 0) return null;
    const a = this.tape.estimate[i];
    const b = this.tape.estimate[Math.min(i + 1, this.tape.estimate.length - 1)];
    const ta = this.tape.times[i];
    const tb = this.tape.times[Math.min(i + 1, this.tape.times.length - 1)];
    const f = tb > ta ? Math.min(1, Math.max(0, (t - ta) / (tb - ta))) : 0;
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, lerpAngle(a[2], b[2], f)];
  }

  /** What the update of `t` saw, by layer. */
  drawingsAt(t: number): Record<string, Shape[]> {
    const i = this.index(t);
    return i < 0 ? NOTHING : this.tape.drawings[i][1];
  }

  /** The estimate's path up to `t`. */
  trail(t: number): TrailView {
    return { xs: this.xs, ys: this.ys, length: this.index(t) + 1 };
  }

  /** The other poses' paths up to `t` (a robot log's: MCL's beside LemLib's, say). */
  paths(t: number): LoggedPath[] {
    if (!isRobotLog(this.tape)) return [];
    const i = this.index(t);
    return this.tape.paths.map((p) => ({ name: p.name, color: p.color, trail: { xs: p.xs, ys: p.ys, length: Math.max(0, i - p.first + 1) } }));
  }

  /** The layers it draws in. */
  layers(): string[] {
    return Object.keys(this.tape.drawings[0]?.[1] ?? {});
  }
}

/** Whether a log is a robot log of vexsim's logger (not an MCL log). */
export function isRobotLog(tape: LogTape | NothingToPlay): tape is RobotLogTape {
  return tape.kind === "robot";
}

/** One line about a log: an MCL log's updates over how long, how often, how spread out; a robot
 * log's rows, the pose it plays, its rays. */
export function logSummary(tape: LogTape): string {
  if (isRobotLog(tape)) {
    const s = tape.summary;
    const parts = [`${s.rows} rows over ${s.duration_s.toFixed(1)} s`];
    if (s.interval_ms) parts.push(`every ${Math.round(s.interval_ms)} ms`);
    parts.push(s.pose === "odometry" ? "its pose by odometry, from its spot" : `its code's ${s.pose} pose`);
    if (s.distance_sensors) parts.push(`${s.distance_sensors} distance sensor${s.distance_sensors === 1 ? "" : "s"}`);
    if (s.no_reading_pct !== null && s.distance_sensors) parts.push(`${Math.round(s.no_reading_pct)}% of readings saw nothing`);
    return parts.join(" · ");
  }
  const s = tape.summary;
  const parts = [`${s.updates} updates over ${s.duration_s.toFixed(1)} s`];
  if (s.interval_ms) parts.push(`every ${Math.round(s.interval_ms[0])} ms (95%: ${Math.round(s.interval_ms[1])})`);
  parts.push(`spread ${s.spread_in[0].toFixed(1)} in`);
  if (s.no_reading_pct !== null) parts.push(`${Math.round(s.no_reading_pct)}% of readings saw nothing`);
  return parts.join(" · ");
}

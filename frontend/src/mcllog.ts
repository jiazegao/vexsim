// A real robot's MCL log, played on the field: where its code thought it was (its estimate,
// as a path and an outline), and what it saw, update by update (rays, particles, spread).
// There's no truth: only the real robot knew where it was. Times are from the log's first
// update; before it, nothing is drawn.

import type { MclLogTape, Shape } from "./protocol";
import type { TrailView } from "./playback";
import { lerpAngle } from "./playback";

type Pose = [number, number, number];

const NOTHING: Record<string, Shape[]> = {};

export class LogPlayback {
  readonly start = 0;
  readonly end: number;
  private readonly xs: number[];
  private readonly ys: number[];

  constructor(readonly tape: MclLogTape) {
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

  /** The layers it draws in. */
  layers(): string[] {
    return Object.keys(this.tape.drawings[0]?.[1] ?? {});
  }
}

/** One line about a log: how many updates over how long, how often, and how spread out. */
export function logSummary(tape: MclLogTape): string {
  const s = tape.summary;
  const parts = [`${s.updates} updates over ${s.duration_s.toFixed(1)} s`];
  if (s.interval_ms) parts.push(`every ${Math.round(s.interval_ms[0])} ms (95%: ${Math.round(s.interval_ms[1])})`);
  parts.push(`spread ${s.spread_in[0].toFixed(1)} in`);
  if (s.no_reading_pct !== null) parts.push(`${Math.round(s.no_reading_pct)}% of readings saw nothing`);
  return parts.join(" · ");
}

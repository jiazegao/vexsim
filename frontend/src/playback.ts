// A recorded run, played back: the frame at any moment of its tape (interpolated between
// samples), its paths up to that moment, and its phases, for the timeline.

import type { FrameMessage, FrameState, OverlayMessage, Shape, Tape } from "./protocol";

export interface TrailView {
  xs: number[];
  ys: number[];
  length: number; // the points to draw: the first `length`
}

export interface Phase {
  name: string;
  start: number;
  end: number;
}

type Pose = [number, number, number];

const NOTHING_DRAWN: Record<string, Shape[]> = {};

export class Playback {
  readonly samples: FrameState[];
  private readonly times: number[];
  private readonly truth: { xs: number[]; ys: number[] };
  private readonly estimate: { xs: number[]; ys: number[]; count: number[] }; // count[i]: points by sample i

  constructor(readonly tape: Tape) {
    this.samples = tape.samples;
    this.times = this.samples.map((s) => s.t);
    this.truth = { xs: this.samples.map((s) => s.pose[0]), ys: this.samples.map((s) => s.pose[1]) };
    const estimate = { xs: [] as number[], ys: [] as number[], count: [] as number[] };
    for (const s of this.samples) {
      if (s.estimate) {
        estimate.xs.push(s.estimate[0]);
        estimate.ys.push(s.estimate[1]);
      }
      estimate.count.push(estimate.xs.length);
    }
    this.estimate = estimate;
  }

  get start(): number {
    return this.times[0] ?? 0;
  }

  get end(): number {
    return this.times.at(-1) ?? 0;
  }

  /** The last sample at or before `t` (the first, before the tape starts). */
  index(t: number): number {
    let low = 0;
    let high = this.times.length - 1;
    if (high < 0 || t <= this.times[0]) return 0;
    while (low < high) {
      const middle = (low + high + 1) >> 1;
      if (this.times[middle] <= t) low = middle;
      else high = middle - 1;
    }
    return low;
  }

  /** Where everything was at `t`, as a live frame would say. */
  frameAt(t: number): FrameMessage | null {
    if (this.samples.length === 0) return null;
    const i = this.index(t);
    const a = this.samples[i];
    const b = this.samples[Math.min(i + 1, this.samples.length - 1)];
    const f = b.t > a.t ? Math.min(1, Math.max(0, (t - a.t) / (b.t - a.t))) : 0;
    const time = Math.min(Math.max(t, this.start), this.end);
    return {
      ...a,
      type: "frame",
      t: time,
      state: "finished",
      speed: null,
      rate: 0,
      pose: lerpPose(a.pose, b.pose, f),
      estimate: a.estimate && b.estimate ? lerpPose(a.estimate, b.estimate, f) : a.estimate,
      wheels: a.wheels.map((w, k) => {
        const v = b.wheels[k];
        return v ? [lerp(w[0], v[0], f), lerp(w[1], v[1], f), lerpAngle(w[2], v[2], f), w[3], w[4]] : w;
      }),
      pieces: a.pieces.map((p, k) => {
        const q = b.pieces[k];
        return q ? [lerp(p[0], q[0], f), lerp(p[1], q[1], f)] : p;
      }),
      lcd: this.eventAt("lcd", time) ?? [],
      controller_screen: this.eventAt("controller_screen", time) ?? [],
    };
  }

  /** The motion's path and target at `t`. */
  overlayAt(t: number): OverlayMessage | null {
    const overlay = this.eventAt("overlay", t);
    return overlay ? { type: "overlay", path: overlay.path, target: overlay.target } : null;
  }

  /** What the robot code had drawn at `t`, by layer. */
  drawingsAt(t: number): Record<string, Shape[]> {
    return this.eventAt("drawings", t) ?? NOTHING_DRAWN;
  }

  /** Every layer the robot code drew in, in the order they first appear. */
  drawnLayers(): string[] {
    const names = new Set<string>();
    for (const [, layers] of this.tape.events.drawings ?? []) for (const name of Object.keys(layers)) names.add(name);
    return [...names];
  }

  /** The true path (or the estimate's) up to `t`. */
  trail(kind: "truth" | "estimate", t: number): TrailView {
    const i = this.index(t);
    if (kind === "truth") return { xs: this.truth.xs, ys: this.truth.ys, length: this.samples.length ? i + 1 : 0 };
    return { xs: this.estimate.xs, ys: this.estimate.ys, length: this.estimate.count[i] ?? 0 };
  }

  /** The competition phases, in order, with when each began and ended. */
  phases(): Phase[] {
    const phases: Phase[] = [];
    for (const s of this.samples) {
      const last = phases.at(-1);
      if (last && last.name === s.phase) last.end = s.t;
      else {
        if (last) last.end = s.t;
        phases.push({ name: s.phase, start: s.t, end: s.t });
      }
    }
    return phases;
  }

  private eventAt<K extends keyof Tape["events"]>(name: K, t: number): NonNullable<Tape["events"][K]>[number][1] | null {
    const events: NonNullable<Tape["events"][K]> = this.tape.events[name] ?? []; // older tapes have no drawings
    // the last event at or before t
    let low = 0;
    let high = events.length;
    while (low < high) {
      const middle = (low + high) >> 1;
      if (events[middle][0] <= t + 1e-9) low = middle + 1;
      else high = middle;
    }
    return low > 0 ? events[low - 1][1] : null;
  }
}

function lerp(a: number, b: number, f: number): number {
  return a + (b - a) * f;
}

/** Degrees, the short way round. */
export function lerpAngle(a: number, b: number, f: number): number {
  const turn = ((((b - a) % 360) + 540) % 360) - 180;
  return a + turn * f;
}

function lerpPose(a: readonly number[], b: readonly number[], f: number): Pose {
  return [lerp(a[0], b[0], f), lerp(a[1], b[1], f), lerpAngle(a[2], b[2], f)];
}

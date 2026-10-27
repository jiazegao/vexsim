// The time a recorded run is shown at: seek, play and pause at a speed. The field reads `t`
// every animation frame; React views subscribe and hear about it at most every NOTIFY_MS.

import { useEffect, useSyncExternalStore } from "react";

const NOTIFY_MS = 60;

type Listener = () => void;

export class Playhead {
  t = 0;
  start = 0;
  end = 0;
  playing = false;
  speed = 1;
  version = 0;
  private listeners = new Set<Listener>();
  private notified = 0;

  /** A tape from `start` to `end`, shown at `t` (its end, if not given). */
  load(start: number, end: number, t = end): void {
    this.start = start;
    this.end = end;
    this.playing = false;
    this.seek(t);
  }

  seek(t: number): void {
    this.t = Math.min(this.end, Math.max(this.start, t));
    this.notify(true);
  }

  play(): void {
    if (this.t >= this.end - 1e-6) this.t = this.start; // from the top again
    this.playing = true;
    this.notify(true);
  }

  pause(): void {
    this.playing = false;
    this.notify(true);
  }

  toggle(): void {
    if (this.playing) this.pause();
    else this.play();
  }

  setSpeed(speed: number): void {
    this.speed = speed;
    this.notify(true);
  }

  /** Advance by `seconds` of real time, at the speed (stopping at the end). */
  tick(seconds: number): void {
    if (!this.playing) return;
    this.t += seconds * this.speed;
    if (this.t >= this.end) {
      this.t = this.end;
      this.playing = false;
      this.notify(true);
    } else {
      this.notify(false);
    }
  }

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getVersion = (): number => this.version;

  private notify(now: boolean): void {
    const clock = performance.now();
    if (!now && clock - this.notified < NOTIFY_MS) return;
    this.notified = clock;
    this.version += 1;
    for (const listener of [...this.listeners]) listener();
  }
}

/** Moves `playhead` along while it plays. */
export function usePlayheadClock(playhead: Playhead): void {
  useEffect(() => {
    let frame = 0;
    let last = performance.now();
    const step = (now: number) => {
      frame = requestAnimationFrame(step);
      playhead.tick(Math.min(0.1, (now - last) / 1000)); // a hidden tab doesn't jump ahead
      last = now;
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [playhead]);
}

const never = () => () => {};
const zero = () => 0;

/** Re-render as `playhead` moves (at most every NOTIFY_MS while it plays). */
export function usePlayhead(playhead: Playhead | null): number {
  return useSyncExternalStore(playhead ? playhead.subscribe : never, playhead ? playhead.getVersion : zero);
}

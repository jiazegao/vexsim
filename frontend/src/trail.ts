// A path drawn behind the robot: points at least MIN_STEP apart, at most MAX_POINTS of
// them (when full, every other point is dropped, so the whole path stays visible).

export const MIN_STEP_IN = 0.25;
export const MAX_POINTS = 8000;

export class Trail {
  xs: number[] = [];
  ys: number[] = [];

  get length(): number {
    return this.xs.length;
  }

  clear(): void {
    this.xs = [];
    this.ys = [];
  }

  add(x: number, y: number): void {
    const n = this.xs.length;
    if (n > 0) {
      const dx = x - this.xs[n - 1];
      const dy = y - this.ys[n - 1];
      if (dx * dx + dy * dy < MIN_STEP_IN * MIN_STEP_IN) return;
    }
    this.xs.push(x);
    this.ys.push(y);
    if (this.xs.length > MAX_POINTS) {
      this.xs = this.xs.filter((_, i) => i % 2 === 0);
      this.ys = this.ys.filter((_, i) => i % 2 === 0);
    }
  }
}

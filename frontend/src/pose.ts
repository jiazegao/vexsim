// Poses as people read them. vexsim's heading is degrees counter-clockwise from +x;
// LemLib's theta is degrees clockwise from +y, so the same robot facing +x is heading 0
// here and theta 90 in LemLib (the mix-up behind many wrong start poses).

export type Pose = readonly [number, number, number];

/** LemLib's theta (0 to 360, clockwise from +y) for a vexsim heading. */
export function lemlibTheta(heading: number): number {
  const theta = (90 - heading) % 360;
  return theta < 0 ? theta + 360 : theta === 0 ? 0 : theta;
}

/** A heading in (-180, 180]. */
export function wrapDegrees(degrees: number): number {
  const wrapped = ((((degrees + 180) % 360) + 360) % 360) - 180;
  return wrapped === -180 ? 180 : wrapped;
}

/** Position and heading error between two poses: inches, degrees (absolute). */
export function poseError(a: Pose, b: Pose): [number, number] {
  return [Math.hypot(a[0] - b[0], a[1] - b[1]), Math.abs(wrapDegrees(a[2] - b[2]))];
}

export function fixed(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const text = value.toFixed(digits);
  return text === `-${(0).toFixed(digits)}` ? (0).toFixed(digits) : text;
}

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${seconds.toFixed(2)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds - minutes * 60).toFixed(2).padStart(5, "0")}`;
}

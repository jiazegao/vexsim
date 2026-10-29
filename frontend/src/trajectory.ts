// How vexsim's own motions plan (vexsim/bridge/cpp/motions/include/vexsim/trajectory.hpp, and
// vexsim/algorithms/control/trajectory.py), step for step: an arc, or a smooth path through
// points, timed on a speed profile within the limits of each side's wheel speed, of speeding
// up and slowing down, and of turning at speed. The autonomous maker draws these plans.
//
// Inches, seconds, and headings in radians counter-clockwise from +x. (Square roots, not
// Math.hypot, so the three agree.)

/** A moment of a plan: when (s), how far along (in), where (in, and the robot's heading),
 * forward speed (in/s, negative backwards) and turning (rad/s), and their rates of change. */
export interface State {
  t: number;
  s: number;
  x: number;
  y: number;
  heading: number;
  v: number;
  omega: number;
  a: number;
  alpha: number;
}

/** The fastest either side's wheels may go (in/s), how fast the robot may speed up and slow
 * down (in/s^2), how hard it may turn at speed (in/s^2), and how far apart its wheels are (in). */
export interface Limits {
  maxVelocity: number;
  maxAccel: number;
  maxLateralAccel: number;
  trackWidth: number;
}

const PI = 3.14159265358979323846;
const STEP = 0.25; // inches between the samples a path is timed at

interface Sample {
  s: number;
  x: number;
  y: number;
  heading: number; // which way the path goes
  curvature: number; // radians per inch, counter-clockwise positive
}

function wrap(angle: number): number {
  // into (-pi, pi], as C's fmod does it
  angle = (angle + PI) % (2 * PI);
  if (angle <= 0) angle += 2 * PI;
  return angle - PI;
}

function distance(x0: number, y0: number, x1: number, y1: number): number {
  return Math.sqrt((x1 - x0) * (x1 - x0) + (y1 - y0) * (y1 - y0));
}

function still(): State {
  return { t: 0, s: 0, x: 0, y: 0, heading: 0, v: 0, omega: 0, a: 0, alpha: 0 };
}

/** The path's samples timed: as fast as the limits let it go at each sample, from a
 * standstill to a standstill, with the states every `dt` seconds (and at the end). */
function profile(path: readonly Sample[], forwards: boolean, speed: number, limits: Limits, dt: number): State[] {
  const n = path.length;
  const side = forwards ? 1 : -1;
  if (n < 2) {
    const state = still();
    if (n === 1) {
      state.x = path[0].x;
      state.y = path[0].y;
      state.heading = path[0].heading - (forwards ? 0 : PI);
    }
    return [state];
  }
  const v = new Array<number>(n);
  const t = new Array<number>(n).fill(0);
  const accel = new Array<number>(n).fill(0);
  for (let j = 0; j < n; j++) {
    const bend = Math.abs(path[j].curvature);
    let cap = Math.min(speed, limits.maxVelocity / (1 + (bend * limits.trackWidth) / 2));
    if (bend > 1e-9) cap = Math.min(cap, Math.sqrt(limits.maxLateralAccel / bend));
    v[j] = cap;
  }
  v[0] = v[n - 1] = 0;
  for (let j = 1; j < n; j++) v[j] = Math.min(v[j], Math.sqrt(v[j - 1] * v[j - 1] + 2 * limits.maxAccel * (path[j].s - path[j - 1].s))); // speeding up
  for (let j = n - 2; j >= 0; j--) v[j] = Math.min(v[j], Math.sqrt(v[j + 1] * v[j + 1] + 2 * limits.maxAccel * (path[j + 1].s - path[j].s))); // slowing down
  for (let j = 1; j < n; j++) {
    const ds = path[j].s - path[j - 1].s;
    const sum = v[j] + v[j - 1];
    t[j] = t[j - 1] + (sum > 1e-12 ? (2 * ds) / sum : 0);
    accel[j] = ds > 1e-12 ? (v[j] * v[j] - v[j - 1] * v[j - 1]) / (2 * ds) : 0;
  }
  const states: State[] = [];
  const end = t[n - 1];
  let j = 1; // the samples j - 1 and j bracket the time
  for (let k = 0; ; k++) {
    const time = Math.min(k * dt, end);
    while (j < n - 1 && t[j] < time) j++;
    const tau = time - t[j - 1];
    let s = path[j - 1].s + v[j - 1] * tau + 0.5 * accel[j] * tau * tau;
    s = Math.max(path[j - 1].s, Math.min(path[j].s, s));
    const speedNow = Math.max(0, v[j - 1] + accel[j] * tau);
    const ds = path[j].s - path[j - 1].s;
    const f = ds > 1e-12 ? (s - path[j - 1].s) / ds : 0;
    const p = path[j - 1];
    const q = path[j];
    const curvature = p.curvature + f * (q.curvature - p.curvature);
    const stopped = time >= end;
    states.push({
      t: time,
      s,
      x: p.x + f * (q.x - p.x),
      y: p.y + f * (q.y - p.y),
      heading: p.heading + f * (q.heading - p.heading) - (forwards ? 0 : PI),
      v: stopped ? 0 : side * speedNow,
      omega: stopped ? 0 : curvature * speedNow,
      a: stopped ? 0 : side * accel[j],
      alpha: stopped ? 0 : curvature * accel[j],
    });
    if (stopped) return states;
  }
}

/** An arc from (x, y), facing `heading`: `radius` inches, turning the robot `turn` radians
 * (counter-clockwise positive), forwards or backwards, at most `speed` in/s. */
export function planArc(x: number, y: number, heading: number, radius: number, turn: number, forwards: boolean, speed: number, limits: Limits, dt = 0.01): State[] {
  const length = Math.abs(radius * turn);
  const count = Math.max(1, Math.ceil(length / STEP));
  const travel = heading + (forwards ? 0 : PI); // the way it goes
  const bend = length > 1e-12 ? turn / length : 0;
  const path: Sample[] = [];
  for (let i = 0; i <= count; i++) {
    const s = (length * i) / count;
    const h = travel + bend * s;
    let px = x + s * Math.cos(travel);
    let py = y + s * Math.sin(travel);
    if (Math.abs(bend) > 1e-12) {
      px = x + (Math.sin(h) - Math.sin(travel)) / bend;
      py = y - (Math.cos(h) - Math.cos(travel)) / bend;
    }
    path.push({ s, x: px, y: py, heading: h, curvature: bend });
  }
  return profile(path, forwards, speed, limits, dt);
}

/** A smooth path from (x, y), facing `heading`, through `points`: it sets off the way the
 * robot faces (backwards: the way it faces away from), bends through each point as a
 * Catmull-Rom curve does, and ends facing `endHeading` (the robot's, radians) or, if null,
 * the way the last stretch goes. At most `speed` in/s. */
export function planPath(x: number, y: number, heading: number, points: readonly (readonly [number, number])[], forwards: boolean, endHeading: number | null, speed: number, limits: Limits, dt = 0.01): State[] {
  const q: [number, number][] = [[x, y]];
  for (const p of points) {
    const last = q[q.length - 1];
    if (distance(last[0], last[1], p[0], p[1]) > 1e-6) q.push([p[0], p[1]]);
  }
  const travel = heading + (forwards ? 0 : PI);
  if (q.length < 2) return profile([{ s: 0, x, y, heading: travel, curvature: 0 }], forwards, speed, limits, dt);
  const m = q.length - 1; // pieces, each a cubic Hermite curve
  const first = distance(q[0][0], q[0][1], q[1][0], q[1][1]);
  const tangent: [number, number][] = [[Math.cos(travel) * first, Math.sin(travel) * first]];
  for (let i = 1; i < m; i++) tangent.push([(q[i + 1][0] - q[i - 1][0]) / 2, (q[i + 1][1] - q[i - 1][1]) / 2]);
  if (endHeading === null) {
    tangent.push([q[m][0] - q[m - 1][0], q[m][1] - q[m - 1][1]]);
  } else {
    const last = distance(q[m - 1][0], q[m - 1][1], q[m][0], q[m][1]);
    const end = endHeading + (forwards ? 0 : PI);
    tangent.push([Math.cos(end) * last, Math.sin(end) * last]);
  }
  const path: Sample[] = [];
  let s = 0;
  let previous = travel;
  for (let i = 0; i < m; i++) {
    const [p0x, p0y] = q[i];
    const [p1x, p1y] = q[i + 1];
    const [m0x, m0y] = tangent[i];
    const [m1x, m1y] = tangent[i + 1];
    const count = Math.max(4, Math.ceil(distance(p0x, p0y, p1x, p1y) / STEP));
    for (let k = i === 0 ? 0 : 1; k <= count; k++) {
      const u = k / count;
      const u2 = u * u;
      const u3 = u2 * u;
      const h00 = 2 * u3 - 3 * u2 + 1;
      const h10 = u3 - 2 * u2 + u;
      const h01 = -2 * u3 + 3 * u2;
      const h11 = u3 - u2;
      const d00 = 6 * u2 - 6 * u;
      const d10 = 3 * u2 - 4 * u + 1;
      const d01 = -6 * u2 + 6 * u;
      const d11 = 3 * u2 - 2 * u;
      const e00 = 12 * u - 6;
      const e10 = 6 * u - 4;
      const e01 = -12 * u + 6;
      const e11 = 6 * u - 2;
      const px = h00 * p0x + h10 * m0x + h01 * p1x + h11 * m1x;
      const py = h00 * p0y + h10 * m0y + h01 * p1y + h11 * m1y;
      const dx = d00 * p0x + d10 * m0x + d01 * p1x + d11 * m1x;
      const dy = d00 * p0y + d10 * m0y + d01 * p1y + d11 * m1y;
      const ex = e00 * p0x + e10 * m0x + e01 * p1x + e11 * m1x;
      const ey = e00 * p0y + e10 * m0y + e01 * p1y + e11 * m1y;
      const rate = Math.sqrt(dx * dx + dy * dy);
      const h = rate > 1e-12 ? previous + wrap(Math.atan2(dy, dx) - previous) : previous;
      const bend = rate > 1e-12 ? (dx * ey - dy * ex) / (rate * rate * rate) : 0;
      if (path.length) s += distance(path[path.length - 1].x, path[path.length - 1].y, px, py);
      path.push({ s, x: px, y: py, heading: h, curvature: bend });
      previous = h;
    }
  }
  return profile(path, forwards, speed, limits, dt);
}

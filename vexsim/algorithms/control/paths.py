"""Path following: pure pursuit on waypoints, and RAMSETE on a time-parameterized trajectory."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from vexsim.algorithms.control.base import ChassisGeometry, DriveCommand, scale_to_limit
from vexsim.algorithms.localization.base import Pose
from vexsim.devices.frame import SensorFrame
from vexsim.units import M_PER_IN

Point = tuple[float, float]


def densify(waypoints: Sequence[Point], spacing_in: float = 1.0) -> np.ndarray:
    """Points every ``spacing_in`` along the polyline through ``waypoints``."""
    pts = np.asarray(waypoints, dtype=float)
    if len(pts) < 2:
        raise ValueError("a path needs at least two waypoints")
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:], strict=True):
        n = max(1, int(math.ceil(np.hypot(*(b - a)) / spacing_in)))
        out.extend(a + (b - a) * k / n for k in range(1, n + 1))
    return np.array(out)


def smooth(points: np.ndarray, weight: float = 0.25, iterations: int = 200) -> np.ndarray:
    """Gradient smoothing (keeps the end points), rounding the corners of a polyline."""
    p = points.copy()
    for _ in range(iterations):
        p[1:-1] += weight * (p[:-2] + p[2:] - 2 * p[1:-1])
    return p


def spline(waypoints: Sequence[Point], spacing_in: float = 0.5) -> np.ndarray:
    """A centripetal Catmull-Rom spline through every waypoint, sampled about every ``spacing_in``.

    Unlike corner smoothing, the curve bends gradually between waypoints, so
    its curvature stays within what a drivetrain can actually turn.
    """
    pts = np.asarray(waypoints, dtype=float)
    if len(pts) < 2:
        raise ValueError("a path needs at least two waypoints")
    if len(pts) == 2:
        return densify(pts, spacing_in)
    ext = np.vstack([2 * pts[0] - pts[1], pts, 2 * pts[-1] - pts[-2]])
    out = [pts[0]]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        t0 = 0.0
        t1 = t0 + max(np.hypot(*(p1 - p0)), 1e-9) ** 0.5
        t2 = t1 + max(np.hypot(*(p2 - p1)), 1e-9) ** 0.5
        t3 = t2 + max(np.hypot(*(p3 - p2)), 1e-9) ** 0.5
        n = max(2, int(math.ceil(np.hypot(*(p2 - p1)) / spacing_in)))
        for t in np.linspace(t1, t2, n + 1)[1:]:
            a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
            a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
            a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
            b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
            b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
            out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    return np.array(out)


@dataclass
class PurePursuit:
    """Chase a point ``lookahead_in`` ahead on the path; slow down for curvature and the end."""

    waypoints: Sequence[Point]
    geometry: ChassisGeometry
    lookahead_in: float = 12.0
    max_speed_fraction: float = 0.7
    max_accel_in_s2: float = 120.0
    turn_slowdown: float = 3.0  # higher = slower on tight curves
    end_tolerance_in: float = 1.5

    def __post_init__(self) -> None:
        self.path = spline(self.waypoints, 1.0)
        self._index = 0
        self._speed = 0.0
        self._arrived = False
        self._done = False

    def step(self, pose: Pose, frame: SensorFrame, dt: float) -> DriveCommand:
        p = np.array([pose.x, pose.y])
        # Never search backwards: the closest point only moves forward along the path.
        window = self.path[self._index : self._index + 50]
        self._index += int(np.argmin(np.hypot(*(window - p).T)))
        remaining = self.path[self._index :]
        end_distance = float(np.hypot(*(self.path[-1] - p)))
        if end_distance < self.end_tolerance_in and self._index >= len(self.path) - 3:
            self._arrived = True
        if self._arrived:
            # Brake to a standstill in a straight line, so the motion ends stopped
            # rather than handing a still-moving robot to whatever comes next.
            self._speed = max(0.0, self._speed - self.max_accel_in_s2 * dt)
            self._done = self._speed == 0.0
            return DriveCommand(self._speed, self._speed, mode="velocity")

        ahead = np.hypot(*(remaining - p).T)
        beyond = np.nonzero(ahead >= self.lookahead_in)[0]
        goal = remaining[beyond[0]] if len(beyond) else self.path[-1]
        h = math.radians(pose.heading)
        dx, dy = goal - p
        local_y = -math.sin(h) * dx + math.cos(h) * dy  # lateral offset of the goal (+left)
        chord2 = dx * dx + dy * dy
        curvature = 2.0 * local_y / chord2 if chord2 > 1e-9 else 0.0

        v_max = self.max_speed_fraction * self.geometry.max_speed_in_s
        target = v_max / (1.0 + self.turn_slowdown * abs(curvature) * self.geometry.track_width_in)
        target = min(target, math.sqrt(2 * self.max_accel_in_s2 * end_distance))
        self._speed = min(target, self._speed + self.max_accel_in_s2 * dt)
        left, right = self.geometry.wheel_speeds(self._speed, self._speed * curvature)
        left, right = scale_to_limit(left, right, self.geometry.max_speed_in_s)
        return DriveCommand(left, right, mode="velocity")

    def done(self) -> bool:
        return self._done


@dataclass(frozen=True)
class Trajectory:
    """Samples every ``dt`` seconds: x, y (in), heading (rad), v (in/s), omega (rad/s)."""

    dt: float
    states: np.ndarray  # (n, 5)

    @property
    def duration(self) -> float:
        return (len(self.states) - 1) * self.dt

    def sample(self, t: float) -> np.ndarray:
        i = min(max(int(round(t / self.dt)), 0), len(self.states) - 1)
        return self.states[i]


def generate_trajectory(
    waypoints: Sequence[Point],
    geometry: ChassisGeometry,
    *,
    max_speed_fraction: float = 0.7,
    max_accel_in_s2: float = 100.0,
    max_lateral_accel_in_s2: float = 40.0,
    dt: float = 0.01,
) -> Trajectory:
    """Time-parameterize a smoothed path under speed, acceleration and curvature limits.

    The curvature limit keeps the needed sideways acceleration within what the
    wheels can hold (``max_lateral_accel_in_s2``), which matters a lot on omni drives,
    and the outer wheel never has to exceed the drivetrain's top speed.
    """
    pts = spline(waypoints, 0.5)
    seg = np.hypot(*np.diff(pts, axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    heading = np.unwrap(np.arctan2(*np.gradient(pts, s, axis=0)[:, ::-1].T))
    curvature = np.gradient(heading, s)
    v_max = max_speed_fraction * geometry.max_speed_in_s
    with np.errstate(divide="ignore"):
        v_limit = np.minimum(v_max, np.sqrt(max_lateral_accel_in_s2 / np.abs(curvature)))
    # Outer wheel speed v * (1 + |k| * track/2) must stay within the top speed.
    wheel_limit = geometry.max_speed_in_s / (1.0 + np.abs(curvature) * geometry.track_width_in / 2)
    v_limit = np.minimum(v_limit, wheel_limit)
    v = v_limit.copy()
    v[0] = v[-1] = 0.0
    for i in range(1, len(v)):  # forward pass: acceleration limit
        v[i] = min(v[i], math.sqrt(v[i - 1] ** 2 + 2 * max_accel_in_s2 * seg[i - 1]))
    for i in range(len(v) - 2, -1, -1):  # backward pass: deceleration limit
        v[i] = min(v[i], math.sqrt(v[i + 1] ** 2 + 2 * max_accel_in_s2 * seg[i]))
    v_mid = np.maximum((v[1:] + v[:-1]) / 2, 1e-6)
    t = np.concatenate([[0.0], np.cumsum(seg / v_mid)])
    times = np.arange(0.0, t[-1] + dt, dt)
    states = np.column_stack(
        [
            np.interp(times, t, pts[:, 0]),
            np.interp(times, t, pts[:, 1]),
            np.interp(times, t, heading),
            np.interp(times, t, v),
            np.interp(times, t, v * curvature),
        ]
    )
    return Trajectory(dt, states)


@dataclass
class Ramsete:
    """RAMSETE trajectory tracking: a nonlinear feedback law around the planned speeds.

    ``b`` (1/m^2) and ``zeta`` are the usual SI tuning constants. The textbook
    b = 2 assumes a well-characterized feedforward drivetrain; here the motors'
    own velocity loops lag, and b = 5 tracks better. Output is wheel speed.
    """

    trajectory: Trajectory
    geometry: ChassisGeometry
    b: float = 5.0
    zeta: float = 0.7
    lead_s: float = 0.04  # feed forward speeds this far ahead, to cover the motors' velocity lag
    # Cap on speed x yaw rate (in/s^2). RAMSETE assumes wheels never slide sideways; on omni
    # wheels, catching up faster than this through a turn makes the robot slide out and spiral.
    max_lateral_accel_in_s2: float = 50.0

    def __post_init__(self) -> None:
        self._t = 0.0

    def step(self, pose: Pose, frame: SensorFrame, dt: float) -> DriveCommand:
        xd, yd, hd, _, _ = self.trajectory.sample(self._t)
        _, _, _, vd, wd = self.trajectory.sample(self._t + self.lead_s)
        self._t += dt
        m = M_PER_IN
        x, y, h = pose.x * m, pose.y * m, math.radians(pose.heading)
        ex_f, ey_f = xd * m - x, yd * m - y
        ex = math.cos(h) * ex_f + math.sin(h) * ey_f
        ey = -math.sin(h) * ex_f + math.cos(h) * ey_f
        eh = math.atan2(math.sin(hd - h), math.cos(hd - h))
        v_ref = vd * m
        k = 2 * self.zeta * math.sqrt(wd * wd + self.b * v_ref * v_ref)
        sinc = math.sin(eh) / eh if abs(eh) > 1e-6 else 1.0
        v = v_ref * math.cos(eh) + k * ex
        w = wd + k * eh + self.b * v_ref * sinc * ey
        limit = self.max_lateral_accel_in_s2 * m
        if abs(v * w) > limit:  # keep the turn, give up speed
            v = math.copysign(limit / abs(w), v)
        left, right = self.geometry.wheel_speeds(v / m, w)
        left, right = scale_to_limit(left, right, self.geometry.max_speed_in_s)
        return DriveCommand(left, right, mode="velocity")

    def done(self) -> bool:
        return self._t >= self.trajectory.duration + 0.25

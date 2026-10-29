"""How vexsim's own C++ motions plan (vexsim/bridge/cpp/motions/include/vexsim/trajectory.hpp),
step for step: an arc, or a smooth path through points, timed on a speed profile within the
limits of each side's wheel speed, of speeding up and slowing down, and of turning at speed.
The C++ is tested against this, and the autonomous maker draws plans made the same way.

Inches, seconds, and headings in radians counter-clockwise from +x. (Square roots, not
``math.hypot``, so the three agree to the last digit.)
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

PI = 3.14159265358979323846
STEP = 0.25  # inches between the samples a path is timed at


@dataclass(frozen=True)
class State:
    """A moment of a plan: when (s), how far along (in), where (in, and the robot's heading),
    forward speed (in/s, negative backwards) and turning (rad/s), and their rates of change."""

    t: float = 0.0
    s: float = 0.0
    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0
    v: float = 0.0
    omega: float = 0.0
    a: float = 0.0
    alpha: float = 0.0


@dataclass(frozen=True)
class Limits:
    """The fastest either side's wheels may go (in/s), how fast the robot may speed up and
    slow down along its way (in/s^2), how hard it may turn at speed (speed squared times
    curvature, in/s^2), and how far apart its wheels are (in)."""

    max_velocity: float = 60.0
    max_accel: float = 120.0
    max_lateral_accel: float = 60.0
    track_width: float = 12.0


@dataclass(frozen=True)
class _Sample:
    s: float
    x: float
    y: float
    heading: float  # which way the path goes
    curvature: float  # radians per inch, counter-clockwise positive


def _wrap(angle: float) -> float:
    angle = math.fmod(angle + PI, 2 * PI)
    if angle <= 0:
        angle += 2 * PI
    return angle - PI


def _distance(x0: float, y0: float, x1: float, y1: float) -> float:
    return math.sqrt((x1 - x0) * (x1 - x0) + (y1 - y0) * (y1 - y0))


def _profile(
    path: list[_Sample], forwards: bool, speed: float, limits: Limits, dt: float
) -> list[State]:
    n = len(path)
    side = 1.0 if forwards else -1.0
    if n < 2:
        if n == 0:
            return [State()]
        p = path[0]
        return [State(x=p.x, y=p.y, heading=p.heading - (0.0 if forwards else PI))]
    v = [0.0] * n
    for j, p in enumerate(path):
        bend = abs(p.curvature)
        cap = min(speed, limits.max_velocity / (1 + bend * limits.track_width / 2))
        if bend > 1e-9:
            cap = min(cap, math.sqrt(limits.max_lateral_accel / bend))
        v[j] = cap
    v[0] = v[n - 1] = 0.0
    for j in range(1, n):  # speeding up
        v[j] = min(
            v[j],
            math.sqrt(v[j - 1] * v[j - 1] + 2 * limits.max_accel * (path[j].s - path[j - 1].s)),
        )
    for j in range(n - 2, -1, -1):  # slowing down
        v[j] = min(
            v[j],
            math.sqrt(v[j + 1] * v[j + 1] + 2 * limits.max_accel * (path[j + 1].s - path[j].s)),
        )
    t = [0.0] * n
    accel = [0.0] * n
    for j in range(1, n):
        ds = path[j].s - path[j - 1].s
        total = v[j] + v[j - 1]
        t[j] = t[j - 1] + (2 * ds / total if total > 1e-12 else 0.0)
        accel[j] = (v[j] * v[j] - v[j - 1] * v[j - 1]) / (2 * ds) if ds > 1e-12 else 0.0
    states: list[State] = []
    end = t[n - 1]
    j = 1
    k = 0
    while True:
        time = min(k * dt, end)
        while j < n - 1 and t[j] < time:
            j += 1
        tau = time - t[j - 1]
        s = path[j - 1].s + v[j - 1] * tau + 0.5 * accel[j] * tau * tau
        s = max(path[j - 1].s, min(path[j].s, s))
        speed_now = max(0.0, v[j - 1] + accel[j] * tau)
        ds = path[j].s - path[j - 1].s
        f = (s - path[j - 1].s) / ds if ds > 1e-12 else 0.0
        p, q = path[j - 1], path[j]
        curvature = p.curvature + f * (q.curvature - p.curvature)
        stopped = time >= end
        states.append(
            State(
                t=time,
                s=s,
                x=p.x + f * (q.x - p.x),
                y=p.y + f * (q.y - p.y),
                heading=p.heading + f * (q.heading - p.heading) - (0.0 if forwards else PI),
                v=0.0 if stopped else side * speed_now,
                omega=0.0 if stopped else curvature * speed_now,
                a=0.0 if stopped else side * accel[j],
                alpha=0.0 if stopped else curvature * accel[j],
            )
        )
        if stopped:
            return states
        k += 1


def plan_arc(
    x: float,
    y: float,
    heading: float,
    radius: float,
    turn: float,
    forwards: bool,
    speed: float,
    limits: Limits,
    dt: float = 0.01,
) -> list[State]:
    """An arc from (x, y), facing ``heading``: ``radius`` inches, turning the robot ``turn``
    radians (counter-clockwise positive), forwards or backwards, at most ``speed`` in/s."""
    length = abs(radius * turn)
    count = max(1, int(math.ceil(length / STEP)))
    travel = heading + (0.0 if forwards else PI)
    bend = turn / length if length > 1e-12 else 0.0
    path = []
    for i in range(count + 1):
        s = length * i / count
        h = travel + bend * s
        px, py = x + s * math.cos(travel), y + s * math.sin(travel)
        if abs(bend) > 1e-12:
            px = x + (math.sin(h) - math.sin(travel)) / bend
            py = y - (math.cos(h) - math.cos(travel)) / bend
        path.append(_Sample(s, px, py, h, bend))
    return _profile(path, forwards, speed, limits, dt)


def plan_path(
    x: float,
    y: float,
    heading: float,
    points: Sequence[tuple[float, float]],
    forwards: bool,
    end_heading: float | None,
    speed: float,
    limits: Limits,
    dt: float = 0.01,
) -> list[State]:
    """A smooth path from (x, y), facing ``heading``, through ``points``: it sets off the way
    the robot faces (backwards: the way it faces away from), bends through each point as a
    Catmull-Rom curve does, and ends facing ``end_heading`` (the robot's, radians) or, if
    None, the way the last stretch goes. At most ``speed`` in/s."""
    q = [(x, y)]
    for p in points:
        if _distance(q[-1][0], q[-1][1], p[0], p[1]) > 1e-6:
            q.append((float(p[0]), float(p[1])))
    travel = heading + (0.0 if forwards else PI)
    if len(q) < 2:
        return _profile([_Sample(0.0, x, y, travel, 0.0)], forwards, speed, limits, dt)
    m = len(q) - 1
    first = _distance(q[0][0], q[0][1], q[1][0], q[1][1])
    tangent = [(math.cos(travel) * first, math.sin(travel) * first)]
    for i in range(1, m):
        tangent.append(((q[i + 1][0] - q[i - 1][0]) / 2, (q[i + 1][1] - q[i - 1][1]) / 2))
    if end_heading is None:
        tangent.append((q[m][0] - q[m - 1][0], q[m][1] - q[m - 1][1]))
    else:
        last = _distance(q[m - 1][0], q[m - 1][1], q[m][0], q[m][1])
        end = end_heading + (0.0 if forwards else PI)
        tangent.append((math.cos(end) * last, math.sin(end) * last))
    path: list[_Sample] = []
    s, previous = 0.0, travel
    for i in range(m):
        (p0x, p0y), (p1x, p1y) = q[i], q[i + 1]
        (m0x, m0y), (m1x, m1y) = tangent[i], tangent[i + 1]
        count = max(4, int(math.ceil(_distance(p0x, p0y, p1x, p1y) / STEP)))
        for k in range(0 if i == 0 else 1, count + 1):
            u = k / count
            u2 = u * u
            u3 = u2 * u
            h00, h10, h01, h11 = 2 * u3 - 3 * u2 + 1, u3 - 2 * u2 + u, -2 * u3 + 3 * u2, u3 - u2
            d00, d10, d01, d11 = 6 * u2 - 6 * u, 3 * u2 - 4 * u + 1, -6 * u2 + 6 * u, 3 * u2 - 2 * u
            e00, e10, e01, e11 = 12 * u - 6, 6 * u - 4, -12 * u + 6, 6 * u - 2
            px = h00 * p0x + h10 * m0x + h01 * p1x + h11 * m1x
            py = h00 * p0y + h10 * m0y + h01 * p1y + h11 * m1y
            dx = d00 * p0x + d10 * m0x + d01 * p1x + d11 * m1x
            dy = d00 * p0y + d10 * m0y + d01 * p1y + d11 * m1y
            ex = e00 * p0x + e10 * m0x + e01 * p1x + e11 * m1x
            ey = e00 * p0y + e10 * m0y + e01 * p1y + e11 * m1y
            rate = math.sqrt(dx * dx + dy * dy)
            h = previous + _wrap(math.atan2(dy, dx) - previous) if rate > 1e-12 else previous
            bend = (dx * ey - dy * ex) / (rate * rate * rate) if rate > 1e-12 else 0.0
            if path:
                s += _distance(path[-1].x, path[-1].y, px, py)
            path.append(_Sample(s, px, py, h, bend))
            previous = h
    return _profile(path, forwards, speed, limits, dt)

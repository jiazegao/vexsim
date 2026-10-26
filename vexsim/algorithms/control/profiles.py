"""1-D motion profiles: trapezoidal (accel-limited) and S-curve (jerk-limited)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ProfileState:
    position: float
    velocity: float
    acceleration: float


class TrapezoidProfile:
    """Accelerate at ``max_accel`` to ``max_velocity``, cruise, decelerate; triangle if short."""

    def __init__(self, distance: float, max_velocity: float, max_accel: float):
        if max_velocity <= 0 or max_accel <= 0:
            raise ValueError("max_velocity and max_accel must be positive")
        self.sign = 1.0 if distance >= 0 else -1.0
        d = abs(distance)
        t_acc = max_velocity / max_accel
        if max_accel * t_acc**2 > d:  # never reaches cruise speed
            t_acc = math.sqrt(d / max_accel)
        self.peak = max_accel * t_acc
        self.accel = max_accel
        self.t_acc = t_acc
        self.t_cruise = (d - max_accel * t_acc**2) / self.peak if self.peak > 0 else 0.0
        self.duration = 2 * t_acc + self.t_cruise
        self.distance = d

    def sample(self, t: float) -> ProfileState:
        a, ta, tc, v = self.accel, self.t_acc, self.t_cruise, self.peak
        t = min(max(t, 0.0), self.duration)
        if t < ta:
            state = (0.5 * a * t * t, a * t, a)
        elif t < ta + tc:
            state = (0.5 * a * ta * ta + v * (t - ta), v, 0.0)
        else:
            r = self.duration - t
            state = (self.distance - 0.5 * a * r * r, a * r, -a if r > 0 else 0.0)
        s = self.sign
        return ProfileState(s * state[0], s * state[1], s * state[2])


class SCurveProfile:
    """Jerk-limited profile: the acceleration itself ramps, for smoother starts and stops.

    Built by numerically integrating a jerk-limited acceleration command, then
    scaling the cruise speed down (bisection) until the profile stops exactly at
    ``distance``. Accurate to well under 0.1% of the distance.
    """

    def __init__(
        self,
        distance: float,
        max_velocity: float,
        max_accel: float,
        max_jerk: float,
        dt: float = 0.001,
    ):
        if min(max_velocity, max_accel, max_jerk) <= 0:
            raise ValueError("limits must be positive")
        self.sign = 1.0 if distance >= 0 else -1.0
        self.distance = abs(distance)
        self.dt = dt
        lo, hi = 0.0, max_velocity
        best = self._build(max_velocity, max_accel, max_jerk)
        if best is None:  # cannot reach max_velocity within the distance: lower the cruise speed
            for _ in range(40):
                mid = 0.5 * (lo + hi)
                if self._build(mid, max_accel, max_jerk) is None:
                    hi = mid
                else:
                    lo = mid
            best = self._build(lo, max_accel, max_jerk) or ([0.0], [0.0], [0.0])
        self._pos, self._vel, self._acc = best
        self.duration = (len(self._pos) - 1) * dt

    def _ramp(self, v_target: float, a_max: float, j_max: float):
        """Velocities/accels from 0 to v_target: jerk up, (constant accel), jerk down."""
        if v_target <= 0:
            return [0.0], [0.0]
        if v_target >= a_max * a_max / j_max:
            t_jerk, peak = a_max / j_max, a_max
            t_const = (v_target - a_max * a_max / j_max) / a_max
        else:
            t_jerk = math.sqrt(v_target / j_max)
            peak, t_const = j_max * t_jerk, 0.0
        total = 2 * t_jerk + t_const
        n = max(1, int(math.ceil(total / self.dt)))
        times = [k * total / n for k in range(n + 1)]
        acc = [
            j_max * t if t < t_jerk
            else peak if t < t_jerk + t_const
            else max(0.0, peak - j_max * (t - t_jerk - t_const))
            for t in times
        ]  # fmt: skip
        vel, v = [0.0], 0.0
        step = total / n
        for a0, a1 in zip(acc[:-1], acc[1:], strict=True):
            v += 0.5 * (a0 + a1) * step
            vel.append(v)
        scale = v_target / vel[-1]  # absorb the integration remainder
        return [x * scale for x in vel], acc

    def _build(self, v_cruise: float, a_max: float, j_max: float):
        vel_up, acc_up = self._ramp(v_cruise, a_max, j_max)
        ramp_distance = sum(vel_up) * self.dt
        cruise = self.distance - 2 * ramp_distance
        if cruise < -1e-9:
            return None
        n_cruise = int(round(cruise / v_cruise / self.dt)) if v_cruise > 0 else 0
        vel = vel_up + [v_cruise] * n_cruise + vel_up[::-1]
        acc = acc_up + [0.0] * n_cruise + [-x for x in acc_up[::-1]]
        pos, p = [], 0.0
        for v in vel:
            pos.append(p)
            p += v * self.dt
        # Absorb the small discretization remainder so the profile ends exactly on target.
        scale = self.distance / pos[-1] if pos[-1] > 0 else 1.0
        return [x * scale for x in pos], [v * scale for v in vel], acc

    def sample(self, t: float) -> ProfileState:
        i = min(max(int(round(t / self.dt)), 0), len(self._pos) - 1)
        s = self.sign
        return ProfileState(s * self._pos[i], s * self._vel[i], s * self._acc[i])

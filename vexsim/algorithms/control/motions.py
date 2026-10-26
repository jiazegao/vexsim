"""Point-to-point motions for differential drives (LemLib-style), on the estimated pose.

Every motion is a one-shot controller: build it with its target, call
``step(pose, frame, dt)`` every control tick, stop when ``done()``. Gains are
in volts per inch / per degree, like LemLib's.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from vexsim.algorithms.control.base import (
    ChassisGeometry,
    DriveCommand,
    scale_to_limit,
    wrap_degrees,
)
from vexsim.algorithms.control.pid import PID, ExitCondition
from vexsim.algorithms.control.profiles import SCurveProfile, TrapezoidProfile
from vexsim.algorithms.localization.base import Pose
from vexsim.devices.frame import SensorFrame


def default_lateral() -> PID:
    return PID(kp=0.9, kd=0.06, ki=0.0)


def default_angular() -> PID:
    return PID(kp=0.25, kd=0.015, ki=0.0)


@dataclass
class TurnToHeading:
    """Turn in place to a field heading (degrees, counter-clockwise).

    ``static_volts`` is added in the direction of the error while it's larger
    than the tolerance. Turning in place has to overcome roller and rolling
    friction first; without it a P-only turn stalls a few degrees short.
    """

    heading: float
    max_volts: float = 12.0
    static_volts: float = 1.5
    pid: PID = field(default_factory=lambda: PID(kp=0.35, kd=0.03, ki=0.05, integral_zone=5))
    exit: ExitCondition = field(default_factory=lambda: ExitCondition(tolerance=1.0, hold_s=0.08))

    def __post_init__(self) -> None:
        self._done = False

    def step(self, pose: Pose, frame: SensorFrame, dt: float) -> DriveCommand:
        error = wrap_degrees(self.heading - pose.heading)
        self._done = self.exit.update(error, dt)
        out = self.pid.update(error, dt)
        if abs(error) > self.exit.tolerance:
            out += math.copysign(self.static_volts, error)
        out = max(-self.max_volts, min(self.max_volts, out))
        return DriveCommand(-out, out)

    def done(self) -> bool:
        return self._done


def _prioritize_turning(lateral: float, angular: float, max_volts: float) -> tuple[float, float]:
    """Give up forward output before turning output (LemLib), then limit both sides."""
    lateral = max(-max_volts, min(max_volts, lateral))
    over = abs(lateral) + abs(angular) - max_volts
    if over > 0:
        lateral -= math.copysign(min(over, abs(lateral)), lateral)
    return scale_to_limit(lateral - angular, lateral + angular, max_volts)


class _Slew:
    """Limit how fast the forward output may rise (volts per second); falls are free."""

    def __init__(self, rate: float):
        self.rate = rate
        self.value = 0.0

    def __call__(self, target: float, dt: float) -> float:
        if abs(target) > abs(self.value) and target * self.value >= 0:
            step = self.rate * dt
            target = max(self.value - step, min(self.value + step, target))
        self.value = target
        return target


@dataclass
class MoveToPoint:
    """Drive to (x, y) without caring about the final heading (LemLib ``moveToPoint``).

    Lateral output follows the signed distance along the robot's heading;
    angular output points the robot at the target and takes priority over
    lateral. Within ``settle_radius_in`` the angular correction is switched off,
    so the robot doesn't spin around the point, and it may back up to settle.
    """

    x: float
    y: float
    forwards: bool = True
    max_volts: float = 12.0
    slew_volts_per_s: float = 60.0
    lateral: PID = field(default_factory=default_lateral)
    angular: PID = field(default_factory=default_angular)
    exit: ExitCondition = field(default_factory=lambda: ExitCondition(tolerance=1.0, hold_s=0.1))
    settle_radius_in: float = 7.5

    def __post_init__(self) -> None:
        self._done = False
        self._close = False
        self._slew = _Slew(self.slew_volts_per_s)

    def step(self, pose: Pose, frame: SensorFrame, dt: float) -> DriveCommand:
        dx, dy = self.x - pose.x, self.y - pose.y
        distance = math.hypot(dx, dy)
        self._done = self.exit.update(distance, dt)
        facing = math.radians(pose.heading) + (0.0 if self.forwards else math.pi)
        along = dx * math.cos(facing) + dy * math.sin(facing)  # signed, in the driving direction
        self._close = self._close or distance < self.settle_radius_in
        lateral = self.lateral.update(along, dt)
        angular = 0.0
        if not self._close:
            lateral = max(lateral, 0.0)  # keep driving towards it; turning does the rest
            bearing = wrap_degrees(math.degrees(math.atan2(dy, dx) - facing))
            angular = self.angular.update(bearing, dt)
        lateral = self._slew(lateral, dt)
        if not self.forwards:
            lateral = -lateral
        left, right = _prioritize_turning(lateral, angular, self.max_volts)
        return DriveCommand(left, right)

    def done(self) -> bool:
        return self._done


@dataclass
class Boomerang:
    """Drive to a pose (x, y, heading) by chasing a "carrot" point (LemLib ``moveToPose``).

    The carrot sits ``lead`` x distance behind the target along the target
    heading, so the robot curves in and arrives already facing the right way.
    Within ``settle_radius_in`` the carrot locks onto the target and the
    angular output squares up to the target heading.
    """

    x: float
    y: float
    heading: float
    lead: float = 0.6
    max_volts: float = 9.0  # full-speed curves slide on omni wheels and miss the pose
    slew_volts_per_s: float = 60.0
    lateral: PID = field(default_factory=default_lateral)
    angular: PID = field(default_factory=default_angular)
    settle_radius_in: float = 4.0
    position_tolerance_in: float = 1.5
    heading_tolerance_deg: float = 3.0

    def __post_init__(self) -> None:
        self._done = False
        self._close = False
        self._held = 0.0
        self._slew = _Slew(self.slew_volts_per_s)

    def step(self, pose: Pose, frame: SensorFrame, dt: float) -> DriveCommand:
        dx, dy = self.x - pose.x, self.y - pose.y
        distance = math.hypot(dx, dy)
        heading_error = wrap_degrees(self.heading - pose.heading)
        ok = (
            distance < self.position_tolerance_in
            and abs(heading_error) < self.heading_tolerance_deg
        )
        self._held = self._held + dt if ok else 0.0
        self._done = self._held >= 0.1

        h = math.radians(self.heading)
        self._close = self._close or distance < self.settle_radius_in
        if self._close:
            cx, cy = self.x, self.y
        else:
            cx = self.x - self.lead * distance * math.cos(h)
            cy = self.y - self.lead * distance * math.sin(h)
        to_carrot = math.degrees(math.atan2(cy - pose.y, cx - pose.x))
        facing = math.radians(pose.heading)
        # Signed distance along the robot's heading: negative means the carrot is behind.
        along = (cx - pose.x) * math.cos(facing) + (cy - pose.y) * math.sin(facing)
        lateral = self.lateral.update(along, dt)
        if self._close:
            angular = self.angular.update(heading_error, dt)
        else:
            lateral = max(lateral, 0.0)
            angular = self.angular.update(wrap_degrees(to_carrot - pose.heading), dt)
        lateral = self._slew(lateral, dt)
        left, right = _prioritize_turning(lateral, angular, self.max_volts)
        return DriveCommand(left, right)

    def done(self) -> bool:
        return self._done


@dataclass
class ProfiledDrive:
    """Drive straight a distance (in) along a motion profile, with heading hold.

    Velocity mode: wheel speed = profile velocity + kp * position error; the
    motors' own velocity loops track it. ``profile`` is "trapezoid" or "scurve".
    """

    distance: float
    geometry: ChassisGeometry
    max_speed_fraction: float = 0.8
    max_accel_in_s2: float = 120.0
    max_jerk_in_s3: float = 1200.0
    profile: str = "trapezoid"
    kp: float = 4.0  # in/s per inch of lag
    heading_kp: float = 0.05  # rad/s per degree
    tolerance_in: float = 0.3

    def __post_init__(self) -> None:
        v = self.max_speed_fraction * self.geometry.max_speed_in_s
        if self.profile == "scurve":
            self._profile = SCurveProfile(
                self.distance, v, self.max_accel_in_s2, self.max_jerk_in_s3
            )
        elif self.profile == "trapezoid":
            self._profile = TrapezoidProfile(self.distance, v, self.max_accel_in_s2)
        else:
            raise ValueError("profile must be 'trapezoid' or 'scurve'")
        self._t = 0.0
        self._start: Pose | None = None
        self._done = False

    def step(self, pose: Pose, frame: SensorFrame, dt: float) -> DriveCommand:
        if self._start is None:
            self._start = pose
        start = self._start
        h = math.radians(start.heading)
        travelled = (pose.x - start.x) * math.cos(h) + (pose.y - start.y) * math.sin(h)
        target = self._profile.sample(self._t)
        self._t += dt
        speed = target.velocity + self.kp * (target.position - travelled)
        turn = self.heading_kp * wrap_degrees(start.heading - pose.heading)
        finished = self._t >= self._profile.duration
        self._done = finished and abs(self.distance - travelled) < self.tolerance_in
        if finished and not self._done and self._t > self._profile.duration + 1.0:
            self._done = True  # give up rather than creep forever
        left, right = self.geometry.wheel_speeds(speed, turn)
        return DriveCommand(left, right, mode="velocity")

    def done(self) -> bool:
        return self._done

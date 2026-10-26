"""What controllers produce, and the drivetrain facts they need."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Protocol

from vexsim.algorithms.localization.base import Pose
from vexsim.config.robot import RobotConfig
from vexsim.devices.frame import SensorFrame
from vexsim.v5 import CARTRIDGE_FREE_RPM


@dataclass(frozen=True)
class DriveCommand:
    """Left/right drive output: volts (-12..12), or wheel surface speed in in/s."""

    left: float
    right: float
    mode: Literal["voltage", "velocity"] = "voltage"

    @classmethod
    def stop(cls) -> DriveCommand:
        return cls(0.0, 0.0)


@dataclass(frozen=True)
class ChassisGeometry:
    """Facts about the left and right sides a controller needs (inches)."""

    track_width_in: float
    wheel_diameter_in: float
    max_speed_in_s: float  # wheel surface speed at rated motor speed

    @classmethod
    def from_config(cls, config: RobotConfig) -> ChassisGeometry:
        dt = config.drivetrain
        if dt.type not in ("differential", "hdrive"):
            raise ValueError(
                "chassis motions drive the left and right sides of a differential drive or "
                f"H-drive; an {dt.type} needs its own controller (e.g. in C++, kind: pros)"
            )
        left, right = dt.gearing["left"], dt.gearing["right"]

        def side_y(group) -> float:
            return sum(dt.wheel(w).pos_in[1] for w in group.wheels) / len(group.wheels)

        wheels = [dt.wheel(w) for w in (*left.wheels, *right.wheels)]
        diameter = sum(w.diameter_in for w in wheels) / len(wheels)
        rpm = CARTRIDGE_FREE_RPM[left.cartridge] * left.speed_ratio
        return cls(
            track_width_in=side_y(left) - side_y(right),
            wheel_diameter_in=diameter,
            max_speed_in_s=rpm / 60.0 * math.pi * diameter,
        )

    def wheel_speeds(self, linear_in_s: float, angular_rad_s: float) -> tuple[float, float]:
        """Left/right surface speeds for a body speed and yaw rate (CCW positive)."""
        half = self.track_width_in / 2.0
        return linear_in_s - angular_rad_s * half, linear_in_s + angular_rad_s * half


class Controller(Protocol):
    """A one-shot motion: built with its target, stepped every control tick until done."""

    def step(self, pose: Pose, frame: SensorFrame, dt: float) -> DriveCommand: ...

    def done(self) -> bool: ...


def wrap_degrees(angle: float) -> float:
    """Angle in (-180, 180]."""
    wrapped = (angle + 180.0) % 360.0 - 180.0
    return 180.0 if wrapped == -180.0 else wrapped


def scale_to_limit(left: float, right: float, limit: float) -> tuple[float, float]:
    """Scale both sides down together (keeping their ratio) so neither exceeds ``limit``."""
    biggest = max(abs(left), abs(right))
    if biggest <= limit or biggest == 0:
        return left, right
    k = limit / biggest
    return left * k, right * k

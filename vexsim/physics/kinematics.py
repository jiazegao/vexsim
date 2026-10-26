"""Drive kinematics from the robot config: which gear-group speeds make a body motion.

A wheel that doesn't slip where it grips turns at

    w_wheel * r * cos(g) = a . v_contact

where ``a`` is its grip direction (rolling direction turned by the roller
angle ``g``; see wheel.py) and ``v_contact`` the ground velocity of its
contact point. That is linear in the body motion (forward, left, yaw rate)
of the footprint center, so each gear group gets one row of a matrix ``K``:
group motor speed = ``K @ (forward, left, yaw)``. Wheels geared together
average their rows (if they disagree, they scrub).

``K`` has rank 3 when the drivetrain can move in any direction while turning
(X-drive, mecanum, H-drive), and rank 2 for a differential drive.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from vexsim.config.robot import RobotConfig
from vexsim.units import in_to_m, rpm_to_rad_s
from vexsim.v5 import CARTRIDGE_FREE_RPM


@dataclass(frozen=True)
class DriveKinematics:
    groups: tuple[str, ...]
    matrix: np.ndarray  # (groups, 3): motor rad/s per (forward m/s, left m/s, CCW rad/s)
    rated_rad_s: np.ndarray  # each group's rated motor speed

    @classmethod
    def from_config(cls, config: RobotConfig) -> DriveKinematics:
        dt = config.drivetrain
        rows, rated = [], []
        for gear in dt.gearing.values():
            wheel_rows = []
            for name in gear.wheels:
                w = dt.wheel(name)
                px, py = in_to_m(w.pos_in[0]), in_to_m(w.pos_in[1])
                grip = math.radians(w.heading_deg + w.roller_angle)
                c, s = math.cos(grip), math.sin(grip)
                # grip-direction surface speed per unit motor speed
                radius = in_to_m(w.diameter_in) / 2
                surface = radius * gear.speed_ratio * math.cos(math.radians(w.roller_angle))
                wheel_rows.append(np.array([c, s, -py * c + px * s]) / surface)
            rows.append(np.mean(wheel_rows, axis=0))
            rated.append(rpm_to_rad_s(CARTRIDGE_FREE_RPM[gear.cartridge]))
        return cls(tuple(dt.gearing), np.array(rows), np.array(rated))

    @property
    def rank(self) -> int:
        return int(np.linalg.matrix_rank(self.matrix, tol=1e-9 * np.abs(self.matrix).max()))

    @property
    def holonomic(self) -> bool:
        """Can drive in any direction while turning."""
        return self.rank == 3

    def group_speeds(self, forward: float, left: float, yaw: float) -> dict[str, float]:
        """Motor shaft speed (rad/s) per group for a body motion (m/s, m/s, rad/s CCW)."""
        speeds = self.matrix @ (forward, left, yaw)
        return dict(zip(self.groups, (float(v) for v in speeds), strict=True))

    def top_speeds(self) -> np.ndarray:
        """Fastest (forward m/s, sideways m/s, yaw rad/s), each alone, at rated motor speed.

        A direction the drivetrain can't move in on its own reads 0.
        """
        need = np.abs(self.matrix / self.rated_rad_s[:, None]).max(axis=0)
        return np.where(need > 1e-12, 1.0 / np.maximum(need, 1e-12), 0.0)

    def fractions(self, forward: float, left: float, yaw: float) -> dict[str, float]:
        """Each group's fraction of rated speed (-1..1) for stick-style inputs.

        Each input is -1..1 of the top speed in that direction alone. When the
        combination asks a group for more than its rated speed, every group is
        scaled down together, so the robot keeps the commanded direction.
        """
        body = self.top_speeds() * (forward, left, yaw)
        fractions = self.matrix @ body / self.rated_rad_s
        fractions /= max(1.0, float(np.abs(fractions).max(initial=0.0)))
        return dict(zip(self.groups, (float(v) for v in fractions), strict=True))

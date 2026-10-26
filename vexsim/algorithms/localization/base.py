"""The localizer interface and the pose type algorithms work in."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from vexsim.devices.frame import SensorFrame
from vexsim.units import m_to_in


@dataclass(frozen=True)
class Pose:
    """Field-frame pose of the robot's footprint center: inches, and degrees counter-clockwise."""

    x: float
    y: float
    heading: float

    @classmethod
    def from_si(cls, pose: tuple[float, float, float]) -> Pose:
        x, y, heading = pose
        return cls(m_to_in(x), m_to_in(y), math.degrees(heading))

    def distance_to(self, other: Pose) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def __str__(self) -> str:
        return f"Pose(x={self.x:.2f}, y={self.y:.2f}, heading={self.heading:.1f})"

    def heading_error(self, other: Pose) -> float:
        """Smallest signed angle (degrees) from ``other`` to this pose."""
        return (self.heading - other.heading + 180.0) % 360.0 - 180.0


class Localizer(Protocol):
    name: str

    def reset(self, pose: Pose, frame: SensorFrame) -> None:
        """Start tracking from ``pose``, taking the current readings as the zero point."""

    def update(self, frame: SensorFrame) -> Pose:
        """Fold in a new frame of readings and return the current estimate."""

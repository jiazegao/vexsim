"""Arc odometry from tracking wheels or drive encoders, optionally with an IMU heading.

The standard method used by most VEX odometry (LemLib, the 5225 "pilons" notes):
between updates the robot is assumed to move along a circular arc. With
heading change dtheta, a vertical tracker at lateral offset ``y`` that rolled
``dV`` means the tracking center moved ``dV + y * dtheta`` forward; a
horizontal tracker at longitudinal offset ``x`` that rolled ``dH`` means it
moved ``dH - x * dtheta`` to the left. Each is turned into an arc chord
(scale ``2 sin(dtheta/2) / dtheta``) and rotated by the mid-step heading.

Offsets are measured from the tracking center (the footprint center): vertical
trackers by their lateral position (+left), horizontal ones by their
longitudinal position (+forward).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from vexsim.algorithms.localization.base import Pose
from vexsim.devices.frame import SensorFrame


@dataclass(frozen=True)
class RotationTracker:
    """A tracking wheel on a Rotation sensor."""

    port: int
    diameter_in: float
    offset_in: float
    reversed: bool = False

    def distance_in(self, frame: SensorFrame) -> float | None:
        reading = frame.rotation.get(self.port)
        if reading is None:
            return None
        degrees = reading.position_cdeg / 100.0
        return (-degrees if self.reversed else degrees) / 360.0 * math.pi * self.diameter_in


@dataclass(frozen=True)
class MotorTracker:
    """A drive side measured by its motor encoders (averaged). Negative ports are reversed."""

    ports: tuple[int, ...]
    wheel_diameter_in: float
    ratio: float  # wheel speed / motor speed
    offset_in: float

    def distance_in(self, frame: SensorFrame) -> float | None:
        total = 0.0
        for port in self.ports:
            reading = frame.motors.get(abs(port))
            if reading is None:
                return None
            total += reading.position_deg if port > 0 else -reading.position_deg
        degrees = total / len(self.ports) * self.ratio
        return degrees / 360.0 * math.pi * self.wheel_diameter_in


Tracker = RotationTracker | MotorTracker


class ArcOdometry:
    def __init__(
        self,
        name: str,
        vertical: Sequence[Tracker],
        horizontal: Sequence[Tracker] = (),
        *,
        imu_port: int | None = None,
    ):
        if not vertical:
            raise ValueError("odometry needs at least one vertical tracker")
        if imu_port is None:
            if len(vertical) < 2:
                raise ValueError("without an IMU, odometry needs two vertical trackers for heading")
            if vertical[0].offset_in == vertical[1].offset_in:
                raise ValueError("the two vertical trackers need different lateral offsets")
        self.name = name
        self.vertical = list(vertical)
        self.horizontal = list(horizontal)
        self.imu_port = imu_port
        self.pose = Pose(0.0, 0.0, 0.0)
        self._last: dict[int, float] = {}
        self._heading = 0.0  # radians, CCW
        self._imu_zero = 0.0
        self._heading_zero = 0.0
        self._wheel_heading_zero = 0.0

    def reset(self, pose: Pose, frame: SensorFrame) -> None:
        readings = self._read(frame)
        if readings is None:
            raise ValueError(f"{self.name}: sensors are not ready (IMU still calibrating?)")
        self.pose = pose
        self._heading = self._heading_zero = math.radians(pose.heading)
        self._last = readings
        if self.imu_port is not None:
            self._imu_zero = frame.imu[self.imu_port].rotation_deg
        else:
            self._wheel_heading_zero = self._wheel_heading(readings)

    def update(self, frame: SensorFrame) -> Pose:
        readings = self._read(frame)
        if readings is None:
            return self.pose  # a sensor has no data yet; hold the estimate

        if self.imu_port is not None:
            clockwise = frame.imu[self.imu_port].rotation_deg - self._imu_zero
            heading = self._heading_zero - math.radians(clockwise)
        else:
            heading = self._heading_zero + self._wheel_heading(readings) - self._wheel_heading_zero
        dtheta = heading - self._heading

        def delta(index: int) -> float:
            return readings[index] - self._last[index]

        forward = sum(delta(i) + t.offset_in * dtheta for i, t in enumerate(self.vertical)) / len(
            self.vertical
        )
        left = 0.0
        if self.horizontal:
            base = len(self.vertical)
            left = sum(
                delta(base + i) - t.offset_in * dtheta for i, t in enumerate(self.horizontal)
            ) / len(self.horizontal)

        chord = 1.0 if abs(dtheta) < 1e-9 else 2.0 * math.sin(dtheta / 2.0) / dtheta
        mid = self._heading + dtheta / 2.0
        c, s = math.cos(mid), math.sin(mid)
        dx = chord * (forward * c - left * s)
        dy = chord * (forward * s + left * c)

        self._heading = heading
        self._last = readings
        self.pose = Pose(self.pose.x + dx, self.pose.y + dy, math.degrees(heading))
        return self.pose

    def _read(self, frame: SensorFrame) -> dict[int, float] | None:
        trackers = [*self.vertical, *self.horizontal]
        readings = {}
        for i, tracker in enumerate(trackers):
            value = tracker.distance_in(frame)
            if value is None:
                return None
            readings[i] = value
        if self.imu_port is not None and frame.imu.get(self.imu_port) is None:
            return None
        return readings

    def _wheel_heading(self, readings: dict[int, float]) -> float:
        a, b = self.vertical[0], self.vertical[1]
        # A vertical tracker at offset y rolls (forward - y * heading), so their difference
        # gives the heading.
        return (readings[1] - readings[0]) / (a.offset_in - b.offset_in)

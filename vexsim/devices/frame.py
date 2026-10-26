"""Sensor readings as robot code sees them: PROS units and sign conventions.

* Motor position in degrees, velocity in rpm, current in mA, voltage in mV.
  Values are raw: a motor on a negative config port reads backwards, and the
  robot code reverses it, as with ``pros::Motor(-4)``.
* Rotation sensor position in centidegrees (int); ``reversed`` works the same way.
* IMU rotation and heading in degrees, **clockwise positive** (VEX convention),
  ``None`` while calibrating (PROS returns PROS_ERR).
* Distance in mm (int), ``None`` when nothing is in range.
* GPS position in meters and heading in degrees **clockwise from +y** (the GPS's
  "north"), in the field frame, for the sensor itself: the robot code applies
  its offset. ``None`` until the sensor's first fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MotorReading:
    position_deg: float
    velocity_rpm: float
    current_ma: int
    voltage_mv: int
    temperature_c: float
    torque_nm: float
    power_w: float
    over_temp: bool
    over_current: bool


@dataclass(frozen=True)
class RotationReading:
    position_cdeg: int  # cumulative
    velocity_cdeg_s: float

    @property
    def angle_cdeg(self) -> int:
        """Absolute angle 0..35999, as get_angle() reports."""
        return self.position_cdeg % 36000


@dataclass(frozen=True)
class ImuReading:
    rotation_deg: float  # cumulative, clockwise positive
    gyro_z_deg_s: float  # clockwise positive

    @property
    def heading_deg(self) -> float:
        """0 <= heading < 360, as get_heading() reports."""
        return self.rotation_deg % 360.0


@dataclass(frozen=True)
class GpsReading:
    x_m: float  # the sensor's position, field frame
    y_m: float
    heading_deg: float  # where its camera faces, clockwise from +y, 0..360
    rotation_deg: float  # the same heading, cumulative
    error_m: float  # the sensor's own estimate of its position error
    gyro_z_deg_s: float  # clockwise positive
    fix: bool  # this sample read the code strip (else heading is dead-reckoned)


@dataclass(frozen=True)
class SensorFrame:
    time: float  # seconds of simulation time
    motors: dict[int, MotorReading | None] = field(default_factory=dict)
    rotation: dict[int, RotationReading | None] = field(default_factory=dict)
    imu: dict[int, ImuReading | None] = field(default_factory=dict)
    distance: dict[int, int | None] = field(default_factory=dict)
    gps: dict[int, GpsReading | None] = field(default_factory=dict)

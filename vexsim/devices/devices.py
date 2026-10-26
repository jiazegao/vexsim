"""Simulated V5 smart devices: sample the physics, add errors, publish after a latency.

Each device is sampled by a world event every ``period_ms`` (at sensor
priority, before controllers run in the same tick). A sample becomes visible
``latency_ms`` later. Readings follow PROS units and conventions (see frame.py).
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any

import numpy as np

from vexsim.config.field import FieldConfig
from vexsim.config.robot import DistanceConfig, ImuConfig, RotationConfig
from vexsim.devices.frame import ImuReading, MotorReading, RotationReading
from vexsim.devices.specs import DistanceSensorSpec, ImuSpec, MotorSensorSpec, RotationSensorSpec
from vexsim.physics.motor import V5Motor
from vexsim.physics.robot import Robot
from vexsim.units import in_to_m, rad_s_to_rpm


class Device:
    """Latency queue shared by all devices."""

    kind = "device"

    def __init__(self, port: int, period_ms: float, latency_ms: float):
        self.port = port
        self.period_ms = period_ms
        self._latency_us = round(latency_ms * 1000)
        self._pending: deque[tuple[int, Any]] = deque()
        self.value: Any = None
        self.published_at_us: int | None = None

    def sample(self, now_us: int) -> None:
        self._pending.append((now_us + self._latency_us, self.measure(now_us)))
        self.publish(now_us)

    def publish(self, now_us: int) -> None:
        while self._pending and self._pending[0][0] <= now_us:
            self.published_at_us, self.value = self._pending.popleft()

    def measure(self, now_us: int) -> Any:
        raise NotImplementedError

    def integrate(self, robot: Robot, dt: float) -> None:
        """Called after every physics step, for sensors that accumulate motion."""


def _quantize(value: float, step: float) -> float:
    return round(value / step) * step if step > 0 else value


class MotorDevice(Device):
    kind = "motor"

    def __init__(self, port: int, motor: V5Motor, spec: MotorSensorSpec, rng: np.random.Generator):
        super().__init__(port, spec.period_ms, spec.latency_ms)
        self.motor, self.spec, self.rng = motor, spec, rng
        counts = spec.counts_per_core_rev * motor.ratio
        self.degrees_per_count = 360.0 / counts if counts > 0 else 0.0
        self.zero_deg = 0.0  # the motor's encoder zero (PROS set_zero_position), raw degrees
        self.rated_rpm = rad_s_to_rpm(motor.rated_speed)

    def measure(self, now_us: int) -> MotorReading:
        m = self.motor
        noise = self.rng.normal(0.0, self.spec.velocity_noise * self.rated_rpm)
        return MotorReading(
            position_deg=_quantize(math.degrees(m.position), self.degrees_per_count),
            velocity_rpm=rad_s_to_rpm(m.velocity_estimate) + noise,
            current_ma=round(abs(m.current) * 1000),
            voltage_mv=round(m.voltage * 1000),
            temperature_c=m.temperature_c,
            torque_nm=m.torque,
            power_w=m.power_out,
            over_temp=m.over_temp,
            over_current=m.current_limited,
        )


class RotationDevice(Device):
    """A V5 Rotation Sensor; when the config gives it a tracking wheel, it measures one.

    The wheel's travel is integrated every physics step from the true contact
    velocity at its true mounting point, with its true diameter. Localizers
    only know the configured geometry, so the per-device errors show up as
    odometry error.
    """

    kind = "rotation"

    def __init__(
        self,
        cfg: RotationConfig,
        robot: Robot,
        spec: RotationSensorSpec,
        rng: np.random.Generator,
        static_rng: np.random.Generator,
    ):
        super().__init__(cfg.port, spec.period_ms, spec.latency_ms)
        self.spec, self.rng = spec, rng
        self.sign = -1.0 if cfg.reversed else 1.0  # raw direction; the code reverses it back
        self.angle = 0.0  # true wheel rotation, rad
        self._last_angle_deg = 0.0
        self._lifted_until = -1.0
        self.tracking = cfg.tracking_wheel is not None
        if self.tracking:
            tw = cfg.tracking_wheel
            offset = static_rng.normal(0.0, in_to_m(spec.offset_error_in), size=2)
            mount = np.array([in_to_m(tw.pos_in[0]), in_to_m(tw.pos_in[1])]) + offset
            self.rel = mount - robot.cg_offset
            self.heading = math.radians(tw.heading_deg)
            self.radius = (
                in_to_m(tw.diameter_in) / 2 * (1 + static_rng.normal(0.0, spec.diameter_error))
            )

    def integrate(self, robot: Robot, dt: float) -> None:
        if not self.tracking:
            return
        if robot.time < self._lifted_until:
            return
        spec = self.spec
        if spec.liftoff_rate_hz > 0 and self.rng.random() < spec.liftoff_rate_hz * dt:
            self._lifted_until = robot.time + spec.liftoff_duration_s
            return
        vx, vy = robot.point_velocity(self.rel)
        c, s = math.cos(self.heading), math.sin(self.heading)
        along, across = c * vx + s * vy, -s * vx + c * vy
        self.angle += along * dt / self.radius
        if spec.scrub > 0 and across:
            self.angle += self.rng.normal(0.0, spec.scrub * abs(across) * dt / self.radius)

    def measure(self, now_us: int) -> RotationReading:
        spec = self.spec
        degrees = _quantize(self.sign * math.degrees(self.angle), spec.resolution_deg)
        degrees += self.rng.normal(0.0, spec.noise_deg) if spec.noise_deg else 0.0
        velocity = (degrees - self._last_angle_deg) / (self.period_ms / 1000.0)
        self._last_angle_deg = degrees
        return RotationReading(position_cdeg=round(degrees * 100), velocity_cdeg_s=velocity * 100)


class ImuDevice(Device):
    """V5 Inertial Sensor heading.

    The gyro has a per-device bias, scale error and white noise. Calibration
    (``calibrate()``, automatic at start) averages the gyro for ``calibration_s``
    and subtracts that average from then on, so the robot must stand still:
    any motion during calibration becomes a heading drift. Scale error is not
    calibrated out, matching VEX's documentation.
    """

    kind = "imu"

    def __init__(
        self,
        cfg: ImuConfig,
        robot: Robot,
        spec: ImuSpec,
        rng: np.random.Generator,
        static_rng: np.random.Generator,
    ):
        super().__init__(cfg.port, spec.period_ms, spec.latency_ms)
        self.spec, self.rng, self.robot = spec, rng, robot
        self.scale = 1.0 + static_rng.normal(0.0, spec.scale_error)
        self.bias = math.radians(static_rng.normal(0.0, spec.raw_bias_deg_s))  # rad/s
        self._last_true = robot.heading
        self._heading = 0.0  # integrated, CCW, rad
        self._bias_estimate = 0.0
        self._calibration: list[float] | None = None
        self._calibration_end_us = 0
        self.calibrate(0)

    @property
    def calibrating(self) -> bool:
        return self._calibration is not None

    def calibrate(self, now_us: int) -> None:
        """Start calibration (PROS ``reset()``); heading is 0 when it finishes."""
        self._calibration = []
        self._calibration_end_us = now_us + round(self.spec.calibration_s * 1e6)

    def finish_boot_calibration(self, now_us: int) -> None:
        """Complete calibration at once, as if the robot stood still through it.

        On the V5 the IMU calibrates when the brain powers on, long before a
        program starts. The estimate gets the error an average of the still
        samples would have.
        """
        samples = max(1, round(self.spec.calibration_s * 1000.0 / self.period_ms))
        sigma = math.radians(self.spec.rate_noise_deg_s) / math.sqrt(samples)
        self._bias_estimate = self.bias + (self.rng.normal(0.0, sigma) if sigma else 0.0)
        self._calibration = None
        self._heading = 0.0
        self._last_true = self.robot.heading
        self._pending.clear()
        self.value = ImuReading(rotation_deg=0.0, gyro_z_deg_s=0.0)
        self.published_at_us = now_us

    def measure(self, now_us: int) -> ImuReading | None:
        spec = self.spec
        dt = self.period_ms / 1000.0
        true = self.robot.heading
        true_rate = (true - self._last_true) / dt
        self._last_true = true
        self.bias += math.radians(self.rng.normal(0.0, spec.bias_walk_deg_s * math.sqrt(dt)))
        noise = (
            math.radians(self.rng.normal(0.0, spec.rate_noise_deg_s))
            if spec.rate_noise_deg_s
            else 0.0
        )
        rate = self.scale * true_rate + self.bias + noise

        if self._calibration is not None:
            self._calibration.append(rate)
            if now_us < self._calibration_end_us:
                return None
            self._bias_estimate = float(np.mean(self._calibration))
            self._calibration = None
            self._heading = 0.0
            return ImuReading(rotation_deg=0.0, gyro_z_deg_s=0.0)

        corrected = rate - self._bias_estimate
        self._heading += corrected * dt
        heading_noise = (
            self.rng.normal(0.0, spec.heading_noise_deg) if spec.heading_noise_deg else 0.0
        )
        return ImuReading(
            rotation_deg=-math.degrees(self._heading) + heading_noise,
            gyro_z_deg_s=-math.degrees(corrected),
        )


class DistanceDevice(Device):
    """V5 Distance Sensor: a ray from the sensor to the nearest field wall."""

    kind = "distance"

    def __init__(
        self,
        cfg: DistanceConfig,
        robot: Robot,
        field: FieldConfig,
        spec: DistanceSensorSpec,
        rng: np.random.Generator,
    ):
        super().__init__(cfg.port, spec.period_ms, spec.latency_ms)
        self.spec, self.rng, self.robot = spec, rng, robot
        self.mount = (in_to_m(cfg.pos_in[0]), in_to_m(cfg.pos_in[1]))
        self.heading = math.radians(cfg.heading_deg)
        self.half_size = (in_to_m(field.size_in[0]) / 2, in_to_m(field.size_in[1]) / 2)

    def true_distance_mm(self) -> float | None:
        x, y, heading = self.robot.pose
        c, s = math.cos(heading), math.sin(heading)
        ox = x + c * self.mount[0] - s * self.mount[1]
        oy = y + s * self.mount[0] + c * self.mount[1]
        return ray_to_walls(ox, oy, heading + self.heading, *self.half_size)

    def measure(self, now_us: int) -> int | None:
        spec = self.spec
        true = self.true_distance_mm()
        if true is None or not spec.min_range_mm <= true <= spec.max_range_mm:
            return None
        sigma = spec.short_noise_mm if true < 200.0 else spec.long_noise_fraction * true
        reading = true + (self.rng.normal(0.0, sigma) if sigma else 0.0)
        return max(round(reading), 0)


def ray_to_walls(x: float, y: float, angle: float, half_w: float, half_h: float) -> float | None:
    """Distance (mm) from (x, y) along ``angle`` to the inside of a centered rectangle."""
    if abs(x) >= half_w or abs(y) >= half_h:
        return None  # sensor outside the field
    dx, dy = math.cos(angle), math.sin(angle)
    hits = []
    if dx > 1e-12:
        hits.append((half_w - x) / dx)
    elif dx < -1e-12:
        hits.append((-half_w - x) / dx)
    if dy > 1e-12:
        hits.append((half_h - y) / dy)
    elif dy < -1e-12:
        hits.append((-half_h - y) / dy)
    return min(hits) * 1000.0

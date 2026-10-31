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
from vexsim.config.robot import DistanceConfig, GpsConfig, ImuConfig, RotationConfig
from vexsim.devices.frame import GpsReading, ImuReading, MotorReading, RotationReading
from vexsim.devices.specs import (
    DistanceSensorSpec,
    GpsSpec,
    ImuSpec,
    MotorSensorSpec,
    RotationSensorSpec,
)
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
        sigma = self.spec.velocity_noise * self.rated_rpm
        noise = self.rng.normal(0.0, sigma) if sigma else 0.0
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
        drawn = static_rng.normal(0.0, spec.scale_error)
        self.scale = 1.0 + (drawn if cfg.scale_error is None else cfg.scale_error)
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
    """V5 Distance Sensor: a ray from the sensor to the nearest field wall, or to a game
    element when the field has an arena of them."""

    kind = "distance"

    def __init__(
        self,
        cfg: DistanceConfig,
        robot: Robot,
        field: FieldConfig,
        spec: DistanceSensorSpec,
        rng: np.random.Generator,
        arena=None,
    ):
        super().__init__(cfg.port, spec.period_ms, spec.latency_ms)
        self.spec, self.rng, self.robot, self.arena = spec, rng, robot, arena
        self.mount = (in_to_m(cfg.pos_in[0]), in_to_m(cfg.pos_in[1]))
        self.heading = math.radians(cfg.heading_deg)
        self.height = None if cfg.height_in is None else in_to_m(cfg.height_in)
        self.half_size = (in_to_m(field.size_in[0]) / 2, in_to_m(field.size_in[1]) / 2)
        self.blocked_mm: float | None = None  # something held in front of it (a hand): this far
        self.confidence = 0  # the published reading's (0 to 63; 0 with none)
        self._confidences: deque[int] = deque()  # each pending reading's

    def _beam(self) -> tuple[float, float, float]:
        """Where the sensor is (m, field frame) and which way it points (rad)."""
        x, y, heading = self.robot.pose
        c, s = math.cos(heading), math.sin(heading)
        ox = x + c * self.mount[0] - s * self.mount[1]
        oy = y + s * self.mount[0] + c * self.mount[1]
        return ox, oy, heading + self.heading

    def true_distance_mm(self) -> float | None:
        if self.blocked_mm is not None:
            return self.blocked_mm
        ox, oy, angle = self._beam()
        if self.arena is not None:
            meters = self.arena.ray((ox, oy), angle, height=self.height)
            return None if meters is None else meters * 1000.0
        return ray_to_walls(ox, oy, angle, *self.half_size)

    def incidence_deg(self, mm: float) -> float:
        """How far off square the beam meets what it hits ``mm`` away: the angle between the
        beam and the surface's normal, by the wall, element or piece nearest the hit."""
        if self.blocked_mm is not None:
            return 0.0
        ox, oy, angle = self._beam()
        beam = np.array([math.cos(angle), math.sin(angle)])
        hit = np.array([ox, oy]) + beam * (mm / 1000.0)
        hx, hy = self.half_size
        if hx - abs(hit[0]) < hy - abs(hit[1]):
            nearest, normal = hx - abs(hit[0]), np.array([1.0, 0.0])
        else:
            nearest, normal = hy - abs(hit[1]), np.array([0.0, 1.0])
        if self.arena is not None:
            for shape in self.arena.obstacles:
                if (
                    self.height is not None
                    and shape.height is not None
                    and shape.height <= self.height
                ):
                    continue  # the beam passes over it
                gap, out, _ = shape.signed_distance(hit)
                if abs(gap) < abs(nearest):
                    nearest, normal = gap, out
            for center, radius in zip(
                self.arena.pieces.position, self.arena.pieces.radius, strict=True
            ):
                offset = hit - center
                gap = math.hypot(*offset) - radius
                if abs(gap) < abs(nearest) and gap > -radius:
                    nearest, normal = gap, offset / max(math.hypot(*offset), 1e-12)
        return math.degrees(math.acos(min(1.0, abs(float(beam @ normal)))))

    def measure(self, now_us: int) -> int | None:
        spec = self.spec
        true = self.true_distance_mm()
        if true is None or not spec.min_range_mm <= true <= spec.max_range_mm:
            self._confidences.append(0)
            return None
        shaped = spec.glancing_miss or spec.confidence_per_m or spec.confidence_per_deg
        angle = self.incidence_deg(true) if shaped else 0.0
        glancing = angle > spec.glancing_deg and true > spec.glancing_mm
        if spec.glancing_miss and glancing and self.rng.random() < spec.glancing_miss:
            self._confidences.append(0)
            return None
        sigma = spec.short_noise_mm if true < 200.0 else spec.long_noise_fraction * true
        reading = true + (self.rng.normal(0.0, sigma) if sigma else 0.0)
        lost = (
            spec.confidence_per_m * max(true / 1000.0 - 0.2, 0.0) + spec.confidence_per_deg * angle
        )
        self._confidences.append(int(min(max(round(63 - lost), 0), 63)))
        return max(round(reading), 0)

    def publish(self, now_us: int) -> None:
        while self._pending and self._pending[0][0] <= now_us:
            self.published_at_us, self.value = self._pending.popleft()
            self.confidence = self._confidences.popleft()


class GpsDevice(Device):
    """V5 GPS Sensor: a camera that reads the code strip around the field perimeter.

    It has a fix while its camera ray meets a wall between ``min_range_m`` and
    ``max_range_m`` away; position noise grows with that distance. Without a fix
    its internal gyro carries the heading, the position holds, and the error it
    reports grows. Field elements (obstacles, not pieces) block its view.
    Readings are for the sensor itself: the robot code applies its offset
    (``set_offset``), as PROS does.
    """

    kind = "gps"

    def __init__(
        self,
        cfg: GpsConfig,
        robot: Robot,
        field: FieldConfig,
        spec: GpsSpec,
        rng: np.random.Generator,
        arena=None,
    ):
        super().__init__(cfg.port, spec.period_ms, spec.latency_ms)
        self.spec, self.rng, self.robot, self.arena = spec, rng, robot, arena
        self.mount = (in_to_m(cfg.pos_in[0]), in_to_m(cfg.pos_in[1]))
        self.yaw = math.radians(cfg.mount_yaw_deg)
        self.half_size = (in_to_m(field.size_in[0]) / 2, in_to_m(field.size_in[1]) / 2)
        self.offset = (0.0, 0.0)  # set by the robot code: sensor relative to the robot (m)
        self.initial: tuple[float, float, float] | None = None  # pose the code says it starts at
        self._last_true = robot.heading
        self._heading: float | None = None  # clockwise from +y, degrees, unwrapped
        self._position = (0.0, 0.0)
        self._error = 0.0
        self._since_fix = 0.0

    def sensor_pose(self) -> tuple[float, float, float]:
        """(x m, y m, camera direction rad CCW) of the sensor in the field frame."""
        x, y, heading = self.robot.pose
        c, s = math.cos(heading), math.sin(heading)
        mx, my = self.mount
        return x + c * mx - s * my, y + s * mx + c * my, heading + self.yaw

    def range_m(self) -> float | None:
        """Distance along the camera's line of sight to the code strip (m)."""
        x, y, yaw = self.sensor_pose()
        mm = ray_to_walls(x, y, yaw, *self.half_size)
        if mm is None:
            return None
        if self.arena is not None and self.arena.obstacles:
            seen = self.arena.ray((x, y), yaw, pieces=False)
            if seen is not None and seen < mm / 1000.0 - 1e-6:
                return None  # an obstacle hides the strip
        return mm / 1000.0

    def measure(self, now_us: int) -> GpsReading | None:
        spec, rng = self.spec, self.rng
        dt = self.period_ms / 1000.0
        true = self.robot.heading
        rate = -math.degrees(true - self._last_true) / dt  # clockwise
        self._last_true = true
        rate += rng.normal(0.0, spec.gyro_noise_deg_s) if spec.gyro_noise_deg_s else 0.0
        distance = self.range_m()
        fix = distance is not None and spec.min_range_m <= distance <= spec.max_range_m
        if fix:
            x, y, yaw = self.sensor_pose()
            sigma = spec.position_noise_m + spec.range_noise * distance
            if sigma:
                x, y = x + rng.normal(0.0, sigma), y + rng.normal(0.0, sigma)
            heading = 90.0 - math.degrees(yaw)
            if spec.heading_noise_deg:
                heading += rng.normal(0.0, spec.heading_noise_deg)
            if self._heading is not None:  # keep the cumulative count continuous
                heading = self._heading + (heading - self._heading + 180.0) % 360.0 - 180.0
            self._heading, self._position = heading, (x, y)
            self._error, self._since_fix = sigma, 0.0
        elif self._heading is None:
            return None  # no fix yet
        else:
            self._heading += rate * dt
            self._since_fix += dt
        error = self._error + spec.error_growth_m_s * self._since_fix
        return GpsReading(
            x_m=self._position[0],
            y_m=self._position[1],
            heading_deg=self._heading % 360.0,
            rotation_deg=self._heading,
            error_m=error,
            gyro_z_deg_s=rate,
            fix=fix,
        )


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

"""Sensor timing and error parameters, with named presets.

Every sensor in a robot config picks a preset (``noise: ideal | default | harsh``);
``overrides`` such as ``sensor.imu.scale_error: 0.01`` then adjust one field for
every sensor of that type. "Static" errors (diameter, mounting, scale factor)
are drawn once per device as zero-mean normals with the given standard
deviation; the rest are drawn every sample.

Sources and estimates are listed in docs/models.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from typing import Any


def _check(spec: Any, prefix: str) -> None:
    for f in fields(spec):
        value = getattr(spec, f.name)
        if not (math.isfinite(value) and value >= 0):
            raise ValueError(f"{prefix}.{f.name} must be >= 0, got {value}")
    period = getattr(spec, "period_ms", 1.0)
    if period <= 0 or period != round(period):
        raise ValueError(f"{prefix}.period_ms must be a positive whole number of ms, got {period}")


@dataclass(frozen=True)
class MotorSensorSpec:
    period_ms: float = 10.0  # motors report every 10 ms
    latency_ms: float = 5.0  # estimate
    counts_per_core_rev: float = (
        50.0  # 1800/900/300 counts per output rev (red/green/blue); 0 = exact
    )
    velocity_noise: float = 0.005  # std. dev. as a fraction of rated speed (estimate)

    def __post_init__(self) -> None:
        _check(self, "sensor.motor")


@dataclass(frozen=True)
class RotationSensorSpec:
    period_ms: float = 10.0  # PROS default data rate
    latency_ms: float = 5.0  # estimate
    resolution_deg: float = 0.088  # 4096 counts/rev; 0 = exact
    noise_deg: float = 0.02  # white noise on each reading (estimate)
    diameter_error: float = 0.005  # per device, fraction of diameter (estimate)
    offset_error_in: float = 0.05  # per device and axis, mounting position error (estimate)
    scrub: float = 0.01  # wheel rotation picked up per unit of sideways travel (estimate)
    liftoff_rate_hz: float = 0.0  # random moments when the wheel loses contact
    liftoff_duration_s: float = 0.05

    def __post_init__(self) -> None:
        _check(self, "sensor.rotation")


@dataclass(frozen=True)
class ImuSpec:
    period_ms: float = 10.0
    latency_ms: float = 5.0  # estimate
    calibration_s: float = 2.0  # robot must stay still; heading reads PROS_ERR meanwhile
    raw_bias_deg_s: float = 0.3  # per device gyro bias before calibration removes it (estimate)
    rate_noise_deg_s: float = 0.05  # white noise per sample; sets post-calibration drift
    bias_walk_deg_s: float = 0.0005  # bias random walk per sqrt(second) (estimate)
    scale_error: float = 0.005  # per device, fraction; calibration does NOT remove it
    heading_noise_deg: float = 0.01  # white noise on each heading reading

    def __post_init__(self) -> None:
        _check(self, "sensor.imu")


@dataclass(frozen=True)
class DistanceSensorSpec:
    period_ms: float = 33.0  # ~30 Hz (community-reported)
    latency_ms: float = 10.0  # estimate
    min_range_mm: float = 20.0
    max_range_mm: float = 2000.0
    short_noise_mm: float = 7.5  # std. dev. below 200 mm (VEX: about +/-15 mm)
    long_noise_fraction: float = 0.025  # std. dev. above 200 mm (VEX: about +/-5%)
    # Real sensors miss surfaces met at a glancing angle far away: past glancing_deg off
    # square and glancing_mm, a reading is missed this often (0: never).
    glancing_miss: float = 0.0
    glancing_deg: float = 45.0
    glancing_mm: float = 1500.0
    # The confidence (0 to 63) a reading comes with: 63, less this per meter past 0.2 m and
    # per degree off square.
    confidence_per_m: float = 0.0
    confidence_per_deg: float = 0.0

    def __post_init__(self) -> None:
        _check(self, "sensor.distance")
        if self.glancing_miss > 1:
            raise ValueError("sensor.distance.glancing_miss is a probability: 0 to 1")


@dataclass(frozen=True)
class GpsSpec:
    period_ms: float = 20.0  # PROS's default data rate (estimate)
    latency_ms: float = 20.0  # camera exposure and processing (estimate)
    position_noise_m: float = 0.005  # std. dev. close to the code strip (estimate)
    range_noise: float = 0.004  # extra std. dev. per meter to the strip it reads (estimate)
    heading_noise_deg: float = 0.3  # (estimate)
    min_range_m: float = 0.3  # closer than this the camera sees too little strip (estimate)
    max_range_m: float = 4.0  # farther than this the strip is too small to read (estimate)
    gyro_noise_deg_s: float = 0.1  # the internal gyro that carries heading between fixes
    error_growth_m_s: float = 0.05  # reported error growth while it has no fix (estimate)

    def __post_init__(self) -> None:
        _check(self, "sensor.gps")


SPEC_TYPES: dict[str, type] = {
    "motor": MotorSensorSpec,
    "rotation": RotationSensorSpec,
    "imu": ImuSpec,
    "distance": DistanceSensorSpec,
    "gps": GpsSpec,
}

_IDEAL = {
    "motor": MotorSensorSpec(latency_ms=0, counts_per_core_rev=0, velocity_noise=0),
    "rotation": RotationSensorSpec(
        latency_ms=0, resolution_deg=0, noise_deg=0, diameter_error=0, offset_error_in=0, scrub=0
    ),
    "imu": ImuSpec(
        latency_ms=0,
        raw_bias_deg_s=0,
        rate_noise_deg_s=0,
        bias_walk_deg_s=0,
        scale_error=0,
        heading_noise_deg=0,
    ),
    "distance": DistanceSensorSpec(latency_ms=0, short_noise_mm=0, long_noise_fraction=0),
    "gps": GpsSpec(
        latency_ms=0,
        position_noise_m=0,
        range_noise=0,
        heading_noise_deg=0,
        min_range_m=0,
        max_range_m=100,
        gyro_noise_deg_s=0,
    ),
}
_HARSH = {
    "motor": MotorSensorSpec(latency_ms=10, velocity_noise=0.02),
    "rotation": RotationSensorSpec(
        latency_ms=10,
        noise_deg=0.05,
        diameter_error=0.015,
        offset_error_in=0.15,
        scrub=0.03,
        liftoff_rate_hz=0.2,
    ),
    "imu": ImuSpec(
        latency_ms=10,
        raw_bias_deg_s=1.0,
        rate_noise_deg_s=0.15,
        bias_walk_deg_s=0.002,
        scale_error=0.015,
        heading_noise_deg=0.03,
    ),
    "distance": DistanceSensorSpec(latency_ms=20, short_noise_mm=15, long_noise_fraction=0.05),
    "gps": GpsSpec(
        latency_ms=40,
        position_noise_m=0.015,
        range_noise=0.01,
        heading_noise_deg=1.0,
        min_range_m=0.5,
        max_range_m=3.0,
        gyro_noise_deg_s=0.3,
    ),
}
PRESETS: dict[str, dict[str, Any]] = {
    "ideal": _IDEAL,
    "default": {kind: cls() for kind, cls in SPEC_TYPES.items()},
    "harsh": _HARSH,
    # Replaying a robot log (vexsim.calibration): the state every millisecond, no errors.
    "replay": {kind: replace(spec, period_ms=1.0) for kind, spec in _IDEAL.items()},
}


def sensor_spec(kind: str, preset: str = "default", overrides: dict[str, float] | None = None):
    """The spec for one sensor type under a preset, with per-field overrides applied."""
    return replace(PRESETS[preset][kind], **(overrides or {}))

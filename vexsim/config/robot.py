"""Robot definition schema: the structure and per-field rules of a robot YAML file.

Values stay in VEX-facing units (inches, degrees, rpm). Cross-field rules
(port conflicts, footprint containment, drivetrain layout) live in
``vexsim.config.checks``. Frames and sign conventions are documented in
docs/conventions.md.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictBool,
    StrictInt,
)

from vexsim.units import in_to_m
from vexsim.v5 import CARTRIDGE_FREE_RPM, SMART_PORT_COUNT

PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Vec2 = tuple[FiniteFloat, FiniteFloat]
Name = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]

Cartridge = Literal["red", "green", "blue"]
WheelType = Literal["omni", "traction", "mecanum"]
DrivetrainType = Literal["differential", "xdrive", "mecanum", "hdrive"]
NoisePreset = Literal["ideal", "default", "harsh"]
BatteryPreset = Literal["v5_default"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_motor_port(port: int) -> int:
    if port == 0 or abs(port) > SMART_PORT_COUNT:
        raise ValueError(
            f"motor port must be 1..{SMART_PORT_COUNT} (negative = reversed), got {port}"
        )
    return port


MotorPort = Annotated[StrictInt, AfterValidator(_check_motor_port)]
SensorPort = Annotated[StrictInt, Field(ge=1, le=SMART_PORT_COUNT)]


def ratio_value(ratio: str | float) -> float:
    """Wheel-side speed divided by motor-side speed.

    ``"36:48"`` means a 36-tooth gear on the motor driving a 48-tooth gear on
    the wheel, so the wheel turns at 36/48 = 0.75x motor speed.
    """
    if isinstance(ratio, str):
        parts = ratio.split(":")
        if len(parts) != 2:
            raise ValueError(
                f"gear ratio {ratio!r} must be 'driving:driven' teeth (e.g. \"36:48\") or a number"
            )
        try:
            driving, driven = float(parts[0]), float(parts[1])
        except ValueError:
            raise ValueError(f"gear ratio {ratio!r} must contain two numbers") from None
        value = driving / driven if driven else math.inf
    else:
        value = float(ratio)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"gear ratio {ratio!r} must be positive and finite")
    return value


def _normalize_ratio(value: object) -> str | float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError("gear ratio must be a number or 'driving:driven' teeth, e.g. \"36:48\"")
    normalized = value.strip() if isinstance(value, str) else float(value)
    ratio_value(normalized)
    return normalized


def _normalize_inertia(value: object) -> str | float:
    if value == "auto":
        return "auto"
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("inertia_kgm2 must be 'auto' or a positive number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("inertia_kgm2 must be positive and finite")
    return float(value)


GearRatio = Annotated[str | float, BeforeValidator(_normalize_ratio)]
Inertia = Annotated[Literal["auto"] | float, BeforeValidator(_normalize_inertia)]


class BodyConfig(_Model):
    mass_kg: PositiveFloat
    inertia_kgm2: Inertia = "auto"
    footprint_in: tuple[PositiveFloat, PositiveFloat]  # length (x) by width (y)
    cg_in: tuple[FiniteFloat, FiniteFloat, PositiveFloat]  # x, y, height above the floor
    battery: BatteryPreset = "v5_default"

    def yaw_inertia_kgm2(self) -> float:
        """Explicit inertia, or a uniform box over the footprint when set to 'auto'."""
        if self.inertia_kgm2 != "auto":
            return self.inertia_kgm2
        length, width = (in_to_m(v) for v in self.footprint_in)
        return self.mass_kg * (length**2 + width**2) / 12.0


class WheelConfig(_Model):
    name: Name
    pos_in: Vec2
    heading_deg: FiniteFloat = 0.0  # rolling direction, CCW from robot +x
    type: WheelType
    diameter_in: PositiveFloat
    drop_in: Annotated[float, Field(ge=0, le=0.5)] = 0.0  # lowered by this much (drop center)


class GearGroupConfig(_Model):
    motors: Annotated[tuple[MotorPort, ...], Field(min_length=1)]
    cartridge: Cartridge
    ratio: GearRatio = 1.0
    wheels: Annotated[tuple[Name, ...], Field(min_length=1)]

    @property
    def speed_ratio(self) -> float:
        return ratio_value(self.ratio)

    @property
    def motor_free_rpm(self) -> float:
        return CARTRIDGE_FREE_RPM[self.cartridge]

    @property
    def wheel_free_rpm(self) -> float:
        return self.motor_free_rpm * self.speed_ratio


class DrivetrainConfig(_Model):
    type: DrivetrainType
    wheels: Annotated[tuple[WheelConfig, ...], Field(min_length=1)]
    gearing: Annotated[dict[Name, GearGroupConfig], Field(min_length=1)]

    def wheel(self, name: str) -> WheelConfig:
        for wheel in self.wheels:
            if wheel.name == name:
                return wheel
        raise KeyError(name)


class TrackingWheelConfig(_Model):
    pos_in: Vec2
    heading_deg: FiniteFloat = 0.0
    diameter_in: PositiveFloat


class ImuConfig(_Model):
    type: Literal["imu"]
    port: SensorPort
    pos_in: Vec2 = (0.0, 0.0)
    mount_yaw_deg: FiniteFloat = 0.0
    noise: NoisePreset = "default"


class RotationConfig(_Model):
    type: Literal["rotation"]
    port: SensorPort
    reversed: StrictBool = False
    tracking_wheel: TrackingWheelConfig | None = None
    noise: NoisePreset = "default"


class DistanceConfig(_Model):
    type: Literal["distance"]
    port: SensorPort
    pos_in: Vec2
    heading_deg: FiniteFloat = 0.0
    noise: NoisePreset = "default"


SensorConfig = Annotated[ImuConfig | RotationConfig | DistanceConfig, Field(discriminator="type")]
SENSOR_TYPES = ("imu", "rotation", "distance")

OverrideKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")]


class RobotConfig(_Model):
    version: Literal[1] = 1
    name: str | None = None
    body: BodyConfig
    drivetrain: DrivetrainConfig
    sensors: tuple[SensorConfig, ...] = ()
    # Dotted model-parameter overrides (e.g. "wheel.omni.lateral_mu"). Accepted
    # now; applied once the targeted models exist (Phase 2+).
    overrides: dict[OverrideKey, bool | int | float | str] = Field(default_factory=dict)


ROBOT_MODELS: tuple[type[BaseModel], ...] = (
    RobotConfig,
    BodyConfig,
    DrivetrainConfig,
    WheelConfig,
    GearGroupConfig,
    TrackingWheelConfig,
    ImuConfig,
    RotationConfig,
    DistanceConfig,
)

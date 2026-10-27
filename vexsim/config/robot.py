"""Robot definition schema: the structure and per-field rules of a robot YAML file.

Values stay in VEX-facing units (inches, degrees, rpm). Cross-field rules
(port conflicts, footprint containment, drivetrain layout) live in
``vexsim.config.checks``. Frames and sign conventions are documented in
docs/conventions.md.
"""

from __future__ import annotations

import math
from functools import lru_cache
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
    model_validator,
)

from vexsim.geometry import Circle, Outline, Polygon, polygon_problem
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


class RectPart(_Model):
    """A rectangle in the robot's shape."""

    type: Literal["rect"]
    pos_in: Vec2 = (0.0, 0.0)  # center
    size_in: tuple[PositiveFloat, PositiveFloat]  # length (along its heading) by width
    heading_deg: FiniteFloat = 0.0  # rotation of its length axis, CCW from robot +x


class CirclePart(_Model):
    """A circle in the robot's shape."""

    type: Literal["circle"]
    pos_in: Vec2 = (0.0, 0.0)  # center
    diameter_in: PositiveFloat


class OutlinePart(_Model):
    """A closed outline in the robot's shape: straight edges from point to point, and from
    the last point back to the first. Its edges mustn't cross."""

    type: Literal["outline"]
    points_in: Annotated[tuple[Vec2, ...], Field(min_length=3)]

    @model_validator(mode="after")
    def _simple(self) -> OutlinePart:
        problem = polygon_problem(self.points_in)
        if problem:
            raise ValueError(
                f"the outline's points (numbered from 0) don't make a shape: {problem}"
            )
        return self


ShapePart = Annotated[RectPart | CirclePart | OutlinePart, Field(discriminator="type")]
SHAPE_TYPES = ("rect", "circle", "outline")


class BodyConfig(_Model):
    mass_kg: PositiveFloat
    inertia_kgm2: Inertia = "auto"
    # The robot seen from above, in the robot frame: either a rectangle centered on the
    # origin, length (x) by width (y), or a shape made of rectangles, circles and outlines
    # (where they overlap they merge: only the outside edge touches anything).
    footprint_in: tuple[PositiveFloat, PositiveFloat] | None = None
    shape: tuple[ShapePart, ...] | None = None
    cg_in: tuple[FiniteFloat, FiniteFloat, PositiveFloat]  # x, y, height above the floor
    battery: BatteryPreset = "v5_default"

    @model_validator(mode="after")
    def _one_shape(self) -> BodyConfig:
        if self.footprint_in is None and self.shape is None:
            raise ValueError(
                "the body needs footprint_in: [length, width] (a rectangle centered on the "
                "robot's origin) or shape: (rectangles, circles and outlines)"
            )
        if self.footprint_in is not None and self.shape is not None:
            raise ValueError("the body has both footprint_in and shape; keep one")
        if self.shape == ():
            raise ValueError("the body's shape needs a part: a rect, a circle or an outline")
        return self

    @property
    def outline(self) -> Outline:
        """The robot seen from above, in inches, robot frame."""
        return _outline(self.footprint_in, self.shape)

    @property
    def size_in(self) -> tuple[float, float]:
        """Length (x) by width (y) of the box around the robot, in its own frame."""
        if self.shape is None:
            return self.footprint_in
        x0, y0, x1, y1 = self.outline.bounds
        return x1 - x0, y1 - y0

    def yaw_inertia_kgm2(self) -> float:
        """Explicit inertia, or a uniform plate over the robot's shape when set to 'auto'
        (a uniform box over the footprint: m(L^2 + W^2)/12)."""
        if self.inertia_kgm2 != "auto":
            return self.inertia_kgm2
        if self.shape is None:
            length, width = (in_to_m(v) for v in self.footprint_in)
            return self.mass_kg * (length**2 + width**2) / 12.0
        area, _, polar = self.outline.moments  # inches
        return self.mass_kg * in_to_m(1.0) ** 2 * polar / area


@lru_cache(maxsize=64)
def _outline(footprint: tuple[float, float] | None, shape: tuple | None) -> Outline:
    if shape is None:
        return Outline([Polygon.rect((0.0, 0.0), footprint)])
    parts = []
    for part in shape:
        if part.type == "rect":
            parts.append(Polygon.rect(part.pos_in, part.size_in, math.radians(part.heading_deg)))
        elif part.type == "circle":
            parts.append(Circle(tuple(part.pos_in), part.diameter_in / 2))
        else:
            parts.append(Polygon.of(part.points_in))
    return Outline(parts)


class WheelConfig(_Model):
    name: Name
    pos_in: Vec2
    heading_deg: FiniteFloat = 0.0  # rolling direction, CCW from robot +x
    type: WheelType
    diameter_in: PositiveFloat
    drop_in: Annotated[float, Field(ge=0, le=0.5)] = 0.0  # lowered by this much (drop center)
    # Mecanum only: axis of the rollers touching the ground, CCW from the rolling
    # direction, seen from above. The usual layout is -45 front-left and back-right,
    # +45 front-right and back-left.
    roller_angle_deg: Annotated[float, Field(gt=-90, lt=90, allow_inf_nan=False)] | None = None

    @property
    def roller_angle(self) -> float:
        """Roller angle in degrees (0 for omni and traction wheels)."""
        return self.roller_angle_deg or 0.0


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


class MechanismConfig(_Model):
    """Motors that drive something other than the wheels: a lift, an intake, an arm.

    The mechanism is one rotating output (a lift's spool, a roller, an arm's
    pivot) geared to its motors. Load values are at that output; positions are
    output degrees from where it starts, positive in its motors' positive
    direction (a negative port is reversed, as in the drive's gearing groups).
    """

    motors: Annotated[tuple[MotorPort, ...], Field(min_length=1)]
    cartridge: Cartridge
    ratio: GearRatio = 1.0  # output speed / motor speed, e.g. "12:48" (a 4:1 reduction)
    inertia_kgm2: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.0  # load, at the output
    # Constant torque pulling the output toward negative angles: a lift's weight
    # times its spool radius. Negative pulls the other way.
    load_torque_nm: FiniteFloat = 0.0
    friction_nm: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.0  # Coulomb, at the output
    # Hard stops, in output degrees from the starting position (so low <= 0 <= high)
    range_deg: tuple[FiniteFloat, FiniteFloat] | None = None

    @property
    def speed_ratio(self) -> float:
        return ratio_value(self.ratio)

    @model_validator(mode="after")
    def _range_contains_start(self) -> MechanismConfig:
        if self.range_deg is not None:
            low, high = self.range_deg
            if not low <= 0.0 <= high or low == high:
                raise ValueError(
                    "range_deg must be [low, high] with low <= 0 <= high: the mechanism starts "
                    "at 0, between its hard stops"
                )
        return self


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
    # This IMU's own scale error, if measured: (reading - true) / true for a full turn, e.g.
    # 0.0025 for an IMU that reads 360.91 deg per real 360. Without it each simulated IMU
    # draws a random one (sensor.imu.scale_error).
    scale_error: Annotated[float, Field(gt=-0.5, lt=0.5, allow_inf_nan=False)] | None = None


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
    # Height of the beam above the floor. Field elements with a height_in at or below it
    # pass under the beam; without it the sensor sees every element.
    height_in: PositiveFloat | None = None
    noise: NoisePreset = "default"


class GpsConfig(_Model):
    type: Literal["gps"]
    port: SensorPort
    pos_in: Vec2  # where the sensor sits
    mount_yaw_deg: FiniteFloat = 0.0  # direction its camera faces, CCW from robot +x
    noise: NoisePreset = "default"


SensorConfig = Annotated[
    ImuConfig | RotationConfig | DistanceConfig | GpsConfig, Field(discriminator="type")
]
SENSOR_TYPES = ("imu", "rotation", "distance", "gps")

OverrideKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")]


class RobotConfig(_Model):
    version: Literal[1] = 1
    name: str | None = None
    body: BodyConfig
    drivetrain: DrivetrainConfig
    mechanisms: dict[Name, MechanismConfig] = Field(default_factory=dict)
    sensors: tuple[SensorConfig, ...] = ()
    # Dotted model-parameter overrides, e.g. "wheel.omni.lateral_mu" (docs/models.md).
    overrides: dict[OverrideKey, bool | int | float | str] = Field(default_factory=dict)


ROBOT_MODELS: tuple[type[BaseModel], ...] = (
    RobotConfig,
    BodyConfig,
    RectPart,
    CirclePart,
    OutlinePart,
    DrivetrainConfig,
    WheelConfig,
    GearGroupConfig,
    MechanismConfig,
    TrackingWheelConfig,
    ImuConfig,
    RotationConfig,
    DistanceConfig,
    GpsConfig,
)

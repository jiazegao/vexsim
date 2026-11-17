"""A run's scene: the robot and the field as the page draws them."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from vexsim.ui.protocol.base import _Message


class WheelMount(_Message):
    name: str
    x: float  # robot frame: +x forward, +y left
    y: float
    heading: float
    diameter: float
    type: str
    roller: float  # mecanum: the ground rollers' angle to the wheel's axis; else 0


class SensorMount(_Message):
    kind: Literal["imu", "distance", "gps"]
    port: int
    x: float  # robot frame
    y: float
    heading: float  # where it faces


class MechanismMount(_Message):
    name: str
    range: tuple[float, float] | None  # hard stops, output degrees from the start


class RobotScene(_Message):
    name: str
    footprint: tuple[float, float]  # length (x) by width (y); of the box around a shape
    # a robot with a body.shape: its edge, as closed loops (robot frame) with the shape on
    # their left; filled together (nonzero), they're the shape. None: the footprint rectangle,
    # centered on the robot's origin
    outline: list[list[tuple[float, float]]] | None = None
    wheels: list[WheelMount]
    sensors: list[SensorMount]
    mechanisms: list[MechanismMount]


class CircleObstacle(_Message):
    shape: Literal["circle"]
    name: str
    x: float
    y: float
    radius: float
    color: str | None
    solid: bool  # False: robots drive over it, only sensors see it


class PolygonObstacle(_Message):
    shape: Literal["polygon"]
    name: str
    points: list[tuple[float, float]]
    color: str | None
    solid: bool


class PieceStyle(_Message):
    radius: float
    color: str | None


class FieldScene(_Message):
    name: str
    size: tuple[float, float]  # inside the walls, centered on the origin
    obstacles: list[Annotated[CircleObstacle | PolygonObstacle, Field(discriminator="shape")]]
    pieces: list[PieceStyle]  # game pieces, in the order frames give their positions

"""Field definition schema: the perimeter, and the game elements on the field.

Elements are fixed obstacles (goals, barriers: rectangles or circles in plan)
and movable game pieces (discs: balls, rings and cylinders by their outer
diameter). Positions are field-frame inches from the center, angles degrees
counter-clockwise from +x (docs/conventions.md).
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, model_validator

from vexsim.config.issues import ConfigIssue

PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Fraction = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Vec2 = tuple[FiniteFloat, FiniteFloat]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ObstacleConfig(_Model):
    """A fixed field element. The robot and pieces can't pass through it unless it's
    low enough to drive over (``solid: false``); a distance sensor sees it unless the
    sensor's beam is above its ``height_in``."""

    type: Literal["obstacle"]
    name: str | None = None
    shape: Literal["rect", "circle"]
    pos_in: Vec2  # center
    size_in: tuple[PositiveFloat, PositiveFloat] | None = None  # rect: length (x) by width (y)
    diameter_in: PositiveFloat | None = None  # circle
    heading_deg: FiniteFloat = 0.0  # rect: rotation of its length axis
    height_in: PositiveFloat | None = None  # top above the floor; omitted = taller than sensors
    solid: StrictBool = True  # false: robots and pieces pass over it (a low base, a line)
    color: str | None = None  # for the viewer, e.g. "#808080"

    @model_validator(mode="after")
    def _shape_size(self) -> ObstacleConfig:
        if self.shape == "rect" and self.size_in is None:
            raise ValueError("a rect obstacle needs size_in: [length, width]")
        if self.shape == "circle" and self.diameter_in is None:
            raise ValueError("a circle obstacle needs diameter_in")
        return self

    @property
    def radius_in(self) -> float:
        """Radius of the circle that contains it."""
        if self.shape == "circle":
            return self.diameter_in / 2
        return math.hypot(*self.size_in) / 2


class PieceConfig(_Model):
    """A movable game piece, modeled as a disc that slides on the tiles."""

    type: Literal["piece"]
    name: str | None = None
    pos_in: Vec2
    diameter_in: PositiveFloat
    mass_kg: PositiveFloat
    friction: NonNegative = 0.4  # ground friction coefficient (sliding plastic on foam)
    restitution: Fraction = 0.3  # bounce off walls, obstacles, robots and other pieces
    color: str | None = None


ElementConfig = Annotated[ObstacleConfig | PieceConfig, Field(discriminator="type")]


class FieldConfig(_Model):
    version: Literal[1] = 1
    name: str = "V5RC field (empty)"
    # Inside-wall dimensions. 144 in is the nominal 6x6 tile grid; real fields
    # measure slightly less between the walls, so measure yours for wall resets.
    size_in: tuple[PositiveFloat, PositiveFloat] = (144.0, 144.0)
    elements: tuple[ElementConfig, ...] = ()

    @property
    def obstacles(self) -> list[ObstacleConfig]:
        return [e for e in self.elements if e.type == "obstacle"]

    @property
    def pieces(self) -> list[PieceConfig]:
        return [e for e in self.elements if e.type == "piece"]


FIELD_MODELS: tuple[type[BaseModel], ...] = (FieldConfig, ObstacleConfig, PieceConfig)


def check_field(cfg: FieldConfig) -> list[ConfigIssue]:
    """Elements must be inside the walls; pieces shouldn't start inside anything."""
    issues = []
    half_x, half_y = cfg.size_in[0] / 2, cfg.size_in[1] / 2
    for i, element in enumerate(cfg.elements):
        x, y = element.pos_in
        if abs(x) >= half_x or abs(y) >= half_y:
            issues.append(
                ConfigIssue(
                    "error", f"elements[{i}].pos_in", f"({x:g}, {y:g}) is outside the walls"
                )
            )
    pieces = [(i, e) for i, e in enumerate(cfg.elements) if e.type == "piece"]
    for i, piece in pieces:
        x, y = piece.pos_in
        r = piece.diameter_in / 2
        if abs(x) + r > half_x or abs(y) + r > half_y:
            issues.append(
                ConfigIssue("warning", f"elements[{i}].pos_in", "the piece overlaps a wall")
            )
        for j, other in enumerate(cfg.elements):
            if j == i or (other.type == "piece" and j < i):
                continue
            if other.type == "piece":
                gap = math.dist((x, y), other.pos_in) - other.diameter_in / 2
            elif not other.solid:
                continue  # a piece may sit on a low element
            else:
                gap = _distance_to(other, (x, y))
            if gap < r - 1e-9:
                what = "piece" if other.type == "piece" else "obstacle"
                issues.append(
                    ConfigIssue(
                        "warning",
                        f"elements[{i}].pos_in",
                        f"the piece starts overlapping {what} elements[{j}]",
                    )
                )
    return issues


def _distance_to(obstacle: ObstacleConfig, point: tuple[float, float]) -> float:
    """Distance (inches) from a point to an obstacle's edge; negative inside."""
    dx, dy = point[0] - obstacle.pos_in[0], point[1] - obstacle.pos_in[1]
    if obstacle.shape == "circle":
        return math.hypot(dx, dy) - obstacle.diameter_in / 2
    h = math.radians(obstacle.heading_deg)
    along = abs(dx * math.cos(h) + dy * math.sin(h)) - obstacle.size_in[0] / 2
    across = abs(-dx * math.sin(h) + dy * math.cos(h)) - obstacle.size_in[1] / 2
    if along <= 0 and across <= 0:
        return max(along, across)
    return math.hypot(max(along, 0.0), max(across, 0.0))

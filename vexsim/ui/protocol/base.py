"""What every part of the protocol uses: the kinds and states by name, the shapes robot code draws,
the base of every message, and how a problem is told."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

ItemKind = Literal[
    "robot",
    "field",
    "scenario",
    "program",
    "project",
    "route",
    "input",
    "log",
    "calsession",
    "robotlog",
    "mcllog",
    "invalid",
]
SessionState = Literal["building", "starting", "running", "paused", "finished", "error", "stopped"]
JobState = Literal["queued", "running", "succeeded", "failed", "cancelled"]
ConfigKind = Literal["robot", "field"]
ResultKind = Literal["bench", "sweeps", "calibrations", "checks"]
Workers = Annotated[int, Field(ge=1, le=64)]
# What robot code draws on the field (vexsim.runtime.drawing), by layer: colors from the
# field's palette, then shapes in inches and degrees, as lists that start with their kind.
# "points" is a run of points of one color and size, as they travel (drawing.packed).
DrawColor = Literal[
    "violet", "blue", "orange", "aqua", "yellow", "magenta", "green", "red", "ink", "muted"
]
Shape = Union[  # noqa: UP007 - a named union, for the TypeScript generator
    tuple[Literal["point"], float, float, DrawColor, float],  # x, y, color, size (pixels)
    tuple[Literal["points"], DrawColor, float, list[float]],  # color, size, each one's x, y
    tuple[Literal["line"], float, float, float, float, DrawColor],  # x1, y1, x2, y2
    tuple[Literal["circle"], float, float, float, DrawColor],  # x, y, radius
    tuple[Literal["ellipse"], float, float, float, float, float, DrawColor],  # x, y, rx, ry, turn
    tuple[Literal["pose"], float, float, float, DrawColor],  # x, y, heading
    tuple[Literal["text"], float, float, str, DrawColor],  # x, y, text
]


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Issue(_Message):
    severity: Literal["error", "warning"]
    location: str  # dotted path into the config, e.g. "drivetrain.wheels[2].diameter_in"
    message: str


class RunProblem(_Message):
    """Why a run can't start (HTTP 422)."""

    error: str
    issues: list[Issue]

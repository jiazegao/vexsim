"""What the UI's server and the browser say to each other.

These pydantic models describe the JSON on both sides: REST bodies, the messages a
session's WebSocket sends (``ServerMessage``) and the commands it takes
(``ClientCommand``). ``frontend/src/protocol.ts`` is generated from them, so the two sides
can't disagree; a test fails when it is stale. Regenerate it with:

    python -m vexsim.ui.protocol frontend/src/protocol.ts

Lengths are inches; angles are degrees, counter-clockwise from +x; times are seconds.
"""

from __future__ import annotations

import sys
import types
import typing
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field

from vexsim.app.launch import RunConfiguration
from vexsim.app.runs import PoseErrorSummary, RunRecord
from vexsim.app.runspec import RunSpec

ItemKind = Literal["robot", "field", "scenario", "program", "project", "input", "log", "invalid"]
SessionState = Literal["building", "starting", "running", "paused", "finished", "error", "stopped"]
JobState = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- REST -------------------------------------------------------------------------------------


class Issue(_Message):
    severity: Literal["error", "warning"]
    location: str  # dotted path into the config, e.g. "drivetrain.wheels[2].diameter_in"
    message: str


class AppInfo(_Message):
    version: str
    workspace: str  # the workspace folder
    workspace_name: str
    python: str
    platform: str


class WorkspaceItem(_Message):
    kind: ItemKind
    path: str  # relative to the workspace, with / separators
    name: str
    detail: str
    problem: str  # why it won't work as it is; empty if it will


class WorkspaceInfo(_Message):
    root: str
    name: str
    items: list[WorkspaceItem]


class SessionInfo(_Message):
    id: str
    spec: RunSpec
    command: str  # the vexsim run command that runs the same thing
    state: SessionState
    message: str | None
    mode: str
    created: float
    run_id: str | None  # where its current (or last) run is recorded


class JobInfo(_Message):
    id: str
    kind: str
    title: str
    state: JobState
    log: list[str]  # from the line asked for (``since``) on
    log_size: int
    result: dict[str, Any] | None
    error: str | None
    created: float
    started: float | None
    finished: float | None


class StartSession(_Message):
    spec: RunSpec
    replace: bool = True  # stop the other sessions first
    name: str | None = None  # what to call its recorded runs (a saved run's name)


class StartJob(_Message):
    kind: Literal["build"]
    project: str  # workspace path of a PROS project


class RunProblem(_Message):
    """Why a run can't start (HTTP 422)."""

    error: str
    issues: list[Issue]


class PreviewRequest(_Message):
    robot: str  # workspace paths
    field: str | None = None


class Preview(_Message):
    """A robot and a field before any run, to show them and drag the robot to its start."""

    robot: RobotScene
    field: FieldScene
    pieces: list[tuple[float, float]]  # where the field config puts the pieces


class RunConfigurations(_Message):
    file: str  # workspace path of the file they're kept in
    configurations: list[RunConfiguration]
    error: str | None = None  # why the file couldn't be read (it is then left alone)


class SaveConfigurations(_Message):
    configurations: list[RunConfiguration]


# --- a session's scene ------------------------------------------------------------------------


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
    footprint: tuple[float, float]  # length (x) by width (y)
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


# --- what a session's WebSocket sends ---------------------------------------------------------


class SessionMessage(_Message):
    type: Literal["session"]
    session: SessionInfo


class StatusMessage(_Message):
    type: Literal["status"]
    state: SessionState
    message: str | None
    mode: str


class Scene(_Message):
    """What doesn't move in a run: the robot and field, and what was asked for."""

    robot: RobotScene
    field: FieldScene
    mode: str
    start: tuple[float, float, float]
    seed: int
    spec: RunSpec
    command: str
    run_id: str | None  # where the run is recorded: .vexsim/runs/<run_id>


class SceneMessage(Scene):
    """Sent when a run starts or restarts."""

    type: Literal["scene"]


class ControllerState(_Message):
    analog: dict[str, int]  # LEFT_X, LEFT_Y, RIGHT_X, RIGHT_Y: -127 to 127
    digital: list[str]  # pressed buttons: L1 L2 R1 R2 UP DOWN LEFT RIGHT X B Y A


class FrameState(_Message):
    """Where everything is at one moment (a recorded run's tape keeps these)."""

    t: float  # simulated time
    phase: str  # initialize, autonomous, opcontrol, done, ...
    pose: tuple[float, float, float]  # where the robot really is: x, y, heading
    estimate: tuple[float, float, float] | None  # where the robot code thinks it is
    speed_in_s: float
    battery: tuple[float, float]  # volts, state of charge (0-1)
    # x, y, heading, slip (0-1: the share of its grip in use), side force (N, + to the left
    # of the wheel's rolling direction); field frame
    wheels: list[tuple[float, float, float, float, float]]
    distance: dict[str, int | None]  # distance sensor port -> mm, None if it sees nothing
    pieces: list[tuple[float, float]]
    contacts: list[tuple[float, float]]  # where the robot touches a wall
    motors: list[tuple[int, float, float, bool]]  # port, current (A), temperature (C), hot
    controller: ControllerState  # what the robot's controller reads
    # IMU port -> heading (0-360, clockwise, as get_heading()) and rotation; None while
    # it calibrates
    imu: dict[str, tuple[float, float] | None]
    # GPS port -> x, y, heading (clockwise from +y), its own error estimate (in), whether
    # it read the field strip; None before its first reading
    gps: dict[str, tuple[float, float, float, float, bool] | None]
    mechanisms: list[float]  # output degrees from the start, in the scene's order
    period_left: float | None  # seconds left in a timed period (match, skills)


class FrameMessage(FrameState):
    """Where everything is, about 60 times a second while running."""

    type: Literal["frame"]
    state: SessionState
    speed: float | None  # asked-for speed; None = as fast as possible
    rate: float  # simulated seconds per real second, lately
    lcd: list[str]  # brain screen lines
    controller_screen: list[str]


class Overlay(_Message):
    """A Python program's chassis motion: its path and target."""

    path: list[tuple[float, float]] | None
    target: tuple[float, float, float | None] | None


class OverlayMessage(Overlay):
    """Sent when the motion's path or target changes."""

    type: Literal["overlay"]


class RecordedMessage(_Message):
    """A run ended (finished, stopped, restarted, failed) and was recorded."""

    type: Literal["recorded"]
    run: RunRecord


# --- recorded runs -----------------------------------------------------------------------------


class TapeEvents(_Message):
    """When what changes seldom changed: [time, the new value]."""

    overlay: list[tuple[float, Overlay]]
    lcd: list[tuple[float, list[str]]]
    controller_screen: list[tuple[float, list[str]]]


class Tape(_Message):
    """A recorded run to scrub: its scene, and a frame every 50 ms of simulated time."""

    scene: Scene
    samples: list[FrameState]
    events: TapeEvents


class Telemetry(_Message):
    """A run's 10 ms telemetry log as columns (at most 5000 rows), for plots: the log's
    columns (time_s, x_in, motor1_current_a, ...) plus error_in and error_deg, the robot
    code's pose error; and when each phase begins."""

    columns: dict[str, list[float | None]]
    phases: list[tuple[float, str]]


class RunDetails(_Message):
    run: RunRecord
    console: list[str]


class RunUpdate(_Message):
    kept: bool | None = None  # keep it when old runs are cleared out
    name: str | None = None


class ReplayRequest(_Message):
    """Open a telemetry log (vexsim run --record) from the workspace, drawn with a robot."""

    log: str
    robot: str
    field: str | None = None


class Replay(_Message):
    name: str
    tape: Tape
    telemetry: Telemetry


class ConsoleMessage(_Message):
    type: Literal["console"]
    lines: list[str]


class BuildMessage(_Message):
    type: Literal["build"]
    lines: list[str]


class ErrorMessage(_Message):
    type: Literal["error"]
    message: str
    issues: list[Issue]
    traceback: str | None


ServerMessage = Annotated[
    Union[  # noqa: UP007 - a named union, for the TypeScript generator
        SessionMessage,
        StatusMessage,
        SceneMessage,
        FrameMessage,
        OverlayMessage,
        ConsoleMessage,
        BuildMessage,
        ErrorMessage,
        RecordedMessage,
    ],
    Field(discriminator="type"),
]

# --- what a session's WebSocket takes -----------------------------------------------------------


class SimpleCommand(_Message):
    cmd: Literal["pause", "resume", "restart", "stop"]


class StepCommand(_Message):
    """Advance a paused run."""

    cmd: Literal["step"]
    ms: int = 10


class SpeedCommand(_Message):
    cmd: Literal["speed"]
    value: float  # times real time; 0 or less = as fast as possible


class InputCommand(_Message):
    """The virtual controller's sticks (-127 to 127) and pressed buttons."""

    cmd: Literal["input"]
    analog: dict[str, float]
    digital: list[str]


ClientCommand = Annotated[
    Union[SimpleCommand, StepCommand, SpeedCommand, InputCommand],  # noqa: UP007
    Field(discriminator="cmd"),
]

# --- TypeScript -------------------------------------------------------------------------------

MODELS: list[type[BaseModel]] = [
    RunSpec,
    Issue,
    AppInfo,
    WorkspaceItem,
    WorkspaceInfo,
    SessionInfo,
    JobInfo,
    StartSession,
    StartJob,
    RunProblem,
    PreviewRequest,
    Preview,
    RunConfiguration,
    RunConfigurations,
    SaveConfigurations,
    WheelMount,
    SensorMount,
    MechanismMount,
    RobotScene,
    CircleObstacle,
    PolygonObstacle,
    PieceStyle,
    FieldScene,
    SessionMessage,
    StatusMessage,
    Scene,
    SceneMessage,
    ControllerState,
    FrameState,
    FrameMessage,
    Overlay,
    OverlayMessage,
    PoseErrorSummary,
    RunRecord,
    RecordedMessage,
    TapeEvents,
    Tape,
    Telemetry,
    RunDetails,
    RunUpdate,
    ReplayRequest,
    Replay,
    ConsoleMessage,
    BuildMessage,
    ErrorMessage,
    SimpleCommand,
    StepCommand,
    SpeedCommand,
    InputCommand,
]
ALIASES: dict[str, Any] = {
    "ItemKind": ItemKind,
    "SessionState": SessionState,
    "JobState": JobState,
    "ServerMessage": ServerMessage,
    "ClientCommand": ClientCommand,
}


def _ts(annotation: Any, aliases: dict[int, str]) -> str:
    """A Python type as TypeScript."""
    if id(annotation) in aliases:
        return aliases[id(annotation)]
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is type(None) or annotation is None:
        return "null"
    if annotation is str:
        return "string"
    if annotation in (int, float):
        return "number"
    if annotation is bool:
        return "boolean"
    if annotation is Any:
        return "unknown"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation.__name__
    if origin is Annotated:
        return _ts(args[0], aliases)
    if origin is Literal:
        return " | ".join(f'"{a}"' if isinstance(a, str) else str(a).lower() for a in args)
    if origin in (Union, types.UnionType):
        parts: list[str] = []
        for arg in args:
            part = _ts(arg, aliases)
            if part not in parts:
                parts.append(part)
        return " | ".join(parts)
    if origin is list:
        inner = _ts(args[0], aliases)
        return f"({inner})[]" if "|" in inner else f"{inner}[]"
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            inner = _ts(args[0], aliases)
            return f"({inner})[]" if "|" in inner else f"{inner}[]"
        return "[" + ", ".join(_ts(a, aliases) for a in args) + "]"
    if origin is dict:
        return f"Record<string, {_ts(args[1], aliases)}>"
    raise TypeError(f"no TypeScript for {annotation!r}")


def typescript() -> str:
    """``frontend/src/protocol.ts``: the models above as TypeScript types."""
    aliases = {id(value): name for name, value in ALIASES.items()}
    lines = [
        "// Generated from vexsim/ui/protocol.py: python -m vexsim.ui.protocol "
        "frontend/src/protocol.ts",
        "// Don't edit by hand; a test fails when this file is stale.",
        "",
    ]
    for name, value in ALIASES.items():
        lines.append(f"export type {name} = {_ts(value, {})};")
    lines.append("")
    for model in MODELS:
        doc = (model.__doc__ or "").strip()
        if doc and model.__doc__ is not BaseModel.__doc__:
            lines.append("/** " + " ".join(doc.split()).replace("``", "`") + " */")
        lines.append(f"export interface {model.__name__} {{")
        hints = typing.get_type_hints(model, include_extras=True)
        for name, info in model.model_fields.items():
            optional = "?" if not info.is_required() else ""
            lines.append(f"  {name}{optional}: {_ts(hints[name], aliases)};")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    # python -m vexsim.ui.protocol frontend/src/protocol.ts (with no file: print it)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(typescript(), encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(typescript())

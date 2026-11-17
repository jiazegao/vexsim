"""Live runs: a session, what its WebSocket sends (``ServerMessage``) and what it takes
(``ClientCommand``)."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field

from vexsim.app.runs import RunRecord
from vexsim.app.runspec import RunSpec
from vexsim.ui.protocol.base import Issue, SessionState, Shape, _Message
from vexsim.ui.protocol.scene import FieldScene, RobotScene


class SessionInfo(_Message):
    id: str
    spec: RunSpec
    command: str  # the vexsim run command that runs the same thing
    state: SessionState
    message: str | None
    mode: str
    created: float
    run_id: str | None  # where its current (or last) run is recorded


class StartSession(_Message):
    spec: RunSpec
    replace: bool = True  # stop the other sessions first
    name: str | None = None  # what to call its recorded runs (a saved run's name)


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


class DrawingsMessage(_Message):
    """What the robot code has drawn (``vexsim::draw_*``, ``bot.draw``), by layer: sent
    when it changes."""

    type: Literal["drawings"]
    layers: dict[str, list[Shape]]


class FollowingMessage(_Message):
    """A run that follows a log (``RunSpec.follow``) began to: ``start`` is the moment of
    the run that goes with the log's first update."""

    type: Literal["following"]
    start: float


class RecordedMessage(_Message):
    """A run ended (finished, stopped, restarted, failed) and was recorded."""

    type: Literal["recorded"]
    run: RunRecord


class ChangedMessage(_Message):
    """Files this run was made from (its program or project, its robot, field, route) have
    changed since it started: ``files``, as the workspace names them. What's on the field is
    the code as it was; Restart runs it as it is now. Sent again when more change."""

    type: Literal["changed"]
    files: list[str]


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
        DrawingsMessage,
        FollowingMessage,
        ConsoleMessage,
        BuildMessage,
        ErrorMessage,
        RecordedMessage,
        ChangedMessage,
    ],
    Field(discriminator="type"),
]


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

"""Recorded runs to play back: tapes, telemetry, replays, and a real robot's logs as tapes."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from vexsim.app.runs import RunRecord
from vexsim.ui.protocol.base import DrawColor, Shape, _Message
from vexsim.ui.protocol.sessions import FrameState, Overlay, Scene


class TapeEvents(_Message):
    """When what changes seldom changed: [time, the new value]."""

    overlay: list[tuple[float, Overlay]]
    lcd: list[tuple[float, list[str]]]
    controller_screen: list[tuple[float, list[str]]]
    drawings: list[tuple[float, dict[str, list[Shape]]]] = Field(default_factory=list)


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


class MclLogSummary(_Message):
    """How a robot's MCL ran, by its log."""

    updates: int
    duration_s: float
    sensors: int
    particles: int  # logged with each update
    start: tuple[float, float, float]  # where MCL started: x, y, heading
    interval_ms: tuple[float, float, float] | None  # between updates: median, 95%, longest
    no_reading_pct: float | None  # of the distance sensors' readings
    spread_in: tuple[float, float]  # the particles' spread: median, 95%


class MclLogTape(_Message):
    """A robot's MCL log (``vexsim.mcllog``), to play on the field: where its code thought
    it was, update by update, and what it saw, drawn as the robot code's drawings are. There's
    no truth: only the real robot knew where it was."""

    kind: Literal["mcl"] = "mcl"
    name: str
    path: str
    summary: MclLogSummary
    times: list[float]  # each update's, from the first (s)
    estimate: list[tuple[float, float, float]]  # each update's: x, y, heading
    drawings: list[tuple[float, dict[str, list[Shape]]]]  # each update's: rays, particles, spread


class RobotLogSummary(_Message):
    """What a robot log (vexsim's logger) holds, as it plays on the field."""

    rows: int
    duration_s: float  # from its first pose to its last
    interval_ms: float | None  # between rows: the median
    pose: str  # the pose it plays: the code's first logged (lemlib), or "odometry" (from a spot)
    poses: list[str]  # every pose the code logged
    start: tuple[float, float, float]  # where it starts: x, y, heading
    distance_sensors: int  # drawn as rays, from where the robot config mounts them
    no_reading_pct: float | None  # of their readings
    robot: str | None  # the robot it names (calibration logs do)
    field: str | None  # and the field
    test: str | None  # a calibration program's test
    routine: str | None  # a routine's name, as the code named the log (Left 40)


class LogPath(_Message):
    """Another pose a robot log's code logged (MCL's, beside LemLib's), as a path: its point at
    each frame from ``first`` on (a frame it didn't log keeps the point before)."""

    name: str
    color: DrawColor
    first: int  # the frame its path starts at
    xs: list[float]
    ys: list[float]


class RobotLogTape(_Message):
    """A robot log (``vexsim.app.logtape``), to play on the field as an MCL log plays: where
    its code thought it was (a pose it logged; a calibration log's, by odometry from its spot),
    its other poses and each distance sensor's reading as a ray, row by row. There's no truth:
    only the real robot knew where it was."""

    kind: Literal["robot"] = "robot"
    name: str
    path: str
    summary: RobotLogSummary
    times: list[float]  # each frame's, from the first (s)
    estimate: list[tuple[float, float, float]]  # each frame's: x, y, heading
    drawings: list[tuple[float, dict[str, list[Shape]]]]  # each frame's: rays, poses
    paths: list[LogPath]  # the other poses' paths


class NothingToPlay(_Message):
    """A robot log that reads but has no path to play on the field: no pose of its code's, and
    no spot it started on (the quick fit's routine logs none). Why, in words."""

    kind: Literal["none"] = "none"
    path: str
    why: str

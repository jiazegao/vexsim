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
from vexsim.app.runspec import Follow, RunSpec
from vexsim.app.sweeps import Sweep
from vexsim.config.field import FIELD_MODELS, FieldConfig
from vexsim.config.robot import ROBOT_MODELS, RobotConfig

ItemKind = Literal[
    "robot",
    "field",
    "scenario",
    "program",
    "project",
    "input",
    "log",
    "robotlog",
    "mcllog",
    "invalid",
]
SessionState = Literal["building", "starting", "running", "paused", "finished", "error", "stopped"]
JobState = Literal["queued", "running", "succeeded", "failed", "cancelled"]
ConfigKind = Literal["robot", "field"]
ResultKind = Literal["bench", "sweeps", "calibrations"]
Workers = Annotated[int, Field(ge=1, le=64)]
# What robot code draws on the field (vexsim.runtime.drawing), by layer: colors from the
# field's palette, then shapes in inches and degrees, as lists that start with their kind
DrawColor = Literal[
    "violet", "blue", "orange", "aqua", "yellow", "magenta", "green", "red", "ink", "muted"
]
Shape = Union[  # noqa: UP007 - a named union, for the TypeScript generator
    tuple[Literal["point"], float, float, DrawColor, float],  # x, y, color, size (pixels)
    tuple[Literal["line"], float, float, float, float, DrawColor],  # x1, y1, x2, y2
    tuple[Literal["circle"], float, float, float, DrawColor],  # x, y, radius
    tuple[Literal["ellipse"], float, float, float, float, float, DrawColor],  # x, y, rx, ry, turn
    tuple[Literal["pose"], float, float, float, DrawColor],  # x, y, heading
    tuple[Literal["text"], float, float, str, DrawColor],  # x, y, text
]


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
    pages: int  # the app's pages open on this server now


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
    """A long task (``GET /api/jobs/{id}?since=n&items_since=k``): its log from line n on,
    its items (parts of its result that came early) from k on, and once it's done, its
    result. Listed jobs (``GET /api/jobs``) carry neither, nor their result."""

    id: str
    kind: str
    title: str
    params: dict[str, Any]
    state: JobState
    log: list[str]
    log_size: int
    progress: tuple[int, int] | None  # done, total
    items: list[dict[str, Any]]
    items_size: int
    result: dict[str, Any] | None
    error: str | None
    created: float
    started: float | None
    finished: float | None


class StartSession(_Message):
    spec: RunSpec
    replace: bool = True  # stop the other sessions first
    name: str | None = None  # what to call its recorded runs (a saved run's name)


class BuildJob(_Message):
    """``vexsim build``."""

    kind: Literal["build"]
    project: str  # workspace path of a PROS project
    debug: bool = False  # -O0 -g, for a debugger


class DoctorJob(_Message):
    """``vexsim doctor``: is there a compiler that builds and runs PROS projects?"""

    kind: Literal["doctor"]


class MotorCurvesJob(_Message):
    """``vexsim motor-curves``; its result is a ``MotorCurves``."""

    kind: Literal["motor_curves"]
    cartridge: Literal["red", "green", "blue"] = "green"
    supply_voltage: Annotated[float, Field(ge=6, le=14)] = 12.8
    points: Annotated[int, Field(ge=5, le=401)] = 61


class DriftJob(_Message):
    """``vexsim drift``; its result is a ``Drift``."""

    kind: Literal["drift"]
    robot: str
    left: Annotated[float, Field(ge=-1, le=1)] = 1.0  # fractions of rated speed
    right: Annotated[float, Field(ge=-1, le=1)] = 0.4
    seconds: Annotated[float, Field(gt=0, le=10)] = 1.5
    lateral_mu: Annotated[
        list[Annotated[float, Field(gt=0, le=2)]], Field(min_length=1, max_length=3)
    ] = [0.4, 0.2, 0.1]


class OdometryJob(_Message):
    """``vexsim odometry``; its result is an ``Odometry``."""

    kind: Literal["odometry"]
    robot: str
    script: Literal["gentle", "aggressive"] = "aggressive"
    noise: Literal["ideal", "default", "harsh"] | None = None  # None: as configured
    seed: Annotated[int, Field(ge=0)] = 0


class BenchJob(_Message):
    """``vexsim bench``; its result is the id of a ``BenchResult``."""

    kind: Literal["bench"]
    scenario: str
    seeds: Annotated[int, Field(ge=1, le=1000)] = 20
    first_seed: Annotated[int, Field(ge=0)] = 0
    workers: Workers | None = None  # None: all but one core
    localizers: list[str] | None = None  # None: all of the scenario's
    controllers: list[str] | None = None
    worst_cases: bool = True  # re-run each combination's worst trial with full telemetry


class CalibrateJob(_Message):
    """``vexsim calibrate``; its result is the id of a ``CalibrationResult``."""

    kind: Literal["calibrate"]
    robot: str
    log: str  # a robot log in the workspace
    fit: list[str] | None = None  # parameters to fit; None: the wheel parameters
    compare_only: bool = False  # replay the log as the config has it, fit nothing
    max_iterations: Annotated[int, Field(ge=1, le=100)] = 12
    workers: Workers | None = None


class SweepJob(_Message):
    """A sweep (saved or not); its result is the id of a ``SweepResult``."""

    kind: Literal["sweep"]
    sweep: Sweep
    workers: Workers | None = None


StartJob = Annotated[
    Union[  # noqa: UP007 - a named union, for the TypeScript generator
        BuildJob, DoctorJob, MotorCurvesJob, DriftJob, OdometryJob, BenchJob, CalibrateJob, SweepJob
    ],
    Field(discriminator="kind"),
]


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


# --- recorded runs -----------------------------------------------------------------------------


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

    name: str
    path: str
    summary: MclLogSummary
    times: list[float]  # each update's, from the first (s)
    estimate: list[tuple[float, float, float]]  # each update's: x, y, heading
    drawings: list[tuple[float, dict[str, list[Shape]]]]  # each update's: rays, particles, spread


class RoutineInfo(_Message):
    """A PROS project's routine (``vexsim.bridge.routines``): a function its
    include/custom/auton.hpp declares that takes no arguments."""

    name: str  # as C++ calls it: left40, or auton::left40
    line: int  # its declaration's, in the header
    source: str | None  # the file that defines it; None: vexsim can't tell, so it can't be picked
    start: tuple[float, float, float] | None  # where its setPose puts the robot: x, y, heading


class NotRoutineInfo(_Message):
    name: str
    line: int
    why: str  # it takes arguments, returns a value, ...


class ProjectRoutines(_Message):
    """A PROS project's routines, to pick one for a run."""

    header: str  # where they're declared, in the project
    found: bool  # whether the project has that header
    routines: list[RoutineInfo]
    others: list[NotRoutineInfo]  # functions the header declares that can't be routines


# --- config editors ---------------------------------------------------------------------------


class TextSpan(_Message):
    """Where something is written in a config: 1-based lines and columns, the end just past
    its last character."""

    line: int
    column: int
    end_line: int
    end_column: int


class PlacedIssue(_Message):
    severity: Literal["error", "warning"]
    location: str  # dotted path, as in Issue
    message: str
    span: TextSpan | None  # None: about the whole document


class ConfigCheck(_Message):
    """A config's text, checked as `vexsim validate-config` would: its issues where they're
    written, and when it parses, the config itself (`robot` or `field`), its summary, and
    where each part the editor's diagram draws is written (`sensors[1]`, `elements[3]`)."""

    issues: list[PlacedIssue]
    robot: RobotConfig | None = None
    field: FieldConfig | None = None
    summary: list[str] = []
    places: dict[str, TextSpan] = {}


class ConfigFile(_Message):
    """A robot or field config, opened for editing. `version` is of the bytes on disk."""

    path: str
    kind: ConfigKind
    text: str
    version: str
    check: ConfigCheck


class ConfigCheckRequest(_Message):
    kind: ConfigKind
    text: str


class ConfigEdit(_Message):
    """Write `value` where `location` is: one number, or a list of them (`pos_in`)."""

    location: str
    value: float | list[float]


class ConfigPatchRequest(_Message):
    kind: ConfigKind
    text: str
    edits: list[ConfigEdit]


class ConfigPatched(_Message):
    """The text with the edits made in place (nothing else in it changed), checked."""

    text: str
    check: ConfigCheck


class ConfigSave(_Message):
    """Write a config. `version`: the one it was opened at; the save is refused (409) if
    the file has changed since. None overwrites whatever is there."""

    path: str
    text: str
    version: str | None = None


class ConfigSaved(_Message):
    version: str


# --- results of the long jobs (analysis, benchmarks, sweeps, calibration) -----------------


class MotorCurve(_Message):
    command: str  # "velocity" or "voltage"
    label: str
    speed_rpm: list[float]
    torque_nm: list[float]
    current_a: list[float]
    power_w: list[float]


class MotorCurves(_Message):
    """A motor on the simulated dynamometer, under each command."""

    cartridge: str
    supply_voltage: float
    current_limit_a: float
    curves: list[MotorCurve]


class DriftRun(_Message):
    lateral_mu: float
    true: list[tuple[float, float]]
    odometry: list[tuple[float, float]]
    final_error_in: float


class Drift(_Message):
    """An arc at fixed side speeds, for each roller friction: the true path against what
    drive-encoder odometry believes."""

    left: float
    right: float
    seconds: float
    runs: list[DriftRun]


class OdometryEstimate(_Message):
    name: str
    path: list[tuple[float, float, float]]
    position_error_in: list[float]
    heading_error_deg: list[float]
    final_in: float
    final_deg: float
    worst_in: float


class Odometry(_Message):
    """A scripted drive, and each baseline localizer's estimate against the truth."""

    script: str
    noise: str | None
    seed: int
    time_s: list[float]
    truth: list[tuple[float, float, float]]
    estimates: list[OdometryEstimate]


class ResultAbout(_Message):
    """A saved result of a benchmark, a sweep or a calibration (``GET /api/results/{kind}``)."""

    id: str
    kind: ResultKind
    title: str
    created: float
    summary: str


class ScenarioController(_Message):
    name: str
    kind: str
    project: str | None


class ScenarioInfo(_Message):
    """A benchmark scenario, described (``GET /api/bench/scenario?path=``)."""

    name: str
    description: str
    path: str
    robot: str  # workspace paths
    field: str | None
    task: str
    tolerance_in: float | None
    time_limit_s: float
    noise: str | None
    disturbances: list[str]
    randomized: list[str]  # what each seed changes
    localizers: list[str]
    controllers: list[ScenarioController]


class Metric(_Message):
    key: str
    label: str


class Combination(_Message):
    localizer: str
    controller: str


class Stats(_Message):
    mean: float
    median: float
    p95: float
    max: float


class BenchSummary(_Message):
    localizer: str
    controller: str
    trials: int
    success_rate: float | None
    timeouts: int
    stats: dict[str, Stats | None]  # by metric key; None when no trial has a value


class WorstCase(_Message):
    localizer: str
    controller: str
    seed: int
    file: str  # its telemetry log, in the result's folder


class BenchResult(_Message):
    """A benchmark's result (``GET /api/results/bench/{id}``). ``rows`` are the trials, as
    trials.csv has them."""

    about: ResultAbout
    scenario: ScenarioInfo
    first_seed: int
    seeds: int
    workers: int
    wall_time_s: float
    metrics: list[Metric]
    combos: list[Combination]
    summary: list[BenchSummary]
    rows: list[dict[str, Any]]
    worst: list[WorstCase]
    report: str | None  # report.html, when matplotlib is there to draw its charts
    files: list[str]
    command: str  # the vexsim bench command that runs the same benchmark


class ResultReplayRequest(_Message):
    file: str  # a telemetry log in the result's folder (a benchmark's worst case)


class SweepsFile(_Message):
    """The workspace's sweeps (``.vexsim/sweeps.yaml``); ``error`` if that file can't be
    read."""

    file: str
    sweeps: list[Sweep]
    error: str | None = None


class SaveSweeps(_Message):
    sweeps: list[Sweep]


class SweepVariation(_Message):
    label: str
    env: dict[str, str]


class SweepTrial(_Message):
    """One run of a sweep: what ran (``spec``, to run it again exactly), whether its program
    finished, and how far the robot code's pose was from the truth (None without one)."""

    index: int
    run: str  # the saved run's name
    variation: str  # its label
    env: dict[str, str]
    seed: int
    start: tuple[float, float, float]  # where the robot was put down
    spec: RunSpec
    finished: bool
    error: str | None
    seconds: float | None  # how long the program ran
    end: tuple[float, float, float] | None  # the true pose at the end
    end_estimate: tuple[float, float, float] | None
    mean_in: float | None
    max_in: float | None
    final_in: float | None
    max_deg: float | None
    trace: list[float | None]  # the position error every trace_step_s
    wall_s: float


class SweepResult(_Message):
    """A sweep's result (``GET /api/results/sweeps/{id}``); live, its trials arrive one by
    one as the job's items."""

    about: ResultAbout
    sweep: Sweep
    variations: list[SweepVariation]
    trace_step_s: float
    workers: int
    wall_time_s: float
    trials: list[SweepTrial]
    files: list[str]


class FitParameter(_Message):
    name: str
    value: float  # the robot's now: its override, or the default
    overridden: bool


class CalibrationSetup(_Message):
    """What a fit adjusts unless told otherwise (``GET /api/calibrate/parameters?robot=``)."""

    robot: str
    parameters: list[FitParameter]


class RoutineRequest(_Message):
    robot: str
    project: str  # a PROS project in the workspace
    write: bool = False  # False: only say what it would do


class RoutineFile(_Message):
    path: str
    state: Literal["new", "same", "different"]  # as written for this robot, or otherwise


class RoutineStep(_Message):
    name: str
    start_s: float
    seconds: float


class RoutinePlan(_Message):
    """The calibration routine in a PROS project (``POST /api/calibrate/routine``)."""

    project: str
    files: list[RoutineFile]
    seconds: float
    steps: list[RoutineStep]


class LogFacts(_Message):
    rows: int
    seconds: float
    found: str  # e.g. "4 motors, 2 rotation sensors, 1 IMU"
    skipped_lines: int
    ignored_motors: list[int]  # logged motors that aren't in the drivetrain


class FittedParameter(_Message):
    name: str
    before: float
    after: float
    uncertainty: float  # one standard deviation, as a fraction of the value


class DirectParameter(_Message):
    name: str
    before: float | None
    after: float  # read off the log (the battery's resistance)


class RmsGroup(_Message):
    group: str
    unit: str
    before: float | None
    after: float


class PanelSeries(_Message):
    name: str  # "robot log", "simulated, before the fit" or "simulated"
    values: list[float | None]


class CalibrationPanel(_Message):
    title: str
    unit: str
    time_s: list[float]
    series: list[PanelSeries]


class CalibrationResult(_Message):
    """A calibration's result (``GET /api/results/calibrations/{id}``)."""

    about: ResultAbout
    robot: str
    log: str
    log_facts: LogFacts
    compare_only: bool
    parameters: list[FittedParameter]
    direct: list[DirectParameter]
    rms: list[RmsGroup]
    overrides: dict[str, float]  # every fitted value, for the robot config
    replays: int
    panels: list[CalibrationPanel]
    files: list[str]


class ConfigOverridesRequest(_Message):
    """Set ``overrides`` in a robot config's text (``POST /api/config/overrides``)."""

    text: str
    values: dict[str, float]


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
    Follow,
    RunSpec,
    Issue,
    AppInfo,
    WorkspaceItem,
    WorkspaceInfo,
    SessionInfo,
    JobInfo,
    StartSession,
    BuildJob,
    DoctorJob,
    MotorCurvesJob,
    DriftJob,
    OdometryJob,
    BenchJob,
    CalibrateJob,
    Sweep,
    SweepJob,
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
    DrawingsMessage,
    FollowingMessage,
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
    MclLogSummary,
    MclLogTape,
    RoutineInfo,
    NotRoutineInfo,
    ProjectRoutines,
    *ROBOT_MODELS,
    *FIELD_MODELS,
    TextSpan,
    PlacedIssue,
    ConfigCheck,
    ConfigFile,
    ConfigCheckRequest,
    ConfigEdit,
    ConfigPatchRequest,
    ConfigPatched,
    ConfigSave,
    ConfigSaved,
    MotorCurve,
    MotorCurves,
    DriftRun,
    Drift,
    OdometryEstimate,
    Odometry,
    ResultAbout,
    ScenarioController,
    ScenarioInfo,
    Metric,
    Combination,
    Stats,
    BenchSummary,
    WorstCase,
    BenchResult,
    ResultReplayRequest,
    SweepsFile,
    SaveSweeps,
    SweepVariation,
    SweepTrial,
    SweepResult,
    FitParameter,
    CalibrationSetup,
    RoutineRequest,
    RoutineFile,
    RoutineStep,
    RoutinePlan,
    LogFacts,
    FittedParameter,
    DirectParameter,
    RmsGroup,
    PanelSeries,
    CalibrationPanel,
    CalibrationResult,
    ConfigOverridesRequest,
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
    "ConfigKind": ConfigKind,
    "ResultKind": ResultKind,
    "DrawColor": DrawColor,
    "Shape": Shape,
    "StartJob": StartJob,
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
    declared: dict[int, str] = {}  # an alias can use the ones before it
    for name, value in ALIASES.items():
        lines.append(f"export type {name} = {_ts(value, declared)};")
        declared[id(value)] = name
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

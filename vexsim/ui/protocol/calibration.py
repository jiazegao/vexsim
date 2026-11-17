"""Calibrating to a real robot: the quick fit and its routine, a session (its program, runs,
fit and report), and the autonomous check."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from vexsim.ui.protocol.base import _Message
from vexsim.ui.protocol.configs import ConfigCheck
from vexsim.ui.protocol.results import ResultAbout


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


class FittedDrive(_Message):
    """The model of the drive fitted to a robot's log (``vexsim.calibration.feedforward``):
    what a route's arcs and RAMSETE paths drive with on that robot, as its drive: section."""

    kS: float  # V
    kV: float  # V per in/s
    kA: float  # V per in/s^2
    kT: float  # V, against the scrub in a turn
    kP: float  # V per in/s the wheels are behind
    max_velocity: float  # in/s: the limits that follow
    max_accel: float  # in/s^2
    max_lateral_accel: float  # in/s^2
    top_speed: float  # in/s
    samples: int
    r2: float
    turned: bool  # whether the log turned the robot: kT is 0 if it didn't
    section: str  # the route's drive: line


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
    drive: FittedDrive | None = None  # for vexsim's own motions, if it's a two-sided drive


class ProgramTest(_Message):
    """One of the session's tests, as the program's menu numbers it."""

    number: int
    key: str
    title: str
    kind: Literal["on_hand", "drive", "push", "spin"]  # on_hand: on its side, or by hand
    runs: int  # runs it takes
    place: list[str]  # how to put the robot on its spot, from two walls
    clearance_in: float | None  # the least room around it
    map: str | None  # its map, in the workspace
    scale: float | None  # a driving test slowed for room


class MissingTest(_Message):
    """A test with no room on the field, left out."""

    key: str
    title: str
    blocked_by: list[str]


class ProgramPlan(_Message):
    robot: str
    field: str
    margin_in: float
    tests: list[ProgramTest]
    missing: list[MissingTest]


class CalibrationProgram(_Message):
    """A calibration program's folder (``GET /api/calibration/program``): whether the program
    and a PROS project are there, and the plan it was written with."""

    folder: str
    exists: bool
    pros_project: bool  # pros c n made it a project: it builds and uploads to the robot
    written: bool  # its src/main.cpp is the calibration program
    plan: ProgramPlan | None


class SessionRun(_Message):
    """One of a session's runs: its log, what collecting made of it, and what it measured."""

    file: str
    test: str
    run: int
    name: str
    started_ms: int
    ended: str
    quality: str  # "good", or what's wrong with it
    use: bool  # whether the fit uses it
    warnings: list[str]
    result: str  # what it measured, in a line (as the brain's screen said it)


class SessionValue(_Message):
    """A value a step of the fit found."""

    key: str
    before: float | None
    after: float | None
    uncertainty: float | None  # one standard deviation; None: the logs can't tell
    tolerance: float | None
    pinned: bool  # known within its tolerance
    note: str
    why_not: str  # why it isn't written ("": it is)


class SessionRms(_Message):
    group: str
    unit: str
    before: float | None
    after: float | None


class SessionStep(_Message):
    name: str
    runs: list[str]
    skipped: str  # why it didn't run ("": it did)
    values: list[SessionValue]
    rms: list[SessionRms]
    notes: list[str]
    warnings: list[str]


class HeldOutGroup(_Message):
    group: str
    unit: str
    rms: float | None  # simulated against logged
    noise: float | None  # what the sensors' noise alone leaves


class HeldOutRun(_Message):
    """The driving run the fit left out, replayed with what it found."""

    run: str
    matches: bool  # within the sensors' noise
    groups: list[HeldOutGroup]


class SessionChange(_Message):
    """One change the fit writes into the robot's config."""

    location: str  # overrides["motor.voltage_cap"], drivetrain.wheels[0].diameter_in, ...
    value: float | list[float]
    key: str  # the value's name in the report


class SessionPlot(_Message):
    title: str
    file: str  # in the session's report/


class SessionReport(_Message):
    """A session's fit (its report/report.json)."""

    robot: str
    robot_file: str  # the robot config it was fitted to
    config_digest: str  # that config's text, as it was: Apply refuses a changed one
    fitted: str  # the date
    session: str
    steps: list[SessionStep]
    held_out: HeldOutRun | None
    drive: str | None  # the drive model, in words
    drive_section: str | None  # the line a route's drive: section takes
    changes: list[SessionChange]  # what Apply writes
    warnings: list[str]
    plots: list[SessionPlot]


class CalibrationSessionState(_Message):
    """A calibration session (``GET /api/calibration/session``): its runs and its latest fit."""

    path: str
    name: str
    exists: bool  # it has a session.yaml
    robot: str | None  # the robot's name, as its logs give it
    field: str | None
    practice: bool  # its runs are the simulated student's
    runs: list[SessionRun]
    report: SessionReport | None


class SessionCollectRequest(_Message):
    session: str
    folder: str | None = None  # a folder of logs (anywhere on this computer); None: the card


class SessionCollected(_Message):
    card: str  # where the logs came from
    added: int  # new runs
    messages: list[str]  # what collecting said of each log
    state: CalibrationSessionState


class SessionUseRequest(_Message):
    session: str
    file: str
    use: bool


class SessionApplyRequest(_Message):
    session: str
    text: str  # the robot config's text, as its editor has it


class SessionApplied(_Message):
    text: str  # with the session's changes written in, its comments kept
    check: ConfigCheck
    changes: int


class PassMarks(_Message):
    """The autonomous check's pass marks: the team's (.vexsim/calibration.yaml), or vexsim's."""

    max_distance_in: float
    max_heading_deg: float
    source: str
    file: str | None
    warnings: list[str]


class SavePassMarks(_Message):
    max_distance_in: Annotated[float, Field(gt=0)]
    max_heading_deg: Annotated[float, Field(gt=0)]


class EndRequest(_Message):
    """Where two corners' tape marks put the robot (``parse_end``'s words)."""

    robot: str
    field: str
    text: str


class EndFound(_Message):
    x: float
    y: float
    heading: float
    misfit_in: float  # the marks' spacing against the corners'
    corners: list[str]
    warning: str | None


class CheckMarks(_Message):
    max_distance_in: float
    max_heading_deg: float
    source: str


class CheckRun(_Message):
    """A real run, against the simulated ones."""

    log: str
    end: str | None  # its tape marks
    measured: tuple[float, float, float] | None  # where it ended: x, y, heading
    end_off: tuple[float, float] | None  # from the simulated runs' end: in, degrees
    run_rms_in: float | None  # its code's pose against theirs, through the run
    parted_s: float | None  # when it first parted from them by more than the mark


class CheckSim(_Message):
    seed: int
    end: tuple[float, float, float]


class AutonCheckResult(_Message):
    """An autonomous check (``GET /api/results/checks/{id}``)."""

    about: ResultAbout
    routine: str
    robot: str | None
    field: str | None
    program: str | None
    start: tuple[float, float, float] | None
    marks: CheckMarks
    passed: bool
    failures: list[str]
    warnings: list[str]
    runs: list[CheckRun]
    sims: list[CheckSim]
    sim_end: tuple[float, float, float] | None
    end_off: tuple[float, float] | None
    run_rms_in: float | None
    sim_spread: tuple[float, float] | None
    real_spread: tuple[float, float] | None
    plots: list[str]  # in the result's folder

"""Long jobs: one's state, and what starts each kind (``StartJob``)."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import Field

from vexsim.app.sweeps import Sweep
from vexsim.ui.protocol.base import JobState, Workers, _Message


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
    cartridge: Literal["red", "green", "blue", "5.5w"] = "green"  # "5.5w": the 5.5W motor
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


class RouteJob(_Message):
    """A route run headless (``vexsim route run``); its result is a ``RouteRun``."""

    kind: Literal["route"]
    route: str  # its file, in the workspace
    seed: Annotated[int, Field(ge=0)] = 0
    noise: Literal["ideal", "default", "harsh"] | None = None
    text: str | None = None  # the route as the editor has it, when that isn't saved


class CalibrationProgramJob(_Message):
    """Plan a calibration session on the field and write its program into a PROS project
    (``vexsim calibration program``); its result is the project's folder."""

    kind: Literal["calibration_program"]
    robot: str
    field: str
    folder: str  # the program's project, in the workspace (made if it isn't there)
    margin: Annotated[float, Field(gt=0, le=24)] = 6.0  # room to keep around each test (in)
    force: bool = False  # write over a src/main.cpp that isn't the program's
    workers: Workers | None = None


class CalibrationPracticeJob(_Message):
    """A practice session: the simulated student runs the program in vexsim, its logs
    collected into ``session`` (marked as practice)."""

    kind: Literal["calibration_practice"]
    robot: str
    field: str
    program: str  # the program's project, written
    session: str  # the session's folder (made if it isn't there)
    tests: list[str] | None = None  # the menu's tests to run; None: every one
    unlike: bool = True  # the simulated robot as a real one is, not quite as its config says


class CalibrationUsbJob(_Message):
    """Collect over USB (no card in the brain) until stopped (``DELETE /api/jobs/{id}``):
    each log the program prints, added to the session as it ends."""

    kind: Literal["calibration_usb"]
    session: str  # it listens through `pros terminal` (no other command: a request names none)


class CalibrationFitJob(_Message):
    """Fit a calibration session (``vexsim calibrate ROBOT SESSION``): its report, and
    report/report.json for the page (``SessionReport``)."""

    kind: Literal["calibration_fit"]
    robot: str
    session: str
    field: str | None = None  # the field the session ran on (for the distance sweeps)
    workers: Workers | None = None


class CalibrationCheckJob(_Message):
    """The autonomous check (``vexsim calibration check-auton``); its result is the id of an
    ``AutonCheckResult``."""

    kind: Literal["calibration_check"]
    robot: str
    field: str
    program: str  # the PROS project the robot ran
    logs: Annotated[list[str], Field(min_length=1)]  # the real runs' robot logs
    ends: list[str]  # where each ended: two corners' tape marks, one for each log
    routine: str | None = None  # None: the routine the logs are named for
    seeds: Annotated[int, Field(ge=1, le=10)] = 3
    max_distance_in: Annotated[float, Field(gt=0)] | None = None  # None: the team's marks
    max_heading_deg: Annotated[float, Field(gt=0)] | None = None
    workers: Workers | None = None


StartJob = Annotated[
    Union[  # noqa: UP007 - a named union, for the TypeScript generator
        BuildJob, DoctorJob, MotorCurvesJob, DriftJob, OdometryJob, BenchJob, CalibrateJob,
        SweepJob, RouteJob, CalibrationProgramJob, CalibrationPracticeJob, CalibrationUsbJob,
        CalibrationFitJob, CalibrationCheckJob,
    ],
    Field(discriminator="kind"),
]  # fmt: skip

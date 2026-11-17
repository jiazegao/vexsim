"""What the long jobs find: motor curves, drift, odometry, benchmarks, sweeps."""

from __future__ import annotations

from typing import Any

from vexsim.app.runspec import RunSpec
from vexsim.app.sweeps import Sweep
from vexsim.ui.protocol.base import ResultKind, _Message


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

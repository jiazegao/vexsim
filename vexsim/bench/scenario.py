"""Benchmark scenario files: what to drive, what goes wrong, what varies, what to compare.

Poses are inches and degrees counter-clockwise (field frame). Paths in the
file (robot, field, algorithm files) are relative to the scenario file.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, PositiveFloat, StrictInt

from vexsim.config.issues import ValidationReport
from vexsim.config.loader import _validate
from vexsim.config.robot import NoisePreset, OverrideKey

Point = tuple[FiniteFloat, FiniteFloat]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Fraction = Annotated[float, Field(ge=0, le=1)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StartPose(_Model):
    x: FiniteFloat = 0.0
    y: FiniteFloat = 0.0
    heading: FiniteFloat = 0.0


# --- tasks ------------------------------------------------------------------------------------


class MoveToPointTask(_Model):
    type: Literal["move_to_point"]
    x: FiniteFloat
    y: FiniteFloat
    forwards: bool = True
    tolerance_in: PositiveFloat = 1.5


class MoveToPoseTask(_Model):
    type: Literal["move_to_pose"]
    x: FiniteFloat
    y: FiniteFloat
    heading: FiniteFloat
    tolerance_in: PositiveFloat = 2.0
    heading_tolerance_deg: PositiveFloat = 3.0


class TurnTask(_Model):
    type: Literal["turn_to_heading"]
    heading: FiniteFloat
    heading_tolerance_deg: PositiveFloat = 2.0


class DriveTask(_Model):
    type: Literal["drive"]
    distance_in: FiniteFloat
    tolerance_in: PositiveFloat = 1.0


class FollowTask(_Model):
    type: Literal["follow"]
    waypoints: Annotated[tuple[Point, ...], Field(min_length=2)]
    tolerance_in: PositiveFloat = 2.0


Task = Annotated[
    MoveToPointTask | MoveToPoseTask | TurnTask | DriveTask | FollowTask,
    Field(discriminator="type"),
]

# Built-in controllers per task type; the first is the default.
CONTROLLER_KINDS = {
    "move_to_point": ("move_to_point",),
    "move_to_pose": ("boomerang",),
    "turn_to_heading": ("turn_pid",),
    "drive": ("profiled_trapezoid", "profiled_scurve"),
    "follow": ("pure_pursuit", "ramsete"),
}


# --- disturbances -------------------------------------------------------------------------------


class PushDisturbance(_Model):
    """An external force on the robot (field frame, newtons), like another robot shoving it."""

    type: Literal["push"]
    at_s: NonNegative
    duration_s: PositiveFloat
    force_n: Point


class ImuBiasStep(_Model):
    """The IMU's gyro bias jumps (e.g. after an impact); calibration doesn't see it."""

    type: Literal["imu_bias_step"]
    at_s: NonNegative
    deg_per_s: FiniteFloat
    port: StrictInt | None = None  # default: every IMU


class TrackingWheelLiftoff(_Model):
    """A tracking wheel loses contact (e.g. over a field element) and stops counting."""

    type: Literal["tracking_wheel_liftoff"]
    at_s: NonNegative
    duration_s: PositiveFloat
    port: StrictInt


Disturbance = Annotated[
    PushDisturbance | ImuBiasStep | TrackingWheelLiftoff, Field(discriminator="type")
]


# --- randomization and algorithms -----------------------------------------------------------------


class Randomize(_Model):
    """Per-seed variation. Standard deviations for the start, uniform ranges otherwise."""

    start_xy_in: NonNegative = 0.0  # true start differs from where odometry believes it is
    start_heading_deg: NonNegative = 0.0
    battery_soc: tuple[Fraction, Fraction] | None = None
    params: dict[OverrideKey, tuple[FiniteFloat, FiniteFloat]] = Field(default_factory=dict)


class ControllerSpec(_Model):
    """A controller to compare: a built-in kind with options, or ``file.py:factory``.

    A factory is called as ``factory(task, geometry, **options)`` and returns a
    controller with ``step(pose, frame, dt)`` and ``done()``.
    """

    name: str
    kind: str | None = None  # default: the task's first built-in kind
    options: dict[str, Any] = Field(default_factory=dict)


class Scenario(_Model):
    version: Literal[1] = 1
    name: str
    description: str = ""
    robot: str
    field: str | None = None
    start: StartPose = StartPose()
    noise: NoisePreset | None = None
    battery_soc: Fraction = 1.0
    time_limit_s: PositiveFloat = 15.0
    settle_window_s: NonNegative = 0.5  # keep watching after the controller finishes
    task: Task
    disturbances: tuple[Disturbance, ...] = ()
    randomize: Randomize = Randomize()
    # Baseline names ("tracking wheels + IMU", ...), "all", or "file.py:factory" (factory(config)).
    localizers: tuple[str, ...] = ("all",)
    controllers: tuple[ControllerSpec, ...] = ()


class LoadedScenario:
    """A validated scenario plus the directory its relative paths resolve against."""

    def __init__(self, scenario: Scenario, base_dir: Path):
        self.scenario = scenario
        self.base_dir = base_dir

    def path(self, relative: str) -> Path:
        return (self.base_dir / relative).resolve()

    @property
    def controllers(self) -> tuple[ControllerSpec, ...]:
        if self.scenario.controllers:
            return self.scenario.controllers
        kind = CONTROLLER_KINDS[self.scenario.task.type][0]
        return (ControllerSpec(name=kind, kind=kind),)


def validate_scenario(
    source: str | os.PathLike[str] | Mapping[str, Any],
) -> ValidationReport[Scenario]:
    report = _validate(source, Scenario, _check_scenario)
    return report


def load_scenario(path: str | os.PathLike[str]) -> LoadedScenario:
    scenario = validate_scenario(path).raise_for_errors()
    return LoadedScenario(scenario, Path(path).resolve().parent)


def _check_scenario(s: Scenario) -> list:
    from vexsim.config.issues import ConfigIssue

    issues = []
    kinds = CONTROLLER_KINDS[s.task.type]
    names = set()
    for i, c in enumerate(s.controllers):
        if c.name in names:
            issues.append(
                ConfigIssue("error", f"controllers[{i}].name", f"duplicate name {c.name!r}")
            )
        names.add(c.name)
        kind = c.kind or kinds[0]
        if ":" not in kind and kind not in kinds:
            issues.append(
                ConfigIssue(
                    "error",
                    f"controllers[{i}].kind",
                    f"{kind!r} can't do a {s.task.type} task (built-ins: {', '.join(kinds)}; "
                    "or give file.py:factory)",
                )
            )
    if s.randomize.battery_soc and s.randomize.battery_soc[0] > s.randomize.battery_soc[1]:
        issues.append(ConfigIssue("error", "randomize.battery_soc", "range must be [low, high]"))
    for key, (lo, hi) in s.randomize.params.items():
        if lo > hi:
            issues.append(
                ConfigIssue("error", f"randomize.params.{key}", "range must be [low, high]")
            )
    return issues

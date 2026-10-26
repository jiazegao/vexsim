"""Scoring one trial from its recorded true and estimated poses."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from vexsim.algorithms.control.paths import spline
from vexsim.bench.scenario import (
    DriveTask,
    FollowTask,
    MoveToPointTask,
    MoveToPoseTask,
    TurnTask,
)

NAN = float("nan")


@dataclass
class TrialMetrics:
    success: bool
    timed_out: bool
    final_error_in: float  # true end position vs. the target
    final_heading_error_deg: float  # NaN when the task has no heading target
    completion_time_s: float  # controller reported done (time limit if it never did)
    settle_time_s: float  # true pose stays in tolerance from here on (NaN if never)
    overshoot_in: float  # point-like tasks: furthest past the target along the approach
    path_rms_in: float  # follow tasks: cross-track error of the true path
    path_max_in: float
    loc_error_final_in: float  # localizer estimate vs. truth at the end
    loc_error_max_in: float
    loc_error_per_100in: float  # final localization error per 100 in travelled
    distance_in: float
    energy_j: float
    peak_motor_temp_c: float

    def as_dict(self) -> dict:
        return asdict(self)


def target_of(task, start: tuple[float, float, float]) -> tuple[float, float, float | None]:
    """(x, y, heading or None) the task should end at; ``start`` is the true start pose."""
    if isinstance(task, (MoveToPointTask, MoveToPoseTask)):
        return task.x, task.y, getattr(task, "heading", None)
    if isinstance(task, TurnTask):
        return start[0], start[1], task.heading
    if isinstance(task, DriveTask):
        h = math.radians(start[2])
        return (
            start[0] + task.distance_in * math.cos(h),
            start[1] + task.distance_in * math.sin(h),
            start[2],
        )
    if isinstance(task, FollowTask):
        x, y = task.waypoints[-1]
        return x, y, None
    raise TypeError(task)


def _wrap(deg: np.ndarray | float):
    return (np.asarray(deg) + 180.0) % 360.0 - 180.0


def score(
    task,
    time: np.ndarray,
    truth: np.ndarray,
    estimate: np.ndarray,
    *,
    completion_time_s: float,
    timed_out: bool,
    energy_j: float,
    peak_motor_temp_c: float,
) -> TrialMetrics:
    """``truth``/``estimate``: (n, 3) arrays of x in, y in, heading deg, sampled at ``time``."""
    start = tuple(truth[0])
    tx, ty, th = target_of(task, start)
    tolerance = getattr(task, "tolerance_in", 1.0)
    heading_tol = getattr(task, "heading_tolerance_deg", math.inf)

    position_error = np.hypot(truth[:, 0] - tx, truth[:, 1] - ty)
    heading_error = np.abs(_wrap(truth[:, 2] - th)) if th is not None else np.zeros(len(time))
    final_heading = float(heading_error[-1]) if th is not None else NAN
    if isinstance(task, (FollowTask, MoveToPointTask)):
        final_heading = NAN

    inside = (position_error <= tolerance) & (heading_error <= heading_tol)
    outside = np.nonzero(~inside)[0]
    if not inside[-1]:
        settle = NAN
    else:
        settle = float(time[outside[-1] + 1]) if len(outside) else float(time[0])

    overshoot = 0.0
    if not isinstance(task, (FollowTask, TurnTask)):
        approach = np.array([tx - start[0], ty - start[1]])
        length = float(np.hypot(*approach))
        if length > 1e-9:
            progress = (truth[:, :2] - start[:2]) @ (approach / length)
            overshoot = max(0.0, float(progress.max()) - length)

    path_rms = path_max = NAN
    if isinstance(task, FollowTask):
        reference = spline(task.waypoints, 0.25)
        moving = np.hypot(*np.diff(truth[:, :2], axis=0).T) > 1e-6
        points = truth[1:][moving, :2] if moving.any() else truth[:, :2]
        cross = np.array([np.hypot(*(reference - p).T).min() for p in points])
        path_rms, path_max = float(np.sqrt(np.mean(cross**2))), float(cross.max())

    loc = np.hypot(*(estimate[:, :2] - truth[:, :2]).T)
    distance = float(np.hypot(*np.diff(truth[:, :2], axis=0).T).sum())
    heading_ok = math.isnan(final_heading) or final_heading <= heading_tol
    return TrialMetrics(
        success=bool(not timed_out and position_error[-1] <= tolerance and heading_ok),
        timed_out=timed_out,
        final_error_in=float(position_error[-1]),
        final_heading_error_deg=final_heading,
        completion_time_s=completion_time_s,
        settle_time_s=settle,
        overshoot_in=overshoot,
        path_rms_in=path_rms,
        path_max_in=path_max,
        loc_error_final_in=float(loc[-1]),
        loc_error_max_in=float(loc.max()),
        loc_error_per_100in=float(loc[-1] / distance * 100.0) if distance > 1.0 else NAN,
        distance_in=distance,
        energy_j=energy_j,
        peak_motor_temp_c=peak_motor_temp_c,
    )

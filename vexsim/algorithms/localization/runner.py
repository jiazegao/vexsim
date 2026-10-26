"""Drive a scripted path and record every localizer's estimate against ground truth."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from vexsim.algorithms.localization.base import Localizer, Pose
from vexsim.algorithms.localization.baselines import baseline_localizers
from vexsim.config.field import FieldConfig
from vexsim.config.robot import RobotConfig
from vexsim.devices.suite import SensorSuite
from vexsim.physics.robot import Robot
from vexsim.physics.world import PRIORITY_CONTROL, World


@dataclass(frozen=True)
class Segment:
    seconds: float
    left: float  # fraction of rated speed
    right: float


def _scaled(segments: Sequence[Segment], k: float) -> list[Segment]:
    return [
        Segment(s.seconds / k if k < 1 else s.seconds, s.left * k, s.right * k) for s in segments
    ]


_TOUR = [
    Segment(0.6, 0.8, 0.8),  # straight
    Segment(1.0, 1.0, 0.35),  # fast arc right
    Segment(0.5, -0.6, 0.6),  # turn in place left
    Segment(1.0, 0.35, 1.0),  # fast arc left
    Segment(0.5, 0.9, 0.9),  # straight
    Segment(0.6, 0.0, 0.0),  # stop and settle
]
SCRIPTS: dict[str, list[Segment]] = {
    "aggressive": _TOUR,
    "gentle": _scaled(_TOUR[:-1], 0.35) + [_TOUR[-1]],
}


@dataclass
class OdometryRun:
    time: np.ndarray  # seconds since the script started
    truth: np.ndarray  # (n, 3): x in, y in, heading deg
    estimates: dict[str, np.ndarray]

    def errors(self, name: str) -> tuple[np.ndarray, np.ndarray]:
        """Position error (in) and absolute heading error (deg) at every sample."""
        est = self.estimates[name]
        position = np.hypot(*(est[:, :2] - self.truth[:, :2]).T)
        heading = np.abs((est[:, 2] - self.truth[:, 2] + 180.0) % 360.0 - 180.0)
        return position, heading

    def final_error(self, name: str) -> tuple[float, float]:
        position, heading = self.errors(name)
        return float(position[-1]), float(heading[-1])


def run_odometry(
    config: RobotConfig,
    script: Sequence[Segment] | str = "aggressive",
    *,
    seed: int = 0,
    noise: str | None = None,
    localizers: Sequence[Localizer] | None = None,
    field: FieldConfig | None = None,
) -> OdometryRun:
    """Calibrate (standing still), then drive the script with the robot's own velocity control.

    Localizers update every 10 ms, right after the sensors are sampled.
    """
    segments = SCRIPTS[script] if isinstance(script, str) else list(script)
    world = World(seed=seed)
    robot = world.add_system(Robot(config))
    sensors = SensorSuite(robot, world.rng, field=field, noise=noise).attach(world)
    localizers = list(localizers) if localizers is not None else baseline_localizers(config)

    calibration = max(
        (d.spec.calibration_s for d in sensors.devices.values() if d.kind == "imu"), default=0.0
    )
    world.run_for(round(calibration + 0.1, 3))
    start = world.time
    frame = sensors.frame(world.time)
    for loc in localizers:
        loc.reset(Pose.from_si(robot.pose), frame)

    ends = np.cumsum([s.seconds for s in segments])

    def control(w: World) -> None:
        index = int(np.searchsorted(ends, w.time - start, side="right"))
        seg = segments[min(index, len(segments) - 1)]
        for name, fraction in (("left", seg.left), ("right", seg.right)):
            group = robot.group(name)
            group.set_velocity(fraction * group.rated_speed)

    times, truth = [], []
    estimates: dict[str, list] = {loc.name: [] for loc in localizers}

    def localize(w: World) -> None:
        frame = sensors.frame(w.time)
        times.append(w.time - start)
        p = Pose.from_si(robot.pose)
        truth.append((p.x, p.y, p.heading))
        for loc in localizers:
            est = loc.update(frame)
            estimates[loc.name].append((est.x, est.y, est.heading))

    world.every(10, control, priority=PRIORITY_CONTROL)
    world.every(10, localize, priority=PRIORITY_CONTROL + 1)
    world.run_for(round(float(ends[-1]), 2))
    return OdometryRun(
        np.array(times), np.array(truth), {k: np.array(v) for k, v in estimates.items()}
    )

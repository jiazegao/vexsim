"""The calibration routine: open-loop drive maneuvers that exercise each uncertain parameter.

Every step holds fixed motor voltages, so the same routine runs identically on
the real robot (generated C++, see cpp.py) and in the simulator, and a replay
of its log needs no controller model.

  launch    full power from rest: traction limit and motor torque
  coast     motors open: rolling resistance
  reverse   half power back, then brake: motor back-EMF braking
  spin      turn in place: roller friction and scrub of the corner wheels
  arc       fast arc: sideways sliding (drift)
  strafe    (robots that can) sideways: roller resistance of X-drive/mecanum/H-drive

It needs about 3 x 3 m of open floor (a field is enough): start in the middle,
facing along the longer free direction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from vexsim.algorithms.localization.base import Pose
from vexsim.calibration.log import RobotLog
from vexsim.calibration.record import PERIOD_MS, RobotLogger
from vexsim.config.robot import RobotConfig
from vexsim.devices.devices import ImuDevice
from vexsim.devices.suite import SensorSuite
from vexsim.physics.kinematics import DriveKinematics
from vexsim.physics.motor import BrakeMode
from vexsim.physics.params import resolve_params
from vexsim.physics.robot import Robot
from vexsim.physics.world import PRIORITY_CONTROL, World
from vexsim.units import in_to_m

MAX_MV = 12000
REFERENCE_SPEED_M_S = 1.2  # top speed of the straight maneuvers (about 47 in/s)
ORIGIN = Pose(0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Step:
    name: str
    seconds: float
    forward: float = 0.0  # -1..1 of the top speed in each direction (DriveKinematics.fractions)
    left: float = 0.0
    turn: float = 0.0  # counter-clockwise
    brake: Literal["coast", "brake"] = "coast"  # how the motors stop when the step is still

    @property
    def still(self) -> bool:
        return not (self.forward or self.left or self.turn)


def standard_routine(config: RobotConfig) -> list[Step]:
    """The maneuvers, at about REFERENCE_SPEED whatever the gearing, so the robot stays
    within about 45 in of where it starts."""
    forward, sideways, _ = DriveKinematics.from_config(config).top_speeds()
    f = min(1.0, REFERENCE_SPEED_M_S / forward)
    steps = [
        Step("settle", 0.5),
        Step("launch", 0.5, forward=f),
        Step("coast", 0.8),
        Step("reverse", 1.0, forward=-0.8 * f),
        Step("brake", 0.5, brake="brake"),
    ]
    if sideways:  # out and back, near the start
        s = min(1.0, REFERENCE_SPEED_M_S / sideways)
        steps += [
            Step("strafe", 0.6, left=s),
            Step("coast", 0.4),
            Step("strafe back", 0.6, left=-s),
            Step("brake", 0.5, brake="brake"),
        ]
    steps += [
        Step("spin", 1.0, turn=0.6),
        Step("coast", 0.8),
        Step("arc", 0.9, forward=0.9 * f, turn=-0.3),
        Step("coast", 0.6),
        Step("brake", 0.4, brake="brake"),
    ]
    return steps


def motor_millivolts(config: RobotConfig, step: Step) -> dict[int, int]:
    """Raw (positive-port) voltage command per motor for a step: 0 means stop."""
    fractions = DriveKinematics.from_config(config).fractions(step.forward, step.left, step.turn)
    out = {}
    for name, gear in config.drivetrain.gearing.items():
        for port in gear.motors:
            sign = 1 if port > 0 else -1
            out[abs(port)] = round(sign * fractions[name] * MAX_MV)
    return dict(sorted(out.items()))


def schedule(config: RobotConfig, steps: list[Step]) -> list[tuple[int, Step, dict[int, int]]]:
    """(start ms, step, raw mV per motor) for each step, on the 10 ms log grid."""
    out, t = [], 0
    for step in steps:
        out.append((t, step, motor_millivolts(config, step)))
        t += round(step.seconds * 1000 / PERIOD_MS) * PERIOD_MS
    out.append((t, Step("end", 0.0, brake="brake"), {}))
    return out


def run_routine(
    config: RobotConfig,
    steps: list[Step] | None = None,
    *,
    overrides: dict[str, float] | None = None,
    seed: int = 0,
    noise: str | None = None,
    start: Pose = ORIGIN,
    truth: list[tuple[float, float, float]] | None = None,
) -> RobotLog:
    """Run the routine in the simulator, the way the C++ routine runs it on the robot:
    calibrate the IMU, then every 10 ms read the sensors and apply the step's voltages.
    ``truth``, if given, collects the true pose (in, in, deg) at every log row."""
    steps = standard_routine(config) if steps is None else steps
    params = resolve_params({**config.overrides, **(overrides or {})})
    world = World(seed=seed)
    pose = (in_to_m(start.x), in_to_m(start.y), math.radians(start.heading))
    robot = world.add_system(Robot(config, params=params, pose=pose))
    sensors = SensorSuite(robot, world.rng, noise=noise).attach(world)
    imus = [d for d in sensors.devices.values() if isinstance(d, ImuDevice)]
    world.run_until(lambda w: all(d.value is not None for d in imus), timeout_s=10.0)
    world.run_for((-world.clock.us // 1000 % PERIOD_MS) / 1000)  # onto the 10 ms grid
    motors = robot.motors
    plan = schedule(config, steps)
    logger = RobotLogger(robot, sensors)
    t0_us = world.clock.us

    def control(w: World) -> None:
        elapsed_ms = (w.clock.us - t0_us) // 1000
        for start_ms, step, millivolts in plan:
            if start_ms == elapsed_ms:
                _apply(motors, step, millivolts)
        if truth is not None:
            p = Pose.from_si(robot.pose)
            truth.append((p.x, p.y, p.heading))

    world.every(PERIOD_MS, control, priority=PRIORITY_CONTROL, name="calibration routine")
    logger.attach(world)
    world.run_for(plan[-1][0] / 1000)
    return logger.log()


def _apply(motors, step: Step, millivolts: dict[int, int]) -> None:
    brake = BrakeMode.BRAKE if step.brake == "brake" else BrakeMode.COAST
    for port, motor in motors.items():
        motor.brake_mode = brake
        mv = millivolts.get(port, 0)
        if mv:
            motor.set_voltage(mv / 1000)
        else:
            motor.stop()

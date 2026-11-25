"""The library's own check: a made-up robot stepped by both steps, when the library is first
built on a computer.
"""

from __future__ import annotations

import numpy as np

from vexsim.physics.compiled.lib import Library
from vexsim.physics.compiled.modes import StepMismatch
from vexsim.physics.compiled.step import Compiled
from vexsim.physics.motor import BrakeMode

# A robot made to take the step's branches: omni and traction wheels (the middle ones
# dropped, so wheels lift off), motors mounted both ways, a mechanism with stops, a load
# and friction, and 5.5W motors (held to 8 V) among faster ones and on their own.
CHECK_ROBOT = {
    "version": 1,
    "body": {"mass_kg": 6.8, "footprint_in": [15, 14], "cg_in": [0.3, -0.2, 4.0]},
    "drivetrain": {
        "type": "differential",
        "wheels": [
            {"name": "lf", "pos_in": [5, 6], "type": "omni", "diameter_in": 3.25},
            {"name": "lm", "pos_in": [0, 6], "type": "traction", "diameter_in": 3.25,
             "drop_in": 0.03},
            {"name": "lb", "pos_in": [-5, 6], "type": "omni", "diameter_in": 3.25},
            {"name": "rf", "pos_in": [5, -6], "type": "omni", "diameter_in": 3.25},
            {"name": "rm", "pos_in": [0, -6], "type": "traction", "diameter_in": 3.25,
             "drop_in": 0.03},
            {"name": "rb", "pos_in": [-5, -6], "type": "omni", "diameter_in": 3.25},
        ],
        "gearing": {
            "left": {"motors": [1, -2, 3], "cartridge": "blue", "ratio": "36:48",
                     "wheels": ["lf", "lm", "lb"], "motors_5_5w": [3]},
            "right": {"motors": [-4, 5, -6], "cartridge": "blue", "ratio": "36:48",
                      "wheels": ["rf", "rm", "rb"], "motors_5_5w": [-6]},
        },
    },
    "mechanisms": {
        "lift": {"motors": [7, -8], "cartridge": "red", "ratio": "12:60", "inertia_kgm2": 0.02,
                 "load_torque_nm": 1.5, "friction_nm": 0.2, "range_deg": [0, 90],
                 "motors_5_5w": [-8]},
        "intake": {"motors": [9], "cartridge": "5.5w", "inertia_kgm2": 0.0002,
                   "friction_nm": 0.02},
    },
}  # fmt: skip


def self_check(lib: Library, steps: int = 400) -> float:
    """Step a made-up robot with both steps, through each control and brake mode, a stall,
    a hot motor, a lift, a push and the mechanism's stops. The largest difference found (a
    part of the number's size); raises StepMismatch past ``TOLERANCE``."""
    from vexsim.config.robot import RobotConfig
    from vexsim.physics.robot import Robot

    robot = Robot(RobotConfig.model_validate(CHECK_ROBOT), pose=(0.2, -0.1, 0.4))
    robot._compiled = step = Compiled(robot, lib, check=True)
    if not step.usable:
        raise StepMismatch(f"it can't take vexsim's own check robot: {step.why}")
    left, right, lift = robot.group("left"), robot.group("right"), robot.mechanisms["lift"]
    lifters = [motor for _, _, motor in lift.motors]
    ((_, _, roller),) = robot.mechanisms["intake"].motors

    def launch() -> None:  # wheels spin, the current limit holds, the 5.5W ones at 8 V
        left.set_voltage(12.0), right.set_voltage(12.0)
        roller.set_voltage(12.0)

    def turn() -> None:  # the traction wheels scrub
        left.set_voltage(-12.0), right.set_voltage(9.0)

    def raise_lift() -> None:
        for motor in lifters:
            motor.set_position(1.2, 4.0)

    def spin() -> None:
        left.set_velocity(30.0), right.set_velocity(-30.0)

    def hold() -> None:
        left.brake_mode = BrakeMode.HOLD
        left.stop(), right.stop()

    def push() -> None:
        robot.external_force = np.array([25.0, -40.0])
        robot.external_torque = 3.0
        left.brake_mode = BrakeMode.BRAKE

    def stall_lift() -> None:  # into its stop
        for motor in lifters:
            motor.set_voltage(12.0)

    def hot() -> None:  # a motor past where its current is cut
        robot.motors[1].thermal.housing_c = 61.0
        left.set_voltage(12.0)

    def in_the_air() -> None:
        robot.lifted = True
        right.set_velocity(50.0)

    def down() -> None:
        robot.lifted = False
        robot.external_force = np.zeros(2)
        robot.external_torque = 0.0
        for motor in lifters:
            motor.set_voltage(-6.0)

    def opposite() -> None:
        left.set_voltage(12.0), right.set_voltage(-12.0)

    def coast() -> None:
        right.brake_mode = BrakeMode.COAST
        left.stop(), right.stop()
        roller.set_velocity(-15.0)

    script = [launch, turn, raise_lift, spin, hold, push, stall_lift, hot, in_the_air, down,
              opposite, coast]  # fmt: skip
    every = max(1, steps // len(script))
    for i in range(steps):
        if i % every == 0 and i // every < len(script):
            script[i // every]()
        robot.advance(0.001)
    return step.worst

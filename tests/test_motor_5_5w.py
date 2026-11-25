"""Phase 17.1: the 5.5 W motor (PLAN.md section 19). On vexsim's dynamometer it gives what it
was fitted to; its drive is held to 8 V; configs say which motors are 5.5 W, and a 5.5 W motor
among faster ones turns at the speed its gearing gives it; the brain counts it as half; and
both physics steps take it."""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from tests.test_step import commands
from vexsim.config.checks import check_robot
from vexsim.config.robot import GearGroupConfig, MechanismConfig, RobotConfig
from vexsim.config.summary import robot_summary
from vexsim.physics import compiled
from vexsim.physics.motor import Motor55Spec, MotorSpec, V5Motor
from vexsim.physics.power import IdealSupply, PowerSystem
from vexsim.physics.rig import ShaftRig, hold_speed, torque_speed_curve
from vexsim.physics.robot import Robot
from vexsim.physics.thermal import Thermal55Spec, ThermalSpec
from vexsim.units import rad_s_to_rpm, rpm_to_rad_s

# A 6-motor drive with a 5.5 W motor a side among blue ones (as 1239E's six-bar robot has),
# a red lift with a 5.5 W motor beside its 11 W one, and an intake of a 5.5 W motor alone.
MIXED = {
    "version": 1,
    "body": {"mass_kg": 7.0, "footprint_in": [14, 14], "cg_in": [0, 0, 4.5]},
    "drivetrain": {
        "type": "differential",
        "wheels": [
            {"name": n, "pos_in": [x, y], "type": "omni", "diameter_in": 2.75}
            for n, x, y in (("lf", 4.5, 5.7), ("lm", 0, 5.7), ("lb", -4.5, 5.7),
                            ("rf", 4.5, -5.7), ("rm", 0, -5.7), ("rb", -4.5, -5.7))
        ],
        "gearing": {
            "left": {"motors": [-15, -14, -13], "cartridge": "blue", "ratio": "36:48",
                     "wheels": ["lf", "lm", "lb"], "motors_5_5w": [-13]},
            "right": {"motors": [8, 7, 10], "cartridge": "blue", "ratio": "36:48",
                      "wheels": ["rf", "rm", "rb"], "motors_5_5w": [10]},
        },
    },
    "mechanisms": {
        "lift": {"motors": [1, 2], "cartridge": "red", "ratio": "12:60", "inertia_kgm2": 0.02,
                 "load_torque_nm": 0.5, "friction_nm": 0.05, "range_deg": [0, 90],
                 "motors_5_5w": [2]},
        "intake": {"motors": [3], "cartridge": "5.5w", "inertia_kgm2": 0.0002},
    },
}  # fmt: skip


def mixed(**changes) -> RobotConfig:
    data = copy.deepcopy(MIXED)
    for path, value in changes.items():
        *keys, last = path.split(".")
        node = data
        for key in keys:
            node = node[key]
        if value is None:
            del node[last]
        else:
            node[last] = value
    return RobotConfig.model_validate(data)


# --- the motor, on vexsim's dynamometer --------------------------------------------------------


def test_it_gives_what_it_was_fitted_to():
    """0.47 N*m at stall and the 2.5 A limit, 5.0 W at its peak, 300 rpm free from a voltage
    command (150% of rated), and under a velocity command 200 rpm with 0.21 N*m left there
    (VEX's curve: 0.2). Its line: docs/models.md."""
    motor = V5Motor("5.5w")
    motor.set_velocity(motor.rated_speed)
    stall = hold_speed(motor, 0.0)
    assert stall.torque == pytest.approx(0.47, abs=0.001)
    assert stall.current == pytest.approx(2.5) and motor.current_limited

    curve = torque_speed_curve("5.5w", "voltage", points=301)
    peak = int(curve.power_out.argmax())
    assert curve.power_out[peak] == pytest.approx(5.0, abs=0.01)
    assert rad_s_to_rpm(curve.speed[peak]) == pytest.approx(150, abs=1)
    assert rad_s_to_rpm(curve.speed[-1]) == pytest.approx(300, rel=1e-3)

    held = V5Motor("5.5w")
    held.set_velocity(2 * held.rated_speed)  # held to its 200 rpm
    assert hold_speed(held, rpm_to_rad_s(199)).torque == pytest.approx(0.21, abs=0.01)
    rig = ShaftRig(V5Motor("5.5w"), load_inertia_kgm2=5e-4)
    rig.motor.set_velocity(2 * rig.motor.rated_speed)
    rig.run(1.0)
    assert rad_s_to_rpm(rig.omega) == pytest.approx(200, rel=0.005)


def test_its_drive_is_held_to_8_volts():
    """Made for VEX EXP's battery: from 8 to 12 V a command gives the same, below 8 less."""
    speeds = {}
    for volts in (12.0, 8.0, 6.0):
        rig = ShaftRig(V5Motor("5.5w", supply=IdealSupply(12.8)), load_inertia_kgm2=5e-4)
        rig.motor.set_voltage(volts)
        drive = []
        for _ in range(1500):
            rig.advance(0.001)
            drive.append(rig.motor.voltage)
        speeds[volts] = rad_s_to_rpm(rig.omega)
        assert max(drive) <= 8.0
    assert speeds[12.0] == speeds[8.0] == pytest.approx(300, rel=0.01)
    assert speeds[6.0] == pytest.approx(224, rel=0.01)
    assert V5Motor("blue").spec.max_drive_v == math.inf  # an 11 W motor: the battery's


def test_its_constants_are_its_own():
    small, big = V5Motor("5.5w"), V5Motor("green")
    assert type(small.spec) is Motor55Spec and type(big.spec) is MotorSpec
    assert type(small.thermal.spec) is Thermal55Spec and type(big.thermal.spec) is ThermalSpec
    assert (small.ratio, small.rated_power_w, big.rated_power_w) == (18, 5.5, 11.0)
    assert rad_s_to_rpm(small.rated_speed) == pytest.approx(200)
    assert small.reflected_inertia_kgm2 == pytest.approx(big.reflected_inertia_kgm2 / 2)
    # stalled for 20 s at the current limit, the smaller motor gets hotter (its thermal
    # constants are estimates: docs/models.md)
    for motor in (small, big):
        motor.set_voltage(12.0)
        for _ in range(20000):
            motor.update(0.0, 0.001)
    assert small.thermal.winding_c > big.thermal.winding_c > 40
    assert small.temperature_c > big.temperature_c > 27


def test_the_brain_counts_a_5_5w_motor_as_half():
    """VEXos shares the battery's current among more than 8 motors' worth; a 5.5 W motor is
    half of one (VEXos 1.1.3)."""

    def cap(eleven: int, small: int) -> float:
        power = PowerSystem()
        for _ in range(eleven):
            power.attach(V5Motor("green"))
        for _ in range(small):
            power.attach(V5Motor("5.5w"))
        return power.per_motor_current_cap

    assert cap(8, 0) == cap(6, 4) == cap(0, 16) == math.inf
    assert cap(9, 0) == cap(8, 2) == pytest.approx(20 / 9)


# --- configs ------------------------------------------------------------------------------------


def test_configs_say_which_motors_are_5_5w():
    group = GearGroupConfig(
        motors=(-15, -14, -13), cartridge="blue", ratio="36:48", wheels=("w",), motors_5_5w=(13,)
    )
    assert [group.motor_cartridge(p) for p in group.motors] == ["blue", "blue", "5.5w"]
    assert [group.motor_gear(p) for p in group.motors] == [1.0, 1.0, pytest.approx(1 / 3)]
    assert group.power_w == 27.5
    lift = MechanismConfig(motors=(1, 2), cartridge="red", motors_5_5w=(-2,))
    assert lift.motor_gear(2) == 2.0  # 200 rpm against red's 100
    green = MechanismConfig(motors=(1, 2), cartridge="green", motors_5_5w=(2,))
    assert green.motor_gear(2) == 1.0
    intake = MechanismConfig(motors=(3, 4), cartridge="5.5w")
    assert [intake.motor_cartridge(p) for p in (3, 4)] == ["5.5w", "5.5w"]
    assert intake.motor_gear(3) == 1.0 and intake.power_w == 11.0


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"motors_5_5w": [12]}, "port 12, which isn't among the motors"),
        ({"motors_5_5w": [13, -13]}, "names port 13 twice"),
        ({"motors_5_5w": [15, 14, 13]}, "write cartridge: 5.5w instead"),
        ({"cartridge": "5.5w"}, "drop motors_5_5w"),
        ({"cartridge": "5.5W"}, "'red', 'green', 'blue' or '5.5w'"),
    ],
)
def test_a_config_that_misnames_them_says_how(change, says):
    with pytest.raises(ValueError, match=says.replace("(", r"\(")):
        mixed(**{f"drivetrain.gearing.left.{k}": v for k, v in change.items()})


def test_the_summary_and_the_motor_budget_count_them():
    config = mixed()
    text = "\n".join(robot_summary(config))
    assert "motors -15, -14, -13 (5.5W: -13) | blue 600 rpm" in text
    assert "intake: motors 3 | 5.5w | ratio 1.0 -> 200 rpm" in text
    assert not [i for i in check_robot(config) if "budget" in i.message]
    # 8 drive motors of 11 W are the budget; 7 and two 5.5 W ones are over it
    eight = {"motors": [-15, -14, -13, -12], "motors_5_5w": None}
    assert not [
        i
        for i in check_robot(mixed(**{f"drivetrain.gearing.left.{k}": v for k, v in eight.items()}))
        if "budget" in i.message
    ]  # noqa: E501
    over = mixed(**{
        "drivetrain.gearing.left.motors": [-15, -14, -13, -12, -11],
        "drivetrain.gearing.left.motors_5_5w": [-11],
        "drivetrain.gearing.right.motors": [8, 7, 10, 9, 6],
        "drivetrain.gearing.right.motors_5_5w": [6],
    })  # fmt: skip
    (issue,) = [i for i in check_robot(over) if "budget" in i.message]
    assert "10 drive motors (99 W)" in issue.message


# --- a robot with them ---------------------------------------------------------------------------


def test_a_mixed_drive_turns_its_5_5w_motors_at_their_gearing_and_shares_the_load():
    robot = Robot(mixed())
    right = robot.group("right")
    blue, small = robot.motors[8], robot.motors[10]
    assert (blue.gear, small.gear) == (1.0, pytest.approx(1 / 3))
    robot.group("left").set_voltage(12.0)
    right.set_voltage(12.0)
    for _ in range(150):  # accelerating
        robot.advance(0.001)
    assert small.velocity == pytest.approx(blue.velocity / 3, rel=1e-12)
    assert small.torque > 0 and blue.torque > 0 and small.voltage == 8.0
    # held to rated speed: the blue motors at 600 rpm, the 5.5 W one at its 200
    robot.lifted = True
    right.set_velocity(right.rated_speed)
    for _ in range(1500):
        robot.advance(0.001)
    assert rad_s_to_rpm(blue.velocity) == pytest.approx(600, rel=0.01)
    assert rad_s_to_rpm(small.velocity) == pytest.approx(200, rel=0.01)


ALL_11W = {
    "drivetrain.gearing.left.motors_5_5w": None,
    "drivetrain.gearing.right.motors_5_5w": None,
}


def test_a_mixed_drive_has_a_fifth_less_torque_and_runs_over_under_voltage():
    """What a team gives up for the motor budget: a fifth of the torque at a standstill. And,
    under voltage commands (LemLib's), the 5.5 W motor (free at 150% of its rated speed) runs
    the blue ones (113% at 12 V) a little past theirs."""

    def at_rest(config: RobotConfig) -> float:  # the group's torque at its shaft
        robot = Robot(config)
        for group in robot.groups:
            group.set_voltage(12.0)
        robot.advance(0.001)
        return sum(sign * m.gear * m.torque for _, sign, m in robot.group("right").motors)

    assert at_rest(mixed()) / at_rest(mixed(**ALL_11W)) == pytest.approx(0.81, abs=0.01)

    def lifted(config: RobotConfig) -> Robot:
        robot = Robot(config)
        robot.lifted = True
        for group in robot.groups:
            group.set_voltage(12.0)
        for _ in range(3000):
            robot.advance(0.001)
        return robot

    mix, eleven = lifted(mixed()), lifted(mixed(**ALL_11W))
    blue = mix.motors[8]
    assert rad_s_to_rpm(eleven.motors[8].velocity) == pytest.approx(680, rel=0.01)
    assert rad_s_to_rpm(blue.velocity) == pytest.approx(705, rel=0.01)
    assert mix.motors[10].torque > 0 > blue.torque  # the blue motors held back, a little


def test_a_mechanism_with_both_kinds_turns_each_at_its_gearing():
    robot = Robot(mixed())
    lift = robot.mechanisms["lift"]
    red, small = robot.motors[1], robot.motors[2]
    assert small.gear == 2.0 and lift.inertia == pytest.approx(
        red.reflected_inertia_kgm2 + 4 * small.reflected_inertia_kgm2 + 0.02 * (12 / 60) ** 2
    )
    red.set_voltage(12.0), small.set_voltage(12.0)
    for _ in range(400):
        robot.advance(0.001)
    assert lift.position_deg > 5
    assert small.position == pytest.approx(2 * red.position, rel=1e-12)
    roller = robot.motors[3]
    roller.set_voltage(12.0)
    for _ in range(1000):
        robot.advance(0.001)
    assert roller.voltage == 8.0 and rad_s_to_rpm(roller.velocity) > 250


def test_overrides_reach_only_their_motors():
    config = mixed().model_copy(update={"overrides": {"motor_5_5w.natural_free_rpm": 270.0}})
    robot = Robot(config)
    assert robot.motors[13].spec.natural_free_rpm == 270.0
    assert robot.motors[15].spec.natural_free_rpm == 121.0
    assert not check_robot(config)


# --- both physics steps --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def library():
    found = compiled.library()
    if found is None:
        pytest.skip(f"no compiled step: {compiled.reason()}")
    return found


def test_both_steps_agree_on_robots_with_5_5w_motors(library):
    rng = np.random.default_rng(17)
    with compiled.use("check"):
        robot = Robot(mixed(), pose=(0.3, -0.2, 0.5))
        for i in range(3000):
            if i % 60 == 0:
                commands(robot, rng)
            robot.advance(0.001)  # raises StepMismatch past the tolerance
    assert robot.step_name == "compiled" and 0 < robot._compiled.worst < 1e-10

"""Mechanisms: motors that drive lifts, intakes and arms instead of wheels."""

import math

import pytest

from vexsim.config import load_robot, validate_robot
from vexsim.config.summary import robot_summary
from vexsim.devices.devices import MotorDevice
from vexsim.physics.motor import BrakeMode
from vexsim.physics.robot import Robot
from vexsim.runtime.simulation import Simulation
from vexsim.units import rpm_to_rad_s

# A lift on ports -7 and 8: positive raises it (port 7 is mounted reversed).
LIFT = {
    "motors": [-7, 8],
    "cartridge": "blue",
    "inertia_kgm2": 0.0004,
    "load_torque_nm": 0.3,
    "friction_nm": 0.03,
    "range_deg": [0, 3600],
}


def robot_with(robot_data, **mechanisms) -> Robot:
    robot_data["mechanisms"] = mechanisms
    return Robot(load_robot(robot_data))


def lift_volts(robot: Robot, volts: float) -> None:
    robot.motors[7].set_voltage(-volts)
    robot.motors[8].set_voltage(volts)


def test_lift_raises_holds_and_falls_under_its_weight(robot_data):
    robot = robot_with(robot_data, lift=LIFT)
    lift = robot.mechanisms["lift"]
    lift_volts(robot, 12.0)
    robot.run(0.3)
    raised = lift.position_deg
    assert 500 < raised < 3600
    # The encoders follow the lift, each in its own direction.
    assert robot.motors[8].position == pytest.approx(lift.angle)
    assert robot.motors[7].position == pytest.approx(-lift.angle)

    for motor in (robot.motors[7], robot.motors[8]):
        motor.brake_mode = BrakeMode.HOLD
        motor.stop()
    robot.run(1.0)
    assert lift.position_deg == pytest.approx(raised, abs=60)  # held, after a small sag
    held = lift.position_deg
    robot.run(1.0)
    assert lift.position_deg == pytest.approx(held, abs=1)

    for motor in (robot.motors[7], robot.motors[8]):
        motor.brake_mode = BrakeMode.COAST
    robot.run(2.0)
    assert lift.position_deg == 0.0 and lift.speed == 0.0  # back down, resting on its stop
    assert robot.pose == (0.0, 0.0, 0.0)  # the chassis never moved


def test_a_load_slows_the_lift(robot_data):
    def raised(load):
        robot = robot_with(robot_data, lift={**LIFT, "load_torque_nm": load})
        lift_volts(robot, 12.0)
        robot.run(0.3)
        return robot.mechanisms["lift"].position_deg

    assert raised(0.4) < raised(0.2) < raised(0.0)


def test_hard_stop_stalls_the_motors_there(robot_data):
    robot = robot_with(robot_data, lift={**LIFT, "range_deg": [0, 360]})
    lift = robot.mechanisms["lift"]
    lift_volts(robot, 12.0)
    robot.run(1.0)
    assert lift.position_deg == pytest.approx(360.0) and lift.at_stop
    assert lift.speed == 0.0
    assert abs(robot.motors[8].current) == pytest.approx(2.5, abs=0.01)  # stalled at the limit


def test_ratio_sets_the_output_speed(robot_data):
    wrist = {"motors": [9], "cartridge": "green", "ratio": "12:48"}  # 200 rpm motor, 4:1
    robot = robot_with(robot_data, wrist=wrist)
    robot.motors[9].set_velocity(rpm_to_rad_s(200))
    robot.run(1.0)
    wrist_mech = robot.mechanisms["wrist"]
    assert wrist_mech.speed * wrist_mech.ratio == pytest.approx(rpm_to_rad_s(50), rel=0.02)
    assert math.degrees(robot.motors[9].position) == pytest.approx(4 * wrist_mech.position_deg)


def test_friction_holds_a_light_load_and_not_a_heavy_one(robot_data):
    robot = robot_with(
        robot_data,
        light={**LIFT, "motors": [7], "load_torque_nm": 0.1, "friction_nm": 0.2},
        heavy={**LIFT, "motors": [8], "load_torque_nm": 0.3, "friction_nm": 0.2},
    )
    for mech in robot.mechanisms.values():
        mech.angle = math.radians(1800)  # start halfway up
    robot.run(0.5)
    assert robot.mechanisms["light"].position_deg == pytest.approx(1800)  # stiction, no creep
    assert robot.mechanisms["heavy"].position_deg < 1700


def test_mechanism_motors_are_devices_on_the_shared_battery(robot_data):
    robot_data["mechanisms"] = {"lift": LIFT, "intake": {"motors": [9], "cartridge": "blue"}}
    config = load_robot(robot_data)
    sim = Simulation(config, echo=None)
    for port in (7, 8, 9):
        assert isinstance(sim.sensors.devices[port], MotorDevice)
    assert len(sim.robot.power.motors) == 9
    sim.robot.motors[9].set_voltage(12.0)
    sim.robot.motors[8].set_voltage(6.0)
    sim.run_for(0.5)
    assert sim.robot.power.battery_current_a > 0.1
    recorder = sim.recorder
    assert recorder.columns[-2:] == ["lift_deg", "intake_deg"]
    assert recorder.rows[-1][-2] == pytest.approx(sim.robot.mechanisms["lift"].position_deg, 0.05)
    summary = "\n".join(robot_summary(config))
    assert "lift: motors -7, 8 | blue | ratio 1.0 -> 600 rpm | stops at 0 and 3600 deg" in summary
    assert "intake: motors 9 | blue" in summary


def test_mechanism_config_errors(robot_data):
    robot_data["mechanisms"] = {"lift": {**LIFT, "range_deg": [10, 20]}}
    report = validate_robot(robot_data)
    assert not report.ok and "low <= 0 <= high" in str(report.issues)
    robot_data["mechanisms"] = {"lift": {**LIFT, "motors": [-7, 1]}}
    report = validate_robot(robot_data)
    assert not report.ok
    assert "port 1 is already used by drivetrain.gearing.left.motors[0]" in str(report.issues)

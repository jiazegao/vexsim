"""Phase 5: the PROS 4-style Python device API."""

import math
import types

import pytest

from tests.conftest import EXAMPLE_ROBOT
from vexsim.api import delay
from vexsim.api.devices import PROS_ERR_F
from vexsim.config import load_robot
from vexsim.runtime.simulation import Simulation

CONFIG = load_robot(EXAMPLE_ROBOT)


def sim_with(autonomous=None, noise="ideal", **kw):
    program = types.SimpleNamespace(autonomous=autonomous) if autonomous else None
    sim = Simulation(CONFIG, program=program, noise=noise, echo=None, **kw)
    return sim


def test_readings_before_the_first_sample_are_pros_err():
    sim = sim_with()
    assert sim.bot.Motor(1).get_position() == PROS_ERR_F
    assert sim.bot.Imu(10).get_rotation() == PROS_ERR_F


def test_negative_port_reverses_commands_and_readings():
    sim = sim_with()
    raw, reversed_ = sim.bot.Motor(4), sim.bot.Motor(-4)
    reversed_.move_voltage(6000)
    sim.run_for(0.5)
    assert sim.robot.motors[4].velocity < 0  # raw direction is backwards...
    assert reversed_.get_actual_velocity() > 0  # ...the reversed object reads forwards
    assert raw.get_position() == pytest.approx(-reversed_.get_position())


def test_move_velocity_and_group_getters():
    sim = sim_with()
    left = sim.bot.MotorGroup([1, 2, 3])
    left.move_velocity(300)
    sim.run_for(1.0)
    assert left.get_actual_velocity() == pytest.approx(300, rel=0.03)
    assert len(left.get_position_all()) == 3
    left.brake()
    assert all(m.mode.value == "stopped" for m in (sim.robot.motors[p] for p in (1, 2, 3)))


def test_move_absolute_relative_and_tare():
    # Both drive sides together, so no motor has to drag the robot sideways on its own.
    sim = sim_with()
    left, right = sim.bot.MotorGroup([1, 2, 3]), sim.bot.MotorGroup([-4, -5, -6])
    sim.run_for(0.02)
    for side in (left, right):
        side.move_absolute(360, 200)
    sim.run_for(2.0)
    count = 360 / 300  # blue cartridge encoder resolution
    assert left.get_position() == pytest.approx(360, abs=2 * count)
    assert right.get_position() == pytest.approx(360, abs=2 * count)
    left.tare_position()
    assert left.get_position() == pytest.approx(0, abs=1e-9)
    for side in (left, right):
        side.move_relative(-90, 200)
    sim.run_for(1.5)
    assert left.get_position() == pytest.approx(-90, abs=2 * count)


def test_brake_mode_and_current_limit():
    sim = sim_with()
    motor = sim.bot.Motor(2)
    motor.set_brake_mode("hold")
    motor.set_current_limit(1200)
    physics = sim.robot.motors[2]
    assert physics.brake_mode.value == "hold"
    assert physics.current_limit_a == pytest.approx(1.2)
    motor.move(127)
    sim.run_for(0.05)
    assert motor.get_current_draw() <= 1200 + 1


def test_imu_api_is_clockwise_and_resettable():
    sim = sim_with()
    imu = sim.bot.Imu(10)
    assert imu.is_calibrating()
    sim.run_for(2.1)
    assert not imu.is_calibrating()
    sim.bot.chassis.tank(-60, 60)  # counter-clockwise turn
    sim.run_for(0.5)
    sim.bot.chassis.stop()
    sim.run_for(0.5)
    turned_ccw = math.degrees(sim.robot.pose[2])
    assert imu.get_rotation() == pytest.approx(-turned_ccw, abs=0.5)
    assert 0 <= imu.get_heading() < 360
    imu.set_rotation(90)
    assert imu.get_rotation() == pytest.approx(90)
    imu.reset()
    assert imu.is_calibrating() and imu.get_rotation() == PROS_ERR_F


def test_rotation_and_distance_api():
    sim = sim_with()
    tracker = sim.bot.Rotation(11)
    sim.bot.chassis.tank(60, 60)
    sim.run_for(0.5)
    assert tracker.get_position() > 0
    tracker.reset_position()
    assert tracker.get_position() == 0
    tracker.set_reversed(True)
    assert 0 <= tracker.get_angle() < 36000
    assert 0 < sim.bot.Distance(13).get() < 9999


def test_wrong_device_type_is_a_clear_error():
    sim = sim_with()
    with pytest.raises(ValueError, match="port 10 has ImuDevice"):
        sim.bot.Motor(10)
    with pytest.raises(ValueError, match="port 20 has nothing"):
        sim.bot.Rotation(20)


def test_controller_api():
    sim = sim_with()
    c = sim.bot.controller
    c.update({"LEFT_Y": 200, "RIGHT_X": -50}, {"R1", "bogus"})
    assert c.get_analog("LEFT_Y") == 127 and c.get_analog("ANALOG_RIGHT_X") == -50
    assert c.get_digital("R1") and c.get_digital("DIGITAL_R1") and not c.get_digital("L1")
    assert c.get_digital_new_press("R1")
    c.update({}, {"R1"})
    assert not c.get_digital_new_press("R1")


def test_delay_validation():
    assert delay(5).ms == 5
    with pytest.raises(ValueError):
        delay(-1)

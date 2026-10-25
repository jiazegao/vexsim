import math

import numpy as np
import pytest

from vexsim.physics import BrakeMode, ControlMode, MotorSpec, V5Motor
from vexsim.physics.motor import CoreConstants
from vexsim.physics.power import IdealSupply
from vexsim.physics.rig import ShaftRig, free_speed, hold_speed, torque_speed_curve
from vexsim.units import rad_s_to_rpm, rpm_to_rad_s

CARTRIDGES = [("red", 100, 2.1), ("green", 200, 1.05), ("blue", 600, 0.35)]
# Per-motor drivetrain loads sit around 4-40x the motor's reflected rotor inertia.
LOAD_RATIOS = [0, 4, 15, 40]


def rig_with_load(cartridge, load_ratio, **kw):
    motor = V5Motor(cartridge, **kw)
    return ShaftRig(motor, load_inertia_kgm2=load_ratio * motor.reflected_inertia_kgm2)


def trace(rig, seconds, dt=0.001):
    out = []
    for _ in range(round(seconds / dt)):
        rig.advance(dt)
        out.append(rig.omega)
    return np.array(out)


# --- fit to published / estimated characteristics ---------------------------------


def test_fit_reproduces_the_natural_line():
    spec = MotorSpec()
    core = CoreConstants.from_spec(spec)
    red = V5Motor("red")
    assert rad_s_to_rpm(free_speed(red, spec.reference_voltage_v)) == pytest.approx(121.0, rel=1e-3)
    stall_current = spec.reference_voltage_v / core.resistance_ohm
    assert stall_current == pytest.approx(4.69)
    stall_torque = 36 * (core.kt * stall_current - core.coulomb_nm)
    assert stall_torque == pytest.approx(3.99)


@pytest.mark.parametrize(("cartridge", "rpm", "stall_nm"), CARTRIDGES)
def test_stall_torque_matches_vex_spec(cartridge, rpm, stall_nm):
    motor = V5Motor(cartridge)
    motor.set_velocity(motor.rated_speed)
    point = hold_speed(motor, 0.0)
    assert point.torque == pytest.approx(stall_nm, rel=0.03)
    assert point.current == pytest.approx(2.5)
    assert motor.current_limited


@pytest.mark.parametrize(("cartridge", "rpm", "stall_nm"), CARTRIDGES)
def test_velocity_mode_reaches_rated_speed(cartridge, rpm, stall_nm):
    rig = rig_with_load(cartridge, 4)
    rig.motor.set_velocity(rig.motor.rated_speed * 2)  # clamped to rated
    rig.run(1.0)
    assert rad_s_to_rpm(rig.omega) == pytest.approx(rpm, rel=0.005)


def test_rated_speed_held_until_about_a_third_of_stall_torque():
    # VEX: full speed is maintained up to ~35% of stall torque.
    motor = V5Motor("red")
    motor.set_velocity(motor.rated_speed)
    knee = hold_speed(motor, rpm_to_rad_s(99.5))
    assert 0.30 * 2.1 < knee.torque < 0.40 * 2.1

    for load, expect_full_speed in ((0.6, True), (1.0, False)):
        rig = rig_with_load("red", 4)
        rig.external_torque = -load
        rig.motor.set_velocity(rig.motor.rated_speed)
        rig.run(2.0)
        rpm = rad_s_to_rpm(rig.omega)
        if expect_full_speed:
            assert rpm == pytest.approx(100, rel=0.01)
        else:
            assert rpm < 95


def test_peak_power_matches_vex_curve():
    # VEX: ~12.75 W peak, and 11 W+ across ~30% of the speed range.
    curve = torque_speed_curve("red", "velocity", points=201)
    assert 12.0 < curve.power_out.max() < 13.5
    span = curve.speed[curve.power_out >= 11.0]
    assert (span.max() - span.min()) / curve.speed.max() > 0.25


def test_voltage_mode_is_not_speed_capped():
    speeds = {}
    for volts in (6.0, 12.0):
        rig = rig_with_load("green", 4)
        rig.motor.set_voltage(volts)
        rig.run(1.5)
        speeds[volts] = rig.omega
    assert 1.9 < speeds[12.0] / speeds[6.0] < 2.1
    # Unlike velocity mode, 12 V runs past rated speed (natural line; see docs/models.md).
    assert rad_s_to_rpm(speeds[12.0]) > 200


def test_cartridges_trade_speed_for_torque():
    red, blue = V5Motor("red"), V5Motor("blue")
    assert red.reflected_inertia_kgm2 / blue.reflected_inertia_kgm2 == pytest.approx(36)
    assert red.rated_speed * 6 == pytest.approx(blue.rated_speed)


# --- current limiting -------------------------------------------------------------


def test_current_never_exceeds_limit_including_reversal():
    rig = rig_with_load("blue", 15)
    rig.motor.set_voltage(12)
    currents = []
    for _ in range(500):
        rig.advance(0.001)
        currents.append(rig.motor.current)
    rig.motor.set_voltage(-12)  # plug reversal: back-EMF adds to the drive voltage
    for _ in range(500):
        rig.advance(0.001)
        currents.append(rig.motor.current)
    assert max(abs(c) for c in currents) <= 2.5 + 1e-12
    assert rig.omega < 0


def test_user_current_limit():
    motor = V5Motor("red")
    motor.current_limit_a = 1.0
    motor.set_velocity(motor.rated_speed)
    assert hold_speed(motor, 0.0).torque == pytest.approx(36 * motor.core.kt * 1.0, rel=1e-6)
    motor.current_limit_a = 9.0
    assert motor.current_limit_a == 2.5
    motor.current_limit_a = -1.0
    assert motor.current_limit_a == 0.0


def test_effective_limit_combines_user_brain_and_thermal():
    motor = V5Motor("green")
    motor.current_limit_a = 2.2
    motor.supply_current_cap = 2.0
    motor.thermal.housing_c = motor.thermal.spec.derate_start_c + 0.1
    assert motor.effective_current_limit_a == pytest.approx(2.0 * 0.5)


# --- commands and brake modes --------------------------------------------------------


def test_zero_commands_stop_with_brake_mode():
    motor = V5Motor()
    motor.set_voltage(6)
    assert motor.mode is ControlMode.VOLTAGE
    motor.set_voltage(0)
    assert motor.mode is ControlMode.STOPPED
    motor.set_velocity(1.0)
    motor.set_velocity(0)
    assert motor.mode is ControlMode.STOPPED


def test_voltage_command_is_clamped():
    rig = rig_with_load("green", 4)
    rig.motor.set_voltage(50)
    rig.advance(0.001)
    assert rig.motor.voltage <= 12.0 + 1e-9


def test_brake_stops_faster_than_coast():
    final = {}
    for mode in (BrakeMode.COAST, BrakeMode.BRAKE):
        rig = rig_with_load("green", 15)
        rig.motor.brake_mode = mode
        rig.motor.set_velocity(rig.motor.rated_speed)
        rig.run(0.5)
        rig.motor.stop()
        rig.run(0.2)
        final[mode] = rig.omega
        if mode is BrakeMode.COAST:
            assert rig.motor.current == 0.0
    # Dynamic braking decays with the mechanical time constant (~0.13 s at this load);
    # coasting only has friction.
    assert final[BrakeMode.BRAKE] < 0.3 * final[BrakeMode.COAST]
    assert final[BrakeMode.COAST] > 0.9 * rig.motor.rated_speed


def test_hold_resists_external_torque():
    rig = rig_with_load("green", 15)
    rig.motor.brake_mode = BrakeMode.HOLD
    rig.motor.set_velocity(rig.motor.rated_speed)
    rig.run(0.3)
    rig.motor.stop()  # hold target is where the shaft was at this moment
    target = rig.motor.position
    rig.run(1.0)  # it overshoots while braking from full speed, then springs back
    assert math.degrees(abs(rig.motor.position - target)) < 1.0
    rig.external_torque = -0.5 * 1.05  # half of stall torque
    rig.run(2.0)
    assert math.degrees(abs(rig.motor.position - target)) < 1.0
    assert abs(rig.omega) < 0.05


def test_switching_to_hold_while_stopped_captures_position():
    rig = rig_with_load("green", 4)
    rig.motor.set_velocity(5.0)
    rig.run(0.5)
    rig.motor.stop()
    rig.run(0.5)  # coasts to rest
    rest = rig.angle
    rig.motor.brake_mode = BrakeMode.HOLD
    rig.external_torque = -0.3
    rig.run(1.5)
    assert math.degrees(abs(rig.angle - rest)) < 3.0


def test_position_mode_reaches_target_within_max_speed():
    rig = rig_with_load("green", 15)
    max_speed = rig.motor.rated_speed / 2
    rig.motor.set_position(2 * math.pi, max_speed)
    speeds = trace(rig, 2.0)
    assert speeds.max() <= max_speed * 1.05
    assert math.degrees(abs(rig.motor.position - 2 * math.pi)) < 0.5


# --- internal velocity controller ---------------------------------------------------


@pytest.mark.parametrize("load_ratio", LOAD_RATIOS)
def test_velocity_step_is_well_damped(load_ratio):
    rig = rig_with_load("green", load_ratio)
    target = rig.motor.rated_speed / 2
    rig.motor.set_velocity(target)
    speeds = trace(rig, 1.0)
    assert speeds.max() / target - 1 < 0.08
    outside = np.nonzero(np.abs(speeds - target) > 0.02 * target)[0]
    settle_s = (outside[-1] + 1) * 0.001 if len(outside) else 0.0
    assert settle_s < 0.6


@pytest.mark.parametrize("load_ratio", [4, 40])
def test_load_disturbance_is_rejected(load_ratio):
    rig = rig_with_load("green", load_ratio)
    target = rig.motor.rated_speed / 2
    rig.motor.set_velocity(target)
    rig.run(1.0)
    rig.external_torque = -0.3 * 1.05
    speeds = trace(rig, 1.5)
    assert speeds.min() < 0.97 * target  # it does sag...
    assert speeds[-1] == pytest.approx(target, rel=0.005)  # ...then recovers fully


def test_velocity_reversal():
    rig = rig_with_load("blue", 15)
    rig.motor.set_velocity(rig.motor.rated_speed)
    rig.run(0.5)
    rig.motor.set_velocity(-rig.motor.rated_speed)
    rig.run(0.8)
    assert rig.omega == pytest.approx(-rig.motor.rated_speed, rel=0.01)


# --- energy and bookkeeping ------------------------------------------------------------


def test_motoring_draws_more_power_than_it_delivers():
    motor = V5Motor("green")
    motor.set_velocity(motor.rated_speed)
    point = hold_speed(motor, motor.rated_speed * 0.6)
    assert point.power_in > point.power_out > 0


def test_position_integrates_shaft_speed():
    motor = V5Motor()
    for _ in range(1000):
        motor.update(2.0, 0.001)
    assert motor.position == pytest.approx(2.0)
    assert motor.velocity_estimate == pytest.approx(2.0, rel=1e-6)


def test_supply_sees_the_load():
    supply = IdealSupply(12.8)
    motor = V5Motor("green", supply=supply)
    motor.set_velocity(motor.rated_speed)
    motor.update(0.0, 0.001)
    assert supply.load_w == pytest.approx(motor.power_in) and supply.load_w > 0


def test_invalid_construction():
    with pytest.raises(ValueError):
        V5Motor("purple")
    with pytest.raises(ValueError):
        MotorSpec(free_current_a=5.0)
    with pytest.raises(ValueError):
        MotorSpec(velocity_kp=0)

import pytest

from vexsim.physics import ThermalSpec, V5Motor
from vexsim.physics.thermal import DERATE_FACTORS, MotorThermal


def stall(motor, seconds, dt=0.01):
    """Hold the shaft still at full command (a motor pushing against a wall)."""
    for _ in range(round(seconds / dt)):
        motor.update(0.0, dt)


def test_stall_heats_motor_until_it_derates():
    motor = V5Motor("green")
    motor.set_velocity(motor.rated_speed)
    t, derated_at = 0.0, None
    while t < 400 and derated_at is None:
        stall(motor, 1.0)
        t += 1.0
        assert motor.thermal.winding_c >= motor.temperature_c  # the sensor lags the winding
        if motor.over_temp:
            derated_at = t
    # Estimate: a stalled motor reaches derating in one to four minutes (calibrate in Phase 10).
    assert derated_at is not None and 60 <= derated_at <= 240
    assert motor.effective_current_limit_a == pytest.approx(1.25)


def test_derating_steps():
    spec = ThermalSpec()
    thermal = MotorThermal(spec)
    expected = []
    for level in range(len(DERATE_FACTORS)):
        thermal.housing_c = spec.derate_start_c + (level - 1) * spec.derate_step_c + 0.1
        expected.append((thermal.derate_level, thermal.derate_factor))
    assert expected == [(0, 1.0), (1, 0.5), (2, 0.25), (3, 0.125), (4, 0.0)]
    thermal.housing_c = 500
    assert thermal.derate_level == 4


def test_fully_derated_motor_produces_no_drive_torque():
    motor = V5Motor("green")
    motor.thermal.housing_c = 200
    motor.set_voltage(12)
    torque = motor.update(0.0, 0.001)
    assert motor.current == 0.0 and torque == pytest.approx(0.0)


def test_motor_cools_back_to_ambient():
    motor = V5Motor("green")
    motor.set_velocity(motor.rated_speed)
    stall(motor, 150)
    hot = motor.temperature_c
    motor.stop()
    stall(motor, 1800)
    assert motor.temperature_c < hot
    assert motor.temperature_c == pytest.approx(motor.thermal.spec.ambient_c, abs=1.0)
    assert not motor.over_temp


def test_light_load_stays_cool():
    motor = V5Motor("green")
    motor.set_velocity(motor.rated_speed)
    for _ in range(12_000):  # two minutes cruising unloaded at 10 ms
        motor.update(motor.rated_speed, 0.01)
    assert motor.temperature_c < 30


def test_thermal_spec_validation():
    with pytest.raises(ValueError):
        ThermalSpec(housing_heat_capacity_j_per_k=0)
    with pytest.raises(ValueError):
        ThermalSpec(derate_start_c=20)

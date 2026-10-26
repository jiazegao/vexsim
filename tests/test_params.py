import pytest

from vexsim.config import load_robot, validate_robot
from vexsim.physics import BatterySpec, MotorSpec, ThermalSpec, resolve_params
from vexsim.physics.params import check_overrides


def test_defaults():
    params = resolve_params()
    assert params.motor == MotorSpec()
    assert params.thermal == ThermalSpec()
    assert params.battery == BatterySpec()


def test_overrides_apply_to_their_group():
    params = resolve_params(
        {
            "motor.free_current_a": 0.2,
            "battery.internal_resistance_ohm": 0.15,
            "thermal.ambient_c": 30,
        }
    )
    assert params.motor.free_current_a == 0.2
    assert params.battery.internal_resistance_ohm == 0.15
    assert params.thermal.ambient_c == 30.0
    assert params.motor.velocity_kp == MotorSpec().velocity_kp


@pytest.mark.parametrize(
    "overrides",
    [
        {"motor.nope": 1.0},
        {"motor.free_current_a": "fast"},
        {"motor.free_current_a": True},
        {"battery.ocv_v": 1.0},  # tuples are not scalar-overridable
        {"gearbox.ratio": 2.0},
        {"motor.free_current_a": 9.0},  # valid alone, inconsistent with stall current
    ],
)
def test_bad_overrides_raise(overrides):
    with pytest.raises(ValueError):
        resolve_params(overrides)


def test_phase9_groups_apply():
    params = resolve_params(
        {"wheel.traction.mu": 0.8, "wheel.mecanum.roller_mu": 0.1, "field.wall_restitution": 0}
    )
    assert params.traction_wheel.mu == 0.8
    assert params.mecanum_wheel.roller_mu == 0.1
    assert params.field.wall_restitution == 0.0
    assert params.wheel("traction") is params.traction_wheel
    assert check_overrides({"wheel.traction.lateral_mu": 0.9})[0][0] == "error"  # one mu
    with pytest.raises(ValueError, match="0..1"):
        resolve_params({"field.wall_restitution": 1.5})


def test_wheel_and_chassis_overrides():
    params = resolve_params({"wheel.omni.lateral_mu": 0.08, "chassis.wheel_stiffness_n_per_m": 5e4})
    assert params.omni_wheel.lateral_mu == 0.08
    assert params.chassis.wheel_stiffness_n_per_m == 5e4
    with pytest.raises(ValueError):
        resolve_params({"wheel.omni.lateral_mu": -1.0})
    with pytest.raises(ValueError):
        resolve_params({"wheel.square.lateral_mu": 0.1})


def test_robot_config_reports_override_problems(robot_data):
    robot_data["overrides"] = {"motor.free_current_a": 0.2, "motor.free_curent_a": 0.2}
    report = validate_robot(robot_data)
    assert [(i.severity, i.location) for i in report.issues] == [
        ("error", "overrides.motor.free_curent_a")
    ]

    robot_data["overrides"] = {"motor.free_current_a": 0.2, "wheel.omni.lateral_mu": 0.08}
    cfg = load_robot(robot_data)
    params = resolve_params(cfg.overrides)
    assert params.motor.free_current_a == 0.2
    assert params.omni_wheel.lateral_mu == 0.08

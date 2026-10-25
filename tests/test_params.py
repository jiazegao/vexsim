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


def test_future_groups_only_warn():
    assert check_overrides({"wheel.omni.lateral_mu": 0.08}) == [
        ("warning", "wheel.omni.lateral_mu", "'wheel' parameters take effect in Phase 3")
    ]
    assert resolve_params({"wheel.omni.lateral_mu": 0.08}).motor == MotorSpec()


def test_robot_config_reports_override_problems(robot_data):
    robot_data["overrides"] = {"motor.free_current_a": 0.2, "motor.free_curent_a": 0.2}
    report = validate_robot(robot_data)
    assert [(i.severity, i.location) for i in report.issues] == [
        ("error", "overrides.motor.free_curent_a")
    ]

    robot_data["overrides"] = {"motor.free_current_a": 0.2, "wheel.omni.lateral_mu": 0.08}
    cfg = load_robot(robot_data)
    assert resolve_params(cfg.overrides).motor.free_current_a == 0.2

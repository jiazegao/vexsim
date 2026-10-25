import math

import pytest

from tests.conftest import EXAMPLE_ROBOT
from vexsim.config import ConfigError, load_robot, validate_robot
from vexsim.config.robot import ratio_value


def issues_at(report, severity):
    return {(i.location, i.message) for i in report.issues if i.severity == severity}


def messages(report, severity="error"):
    return " | ".join(f"{loc}: {msg}" for loc, msg in sorted(issues_at(report, severity)))


# --- the example robot ------------------------------------------------------


def test_example_robot_is_clean():
    report = validate_robot(EXAMPLE_ROBOT)
    assert report.ok, messages(report)
    assert report.warnings == []


def test_example_robot_derived_values():
    cfg = load_robot(EXAMPLE_ROBOT)
    left = cfg.drivetrain.gearing["left"]
    assert left.speed_ratio == pytest.approx(0.75)
    assert left.wheel_free_rpm == pytest.approx(450.0)
    assert left.motors == (1, 2, 3)
    assert cfg.drivetrain.gearing["right"].motors == (-4, -5, -6)
    assert cfg.drivetrain.wheel("rb").pos_in == (-5.5, -6.0)
    # Uniform box: 6.5 kg over 15 x 15 in
    side = 15 * 0.0254
    assert cfg.body.yaw_inertia_kgm2() == pytest.approx(6.5 * 2 * side**2 / 12)
    tracking = [s for s in cfg.sensors if s.type == "rotation"]
    assert [s.tracking_wheel.heading_deg for s in tracking] == [0, 90]


def test_config_is_immutable():
    cfg = load_robot(EXAMPLE_ROBOT)
    with pytest.raises(Exception):  # noqa: B017 - pydantic raises ValidationError
        cfg.body.mass_kg = 1.0


# --- gear ratios ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [("36:48", 0.75), ("48:36", 4 / 3), (" 1 : 1 ", 1.0), (0.6, 0.6), (2, 2.0)],
)
def test_ratio_value(ratio, expected):
    assert ratio_value(ratio) == pytest.approx(expected)


@pytest.mark.parametrize("ratio", ["36:0", "0:48", "-36:48", "a:b", "1:2:3", 0, -1.0, math.inf])
def test_bad_ratio_values(ratio):
    with pytest.raises(ValueError):
        ratio_value(ratio)


@pytest.mark.parametrize("ratio", ["36:0", "abc", True, [36, 48]])
def test_bad_ratio_in_config(robot_data, ratio):
    robot_data["drivetrain"]["gearing"]["left"]["ratio"] = ratio
    report = validate_robot(robot_data)
    assert not report.ok
    assert {loc for loc, _ in issues_at(report, "error")} == {"drivetrain.gearing.left.ratio"}


# --- structural errors -----------------------------------------------------------


def test_unknown_key_suggests_spelling(robot_data):
    wheel = robot_data["drivetrain"]["wheels"][0]
    wheel["diamter_in"] = wheel.pop("diameter_in")
    report = validate_robot(robot_data)
    errors = issues_at(report, "error")
    assert ("drivetrain.wheels[0].diameter_in", "required key is missing") in errors
    assert (
        "drivetrain.wheels[0].diamter_in",
        "unknown key 'diamter_in' (did you mean 'diameter_in'?)",
    ) in errors


@pytest.mark.parametrize("port", [0, 22, -22, "1", 1.0, True])
def test_bad_motor_ports(robot_data, port):
    robot_data["drivetrain"]["gearing"]["left"]["motors"][0] = port
    report = validate_robot(robot_data)
    assert {loc for loc, _ in issues_at(report, "error")} == {"drivetrain.gearing.left.motors[0]"}


@pytest.mark.parametrize("port", [0, -10, 22])
def test_bad_sensor_ports(robot_data, port):
    robot_data["sensors"][0]["port"] = port
    report = validate_robot(robot_data)
    # The tagged-union type name is stripped from the location.
    assert {loc for loc, _ in issues_at(report, "error")} == {"sensors[0].port"}


def test_unknown_sensor_type(robot_data):
    robot_data["sensors"].append({"type": "gps", "port": 20})
    report = validate_robot(robot_data)
    assert "sensors[4]" in {loc for loc, _ in issues_at(report, "error")}


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("body", "mass_kg"), 0),
        (("body", "mass_kg"), float("nan")),
        (("body", "footprint_in"), [15]),
        (("body", "cg_in"), [0, 0, 0]),
        (("body", "inertia_kgm2"), "big"),
        (("body", "inertia_kgm2"), -0.1),
        (("drivetrain", "type"), "swerve"),
    ],
)
def test_bad_scalar_values(robot_data, path, value):
    section, key = path
    robot_data[section][key] = value
    report = validate_robot(robot_data)
    assert report.config is None
    assert all(loc.startswith(f"{section}.{key}") for loc, _ in issues_at(report, "error"))


def test_explicit_inertia(robot_data):
    robot_data["body"]["inertia_kgm2"] = 0.2
    assert load_robot(robot_data).body.yaw_inertia_kgm2() == 0.2


def test_top_level_must_be_mapping(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("- 1\n- 2\n", encoding="utf-8")
    report = validate_robot(path)
    assert not report.ok and report.config is None


def test_load_robot_raises_with_locations(robot_data):
    robot_data["body"]["mass_kg"] = -1
    with pytest.raises(ConfigError) as info:
        load_robot(robot_data)
    assert "body.mass_kg" in str(info.value)


# --- semantic errors ---------------------------------------------------------------


def test_duplicate_port_between_motor_and_sensor(robot_data):
    robot_data["sensors"][0]["port"] = 4  # right motor is on -4
    report = validate_robot(robot_data)
    assert (
        "sensors[0]",
        "port 4 is already used by drivetrain.gearing.right.motors[0]",
    ) in issues_at(report, "error")


def test_duplicate_wheel_name(robot_data):
    robot_data["drivetrain"]["wheels"][1]["name"] = "lf"
    report = validate_robot(robot_data)
    assert "drivetrain.wheels[1].name" in {loc for loc, _ in issues_at(report, "error")}


def test_unknown_and_double_driven_wheels(robot_data):
    gearing = robot_data["drivetrain"]["gearing"]
    gearing["left"]["wheels"] = ["lf", "lm", "zz"]
    gearing["right"]["wheels"] = ["rf", "rm", "rb", "lf"]
    report = validate_robot(robot_data)
    errors = {loc for loc, _ in issues_at(report, "error")}
    assert "drivetrain.gearing.left.wheels[2]" in errors  # unknown 'zz'
    assert "drivetrain.gearing.right.wheels[3]" in errors  # 'lf' driven twice
    assert "drivetrain.wheels[2]" in errors  # 'lb' no longer driven


def test_things_outside_footprint(robot_data):
    robot_data["drivetrain"]["wheels"][0]["pos_in"] = [8, 6]
    robot_data["sensors"][3]["pos_in"] = [7.6, 0]
    robot_data["sensors"][1]["tracking_wheel"]["pos_in"] = [0, -9]
    robot_data["body"]["cg_in"] = [0, 8, 3]
    report = validate_robot(robot_data)
    errors = {loc for loc, _ in issues_at(report, "error")}
    assert errors == {
        "drivetrain.wheels[0].pos_in",
        "sensors[3].pos_in",
        "sensors[1].tracking_wheel.pos_in",
        "body.cg_in",
    }


def test_point_on_footprint_edge_is_inside(robot_data):
    robot_data["sensors"][3]["pos_in"] = [7.5, 0]
    assert validate_robot(robot_data).ok


def test_differential_requires_left_and_right(robot_data):
    gearing = robot_data["drivetrain"]["gearing"]
    gearing["port_side"] = gearing.pop("left")
    report = validate_robot(robot_data)
    assert "drivetrain.gearing" in {loc for loc, _ in issues_at(report, "error")}


# --- warnings ---------------------------------------------------------------------


def test_side_swapped_wheels_warn(robot_data):
    gearing = robot_data["drivetrain"]["gearing"]
    gearing["left"]["wheels"], gearing["right"]["wheels"] = (
        gearing["right"]["wheels"],
        gearing["left"]["wheels"],
    )
    report = validate_robot(robot_data)
    assert report.ok
    assert {loc for loc, _ in issues_at(report, "warning")} == {
        "drivetrain.gearing.left",
        "drivetrain.gearing.right",
    }


def test_angled_differential_wheel_warns(robot_data):
    robot_data["drivetrain"]["wheels"][0]["heading_deg"] = 45
    robot_data["drivetrain"]["wheels"][1]["heading_deg"] = 180  # reversed is still parallel
    report = validate_robot(robot_data)
    assert {loc for loc, _ in issues_at(report, "warning")} == {"drivetrain.wheels[0].heading_deg"}


def test_mixed_diameters_warn(robot_data):
    robot_data["drivetrain"]["wheels"][0]["diameter_in"] = 4.0
    report = validate_robot(robot_data)
    assert report.ok
    assert "drivetrain.gearing.left" in {loc for loc, _ in issues_at(report, "warning")}


def test_size_mass_and_motor_budget_warnings(robot_data):
    robot_data["body"]["footprint_in"] = [18.5, 15]
    robot_data["body"]["mass_kg"] = 20
    robot_data["drivetrain"]["gearing"]["left"]["motors"] = [1, 2, 3, 7, 8, 9]  # 9 motors = 99 W
    report = validate_robot(robot_data)
    assert report.ok
    assert {loc for loc, _ in issues_at(report, "warning")} == {
        "body.footprint_in",
        "body.mass_kg",
        "drivetrain.gearing",
    }


def test_unsimulated_features_warn(robot_data):
    robot_data["drivetrain"]["wheels"][0]["type"] = "traction"
    report = validate_robot(robot_data)
    assert report.ok
    assert any("not simulated yet" in msg for _, msg in issues_at(report, "warning"))

    robot_data["drivetrain"]["type"] = "xdrive"
    report = validate_robot(robot_data)
    assert (
        "drivetrain.type",
        "'xdrive' drivetrains run on the generic wheel model but are not validated until Phase 9",
    ) in (issues_at(report, "warning"))


def test_cg_must_be_over_the_wheels(robot_data):
    # Narrow the wheelbase to the front half; the centered CG now sits behind it.
    for wheel in robot_data["drivetrain"]["wheels"]:
        wheel["pos_in"][0] = 5.5 if wheel["pos_in"][0] > 0 else 2.0
    report = validate_robot(robot_data)
    assert ("body.cg_in") in {loc for loc, _ in issues_at(report, "error")}

    for wheel in robot_data["drivetrain"]["wheels"]:
        wheel["pos_in"][0] = 0.0  # all wheels on one line
    report = validate_robot(robot_data)
    assert "drivetrain.wheels" in {loc for loc, _ in issues_at(report, "error")}


def test_overrides_key_format(robot_data):
    robot_data["overrides"] = {"wheel.omni.lateral_mu": 0.08}
    assert load_robot(robot_data).overrides == {"wheel.omni.lateral_mu": 0.08}
    robot_data["overrides"] = {"Not A Key": 1}
    assert not validate_robot(robot_data).ok

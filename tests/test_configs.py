"""Config documents for the browser's editors: issues at their lines, numbers changed in
place (comments and layout untouched), files written back as they were."""

from pathlib import Path

import pytest
import yaml

from vexsim.app.configs import (
    Edit,
    PatchError,
    check_text,
    format_number,
    format_override,
    kind_of,
    patch_text,
    read_config,
    set_overrides,
    write_config,
)

ROOT = Path(__file__).resolve().parents[1]
ROBOT_1239E = ROOT / "examples" / "robots" / "1239e_2026-27.yaml"

ROBOT = """\
# a test robot
version: 1
name: test bot

body:
  mass_kg: 6.0
  footprint_in: [18, 18]   # square
  cg_in: [0, 0, 4]

drivetrain:
  type: differential
  wheels:
    - {name: lf, pos_in: [5, 7], type: omni, diameter_in: 3.25}
    - {name: lb, pos_in: [-5, 7], type: omni, diameter_in: 3.25}
    - name: rf
      pos_in: [5, -7]   # right side
      type: omni
      diameter_in: 3.25
    - {name: rb, pos_in: [-5, -7], type: omni, diameter_in: 3.25}
  gearing:
    left: {motors: [1], cartridge: blue, wheels: [lf, lb]}
    right: {motors: [-2], cartridge: blue, wheels: [rf, rb]}

sensors:
  - {type: distance, port: 3, pos_in: [8.5, 0], heading_deg: 0}  # front
  - type: imu
    port: 4   # the IMU
"""


def changed_lines(before: str, after: str) -> list[tuple[str, str]]:
    old, new = before.splitlines(), after.splitlines()
    assert len(old) == len(new)
    return [(a, b) for a, b in zip(old, new, strict=True) if a != b]


def test_a_valid_config_has_no_issues_and_says_where_its_parts_are():
    checked = check_text(ROBOT, "robot")
    assert checked.issues == [] and checked.config is not None
    assert any("4 wheels" in line for line in checked.summary)
    assert checked.places["drivetrain.wheels[0]"].line == 13
    assert checked.places["drivetrain.wheels[2]"].line == 15  # a block mapping: its first line
    assert checked.places["sensors[1]"].line == 26
    assert checked.places["body.cg_in"].line == 8


def test_issues_are_placed_at_their_lines():
    outside = ROBOT.replace("pos_in: [8.5, 0]", "pos_in: [12, 0]")
    (issue,) = check_text(outside, "robot").issues
    assert issue.location == "sensors[0].pos_in" and issue.span.line == 25
    assert issue.span.column == outside.splitlines()[24].index("[12, 0]") + 1  # the list itself

    typo = ROBOT.replace("heading_deg: 0}", "heading: 0}")
    (issue,) = check_text(typo, "robot").issues
    assert "unknown key 'heading'" in issue.message and issue.span.line == 25
    assert check_text(typo, "robot").config is None  # no diagram until it parses

    missing = ROBOT.replace("    port: 4   # the IMU\n", "")
    (issue,) = check_text(missing, "robot").issues
    assert issue.message == "required key is missing"
    assert issue.span.line == 26  # the IMU's mapping, where the port belongs


def test_broken_yaml_is_placed_too():
    broken = ROBOT.replace("cg_in: [0, 0, 4]", "cg_in: [0, 0, 4")
    (issue,) = check_text(broken, "robot").issues
    assert issue.severity == "error" and issue.span is not None and issue.span.line >= 8
    twice = ROBOT.replace("  mass_kg: 6.0\n", "  mass_kg: 6.0\n  mass_kg: 7.0\n")
    (issue,) = check_text(twice, "robot").issues
    assert "duplicate key 'mass_kg'" in issue.message and issue.span.line == 7
    assert check_text("", "robot").issues[0].message == "the file is empty"


def test_an_override_with_dots_in_its_key_is_found():
    text = ROBOT + "overrides:\n  wheel.omni.no_such_thing: 1\n"
    issues = check_text(text, "robot").issues
    assert issues and issues[0].location == "overrides.wheel.omni.no_such_thing"
    assert issues[0].span.line == 29


def test_a_drag_rewrites_just_its_numbers():
    moved = patch_text(
        ROBOT, [Edit("sensors[0].pos_in", [8.625, 0]), Edit("sensors[0].heading_deg", 15)]
    )
    assert changed_lines(ROBOT, moved) == [
        (
            "  - {type: distance, port: 3, pos_in: [8.5, 0], heading_deg: 0}  # front",
            "  - {type: distance, port: 3, pos_in: [8.625, 0], heading_deg: 15}  # front",
        )
    ]
    # a number that didn't change keeps its spelling, however precise
    text = ROBOT.replace("pos_in: [5, -7]", "pos_in: [5.1234567, -7]")
    moved = patch_text(text, [Edit("drivetrain.wheels[2].pos_in", [5.1234567, -6.5])])
    assert changed_lines(text, moved) == [
        (
            "      pos_in: [5.1234567, -7]   # right side",
            "      pos_in: [5.1234567, -6.5]   # right side",
        )
    ]
    assert patch_text(ROBOT, [Edit("body.mass_kg", 6)]) == ROBOT  # 6 is 6.0


def test_a_missing_key_is_added_in_its_mapping_s_own_style():
    flow = patch_text(ROBOT, [Edit("drivetrain.wheels[0].drop_in", 0.125)])
    assert (
        "    - {name: lf, pos_in: [5, 7], type: omni, diameter_in: 3.25, drop_in: 0.125}\n" in flow
    )
    block = patch_text(ROBOT, [Edit("sensors[1].mount_yaw_deg", -90)])
    assert block.endswith("    port: 4   # the IMU\n    mount_yaw_deg: -90\n")
    after_a_list = patch_text(ROBOT, [Edit("sensors[1].pos_in", [1, 2])])
    assert after_a_list.endswith("    port: 4   # the IMU\n    pos_in: [1, 2]\n")
    for text in (flow, block, after_a_list):
        assert check_text(text, "robot").issues == []
    crlf = ROBOT.replace("\n", "\r\n")
    added = patch_text(crlf, [Edit("sensors[1].mount_yaw_deg", 5)])
    assert added.endswith("# the IMU\r\n    mount_yaw_deg: 5\r\n")
    assert "\n" not in added.replace("\r\n", "")  # every line still ends in \r\n


def test_what_can_t_be_changed_in_place_says_why():
    anchored = ROBOT.replace("cg_in: [0, 0, 4]", "cg_in: &cg [0, 0, 4]") + "extra: *cg\n"
    with pytest.raises(PatchError, match="anchor"):
        patch_text(anchored, [Edit("body.cg_in", [1, 0, 4])])
    merged = ROBOT.replace(
        "  - {type: distance, port: 3, pos_in: [8.5, 0], heading_deg: 0}  # front",
        "  - &front {type: distance, port: 3, pos_in: [8.5, 0], heading_deg: 0}\n"
        "  - {<<: *front, port: 5}",
    )
    with pytest.raises(PatchError, match="anchor"):
        patch_text(merged, [Edit("sensors[1].pos_in", [1, 1])])
    with pytest.raises(PatchError, match="a list of 2 numbers"):
        patch_text(ROBOT, [Edit("body.mass_kg", [1, 2])])
    with pytest.raises(PatchError, match="isn't in the file"):
        patch_text(ROBOT, [Edit("sensors[7].pos_in", [1, 2])])
    with pytest.raises(PatchError, match="doesn't read"):
        patch_text("body: [", [Edit("body.mass_kg", 1)])
    with pytest.raises(PatchError, match="number"):
        format_number(float("nan"))


def test_the_1239e_robot_keeps_its_comments_when_a_sensor_moves():
    text = ROBOT_1239E.read_text(encoding="utf-8")
    moved = patch_text(text, [Edit("sensors[1].pos_in", [5.25, 5.6937585])])
    [(before, after)] = changed_lines(text, moved)
    assert before.endswith("# frontL") and after.endswith("# frontL")
    assert "pos_in: [ 5.25,  5.6937585]" in after
    checked = check_text(moved, "robot")
    assert checked.issues == [] and checked.config.sensors[1].pos_in == (5.25, 5.6937585)


def test_robots_and_fields_are_told_apart_even_when_broken():
    assert kind_of(ROBOT) == "robot"
    assert kind_of("size_in: [144, 144]\nelements: []\n") == "field"
    assert kind_of("drivetrain:\n  wheels: [\n") == "robot"  # unreadable, still a robot
    assert kind_of("task: {type: follow}\nrobot: r.yaml\n") is None


def test_files_are_written_back_in_their_own_line_endings(tmp_path):
    path = tmp_path / "robot.yaml"
    path.write_bytes(b"\xef\xbb\xbf" + ROBOT.replace("\n", "\r\n").encode())
    read = read_config(path)
    assert read.text == ROBOT and read.crlf and read.bom
    version = write_config(path, patch_text(read.text, [Edit("body.mass_kg", 7)]), read)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n  mass_kg: 7\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n") and version != read.version
    assert read_config(path).version == version


def test_fitted_values_go_under_overrides():
    values = {"wheel.omni.lateral_mu": 0.283456789, "battery.internal_resistance_ohm": 1.5e-5}
    added = set_overrides("body:\n  mass_kg: 6  # kg\ndrivetrain: {}", values)
    assert added == (
        "body:\n  mass_kg: 6  # kg\ndrivetrain: {}\noverrides:\n"
        "  wheel.omni.lateral_mu: 0.283457\n  battery.internal_resistance_ohm: 1.5e-05\n"
    )
    assert yaml.safe_load(added)["overrides"]["battery.internal_resistance_ohm"] == 1.5e-5
    assert format_override(1e-5) == "1.0e-05"  # YAML reads 1e-05 as text
    block = "overrides:\n  wheel.omni.lateral_mu: 0.2  # guess\n  motor.kt: 1.1\nbody: {}\n"
    assert set_overrides(block, values) == (
        "overrides:\n  wheel.omni.lateral_mu: 0.283457  # guess\n  motor.kt: 1.1\n"
        "  battery.internal_resistance_ohm: 1.5e-05\nbody: {}\n"
    )  # changed in place, comments kept; the new key after the others
    empty = "overrides:   # fitted below\nbody: {}\n"
    assert set_overrides(empty, {"a.b": 2}) == "overrides:\n  a.b: 2\nbody: {}\n"
    assert set_overrides("overrides: {}\n", {"a.b": 2, "c.d": 3}) == "overrides: {a.b: 2, c.d: 3}\n"
    flow = "overrides: {a.b: 1}\r\nbody: {}\r\n"
    assert set_overrides(flow, {"c.d": 3}) == "overrides: {a.b: 1, c.d: 3}\r\nbody: {}\r\n"
    with pytest.raises(PatchError, match="anchor or an alias"):
        set_overrides("overrides: &o\n  a.b: 1\n", {"a.b": 2})
    with pytest.raises(PatchError, match="isn't a mapping"):
        set_overrides("overrides: [1]\n", {"a.b": 2})

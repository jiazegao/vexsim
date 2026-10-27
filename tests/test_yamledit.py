"""Phase 12.3: the Design view's changes to a config's YAML (vexsim/app/yamledit.py): values
set, list items added and removed, keys renamed, in their neighbours' style, with every
comment and line that isn't changed left as it was."""

import difflib
import re
from pathlib import Path

import pytest

from tests.test_configs import ROBOT
from vexsim.app.configs import Edit, PatchError, check_text
from vexsim.app.yamledit import Change, apply, number

ROOT = Path(__file__).resolve().parents[1]
ROBOT_1239E = ROOT / "examples" / "robots" / "1239e_2026-27.yaml"


def diff(before: str, after: str) -> list[str]:
    """The lines taken out (-) and put in (+)."""
    lines = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
    return [line for line in lines if line[:1] in "+-" and not line.startswith(("---", "+++"))]


def comments(text: str) -> list[str]:
    return re.findall(r"#.*", text)


# --- setting values --------------------------------------------------------------------------


def test_a_value_is_set_where_it_is_written():
    assert diff(ROBOT, apply(ROBOT, [Change("set", "drivetrain.type", "xdrive")])) == [
        "-  type: differential",
        "+  type: xdrive",
    ]
    assert diff(ROBOT, apply(ROBOT, [Change("set", "name", "Bot #2: the sequel")])) == [
        "-name: test bot",
        '+name: "Bot #2: the sequel"',  # quoted: it wouldn't read back as itself
    ]
    assert diff(ROBOT, apply(ROBOT, [Change("set", "body.mass_kg", 6.75)])) == [
        "-  mass_kg: 6.0",
        "+  mass_kg: 6.75",
    ]
    assert apply(ROBOT, [Change("set", "body.mass_kg", 6)]) == ROBOT  # 6.0 already
    gearing = apply(ROBOT, [Change("set", "drivetrain.gearing.left.wheels", ["lf", "lb", "lm"])])
    assert diff(ROBOT, gearing) == [
        "-    left: {motors: [1], cartridge: blue, wheels: [lf, lb]}",
        "+    left: {motors: [1], cartridge: blue, wheels: [lf, lb, lm]}",
    ]


def test_words_and_numbers_are_written_to_read_back_as_themselves():
    ratio = apply(ROBOT, [Change("set", "drivetrain.gearing.left.ratio", "36:48")])
    assert 'ratio: "36:48"' in ratio  # plain YAML 1.1 would read 36:48 as 2208
    for word in ("yes", "null", "1.5", "on", "-", "a: b", "[x]", "# no"):
        assert check_text(apply(ROBOT, [Change("set", "name", word)]), "robot").config.name == word
    assert number(1e-05) == "1.0e-05" and number(6.0) == "6" and number(0.1) == "0.1"
    assert number(2.5e20) == "2.5e+20" and number(True) == "true"
    with pytest.raises(PatchError, match="isn't a number"):
        number(float("inf"))


def test_a_missing_key_is_added_with_a_value_of_any_kind():
    added = apply(ROBOT, [Change("set", "sensors[1].scale_error", 0.0025)])
    assert added.endswith("    port: 4   # the IMU\n    scale_error: 0.0025\n")
    section = apply(
        ROBOT, [Change("set", "mechanisms.lift", {"motors": [7, -8], "cartridge": "red"})]
    )
    assert section.endswith(
        "    port: 4   # the IMU\n\nmechanisms:\n  lift: {motors: [7, -8], cartridge: red}\n"
    )
    group = apply(
        ROBOT,
        [Change("set", "drivetrain.gearing.strafe", {"motors": [9], "cartridge": "blue"})],
    )
    assert diff(ROBOT, group) == ["+    strafe: {motors: [9], cartridge: blue}"]  # as its peers
    empty = apply(ROBOT + "mechanisms:\n", [Change("set", "mechanisms.intake", {"motors": [5]})])
    assert empty.endswith("mechanisms:\n  intake: {motors: [5]}\n")


def test_a_shape_replaces_a_footprint():
    shaped = apply(
        ROBOT,
        [
            Change("remove", "body.footprint_in"),
            Change("set", "body.shape", [{"type": "rect", "size_in": [18, 18]}]),
            Change("add", "body.shape", {"type": "circle", "pos_in": [-9, 0], "diameter_in": 6}),
        ],
    )
    assert diff(ROBOT, shaped) == [
        "-  footprint_in: [18, 18]   # square",
        "+  shape:",
        "+    - {type: rect, size_in: [18, 18]}",
        "+    - {type: circle, pos_in: [-9, 0], diameter_in: 6}",
    ]
    assert [i.location for i in check_text(shaped, "robot").issues] == ["body.shape"]  # 21 in


# --- list items ------------------------------------------------------------------------------


def test_list_items_are_added_in_their_neighbours_style():
    wheel = {"name": "lm", "pos_in": [0, 7], "type": "omni", "diameter_in": 3.25}
    assert diff(ROBOT, apply(ROBOT, [Change("add", "drivetrain.wheels", wheel)])) == [
        "+    - {name: lm, pos_in: [0, 7], type: omni, diameter_in: 3.25}",  # after rb
    ]
    rotation = {"type": "rotation", "port": 11, "tracking_wheel": {"pos_in": [0, -1.5]}}
    assert diff(ROBOT, apply(ROBOT, [Change("add", "sensors", rotation)])) == [
        "+  - type: rotation",  # the last sensor is a block: so is this one
        "+    port: 11",
        "+    tracking_wheel: {pos_in: [0, -1.5]}",
    ]
    motors = apply(ROBOT, [Change("add", "drivetrain.gearing.left.motors", 3)])
    assert "left: {motors: [1, 3], cartridge: blue" in motors


def test_a_list_is_made_where_there_was_none():
    bare = ROBOT.split("\n\nsensors:")[0] + "\n"
    made = apply(bare, [Change("add", "sensors", {"type": "imu", "port": 10})])
    assert made.endswith("rb]}\n\nsensors:\n  - {type: imu, port: 10}\n")  # a section apart
    for empty in ("sensors: []  # none yet\n", "sensors:\n"):
        text = bare + "\n" + empty
        made = apply(text, [Change("add", "sensors", {"type": "imu", "port": 10})])
        comment = "     # none yet" if "#" in empty else ""  # where it was
        assert made == bare + f"\nsensors:{comment}\n  - {{type: imu, port: 10}}\n"
        if comment:  # and back
            assert apply(made, [Change("remove", "sensors[0]")]) == text


def test_list_items_and_keys_are_removed_with_their_lines():
    block = apply(ROBOT, [Change("remove", "drivetrain.wheels[2]")])
    assert diff(ROBOT, block) == [
        "-    - name: rf",
        "-      pos_in: [5, -7]   # right side",
        "-      type: omni",
        "-      diameter_in: 3.25",
    ]
    flow = apply(ROBOT, [Change("remove", "drivetrain.wheels[3]")])
    assert diff(ROBOT, flow) == [
        "-    - {name: rb, pos_in: [-5, -7], type: omni, diameter_in: 3.25}"
    ]
    motor = apply(ROBOT, [Change("remove", "drivetrain.gearing.left.wheels[0]")])
    assert "left: {motors: [1], cartridge: blue, wheels: [lb]}" in motor
    key = apply(ROBOT, [Change("remove", "drivetrain.gearing.left.cartridge")])
    assert "left: {motors: [1], wheels: [lf, lb]}" in key
    last = apply(ROBOT, [Change("remove", "sensors[1]"), Change("remove", "sensors[0]")])
    assert last.endswith("sensors: []\n")
    with pytest.raises(PatchError, match="shares its line"):  # the first key of a block item
        apply(ROBOT, [Change("remove", "sensors[1].type")])


def test_a_key_is_renamed_where_it_is_written():
    renamed = apply(ROBOT, [Change("rename", "drivetrain.gearing.left", "port_side")])
    assert diff(ROBOT, renamed) == [
        "-    left: {motors: [1], cartridge: blue, wheels: [lf, lb]}",
        "+    port_side: {motors: [1], cartridge: blue, wheels: [lf, lb]}",
    ]
    with pytest.raises(PatchError, match="already a 'right'"):
        apply(ROBOT, [Change("rename", "drivetrain.gearing.left", "right")])


def test_what_cant_be_changed_says_why():
    anchored = ROBOT.replace("cg_in: [0, 0, 4]", "cg_in: &cg [0, 0, 4]") + "extra: *cg\n"
    with pytest.raises(PatchError, match="anchor"):
        apply(anchored, [Change("set", "body.cg_in", [1, 0, 4])])
    with pytest.raises(PatchError, match="isn't in the file"):
        apply(ROBOT, [Change("remove", "sensors[7]")])
    with pytest.raises(PatchError, match="isn't a list"):
        apply(ROBOT, [Change("add", "body.mass_kg", 1)])
    with pytest.raises(PatchError, match="doesn't read"):
        apply("body: [", [Change("set", "name", "x")])


def test_numbers_and_changes_go_together_and_line_endings_stay():
    both = apply(
        ROBOT, [Edit("sensors[0].pos_in", [8.625, 0]), Change("set", "sensors[0].noise", "harsh")]
    )
    assert diff(ROBOT, both) == [
        "-  - {type: distance, port: 3, pos_in: [8.5, 0], heading_deg: 0}  # front",
        "+  - {type: distance, port: 3, pos_in: [8.625, 0], heading_deg: 0, noise: harsh}  # front",
    ]
    crlf = ROBOT.replace("\n", "\r\n")
    changed = apply(
        crlf,
        [Change("add", "sensors", {"type": "gps", "port": 15}), Change("remove", "sensors[0]")],
    )
    assert "\n" not in changed.replace("\r\n", "")
    assert changed.endswith("# the IMU\r\n  - type: gps\r\n    port: 15\r\n")


def test_the_1239e_robot_keeps_its_comments_through_a_redesign():
    text = ROBOT_1239E.read_text(encoding="utf-8")
    changes = [
        Change("set", "name", "1239E, redesigned"),
        Change("set", "body.mass_kg", 7.25),
        Change("set", "drivetrain.gearing.left.cartridge", "green"),
        Change("add", "sensors", {"type": "gps", "port": 13, "pos_in": [0, -4]}),
        Change("set", "mechanisms.hood", {"motors": [14], "cartridge": "green"}),
    ]
    changed = apply(text, changes)
    assert comments(changed) == comments(text)  # every comment, in order
    assert diff(text, changed) == [
        "-name: 1239E 2026-27",
        '+name: "1239E, redesigned"',
        "-  mass_kg: 7.0                  # assumed",
        "+  mass_kg: 7.25                  # assumed",
        '-    left:  {motors: [10, 9],   cartridge: blue, ratio: "36:48", wheels: [lf, lm, lb]}',
        '+    left:  {motors: [10, 9],   cartridge: green, ratio: "36:48", wheels: [lf, lm, lb]}',
        "+  hood: {motors: [14], cartridge: green}",
        "+  - {type: gps, port: 13, pos_in: [0, -4]}",
    ]
    checked = check_text(changed, "robot")
    assert [i for i in checked.issues if i.severity == "error"] == []
    assert checked.config.sensors[-1].type == "gps" and "hood" in checked.config.mechanisms

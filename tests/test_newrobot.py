"""Phase 12.3: new robots (vexsim/app/newrobot.py) and the server's endpoints for the Design
view: a robot made from a template on a drive preset, or copied; a preset's drive put on a
robot that has a shape, inside it and on free ports; the YAML changed by the Design view's
forms, comments and all."""

import re
import shutil
from pathlib import Path

import pytest

from tests.test_ui import TOKEN, authorized
from vexsim.app.configs import PatchError, check_text
from vexsim.app.newrobot import PRESETS, create, drivetrain, file_name, preset_changes, robot_text
from vexsim.app.yamledit import Change, apply

ROOT = Path(__file__).resolve().parents[1]
ROBOT_1239E = ROOT / "examples" / "robots" / "1239e_2026-27.yaml"


def comments(text: str) -> list[str]:
    return re.findall(r"#.*", text)


def wheels_of(text: str) -> list[tuple[float, float]]:
    return [tuple(w.pos_in) for w in check_text(text, "robot").config.drivetrain.wheels]


# --- a new robot -------------------------------------------------------------------------------


def test_a_new_robot_is_a_rectangle_on_a_preset_drive_ready_to_draw_over():
    motors = {"tank4": 4, "tank6": 6, "xdrive": 4, "mecanum": 4, "hdrive": 5}
    for preset in PRESETS:
        text = robot_text("Bot #2: the sequel", preset)
        checked = check_text(text, "robot")
        assert checked.issues == [], preset  # nothing to fix before it drives
        robot = checked.config
        assert robot.name == "Bot #2: the sequel"
        assert robot.body.shape[0].size_in == (15, 15) and robot.body.footprint_in is None
        ports = sorted(abs(p) for g in robot.drivetrain.gearing.values() for p in g.motors)
        assert ports == list(range(1, motors[preset] + 1)), preset
        assert robot.mechanisms == {} and robot.sensors == ()
    assert "mechanisms: {}" in text and "sensors: []" in text  # ready for the forms to fill
    assert file_name("Test bot #2") == "test_bot_2.yaml" and file_name("###") == "robot.yaml"
    with pytest.raises(PatchError, match="no drive preset 'tank8'"):
        robot_text("Bot", "tank8")


def test_a_new_robot_is_written_where_no_file_is(tmp_path):
    made = tmp_path / "robots" / "new_bot.yaml"
    text = create(made, "New bot", "xdrive")
    assert made.read_text(encoding="utf-8") == text
    assert check_text(text, "robot").config.drivetrain.type == "xdrive"
    with pytest.raises(PatchError, match="already there"):
        create(made, "Another bot")
    assert made.read_text(encoding="utf-8") == text  # never over a file
    with pytest.raises(PatchError, match="isn't a YAML file name"):
        create(tmp_path / "bot.txt", "Bot")

    copied = create(tmp_path / "copy.yaml", "1239E, again", copy=ROBOT_1239E)
    original = ROBOT_1239E.read_text(encoding="utf-8")
    assert comments(copied) == comments(original)  # all of it but its name
    assert [
        a for a, b in zip(original.splitlines(), copied.splitlines(), strict=True) if a != b
    ] == ["name: 1239E 2026-27"]
    assert check_text(copied, "robot").config.name == "1239E, again"
    field = ROOT / "examples" / "fields" / "practice_elements.yaml"
    with pytest.raises(PatchError, match="isn't a robot config"):
        create(tmp_path / "field_copy.yaml", "Bot", copy=field)
    with pytest.raises(PatchError, match="isn't there to copy"):
        create(tmp_path / "gone_copy.yaml", "Bot", copy=tmp_path / "gone.yaml")


# --- drive presets -----------------------------------------------------------------------------


def shaped_robot() -> str:
    """The new robot, drawn on: a round intake at its front, a tapered tail behind, an
    intake motor on port 1 and an IMU on port 2."""
    return apply(
        robot_text("Shaped", "tank4"),
        [
            Change("add", "body.shape", {"type": "circle", "pos_in": [7.5, 0], "diameter_in": 5}),
            Change(
                "add",
                "body.shape",
                {"type": "outline", "points_in": [[-7.5, 5], [-11, 3], [-11, -3], [-7.5, -5]]},
            ),
            Change("set", "mechanisms.intake", {"motors": [1], "cartridge": "green"}),
            Change("add", "sensors", {"type": "imu", "port": 2, "pos_in": [-2, 2]}),
        ],
    )


def test_a_preset_drive_goes_on_the_robots_base_on_free_ports():
    text = shaped_robot()
    for preset in PRESETS:
        driven = apply(text, preset_changes(text, preset))
        checked = check_text(driven, "robot")
        assert [i for i in checked.issues if i.severity == "error"] == [], preset
        robot = checked.config
        assert robot.drivetrain.type == ("differential" if preset.startswith("tank") else preset)
        # on the 15 x 15 in base, not the box around the intake and the tail
        assert {abs(x) for x, _ in wheels_of(driven)} <= {0.0, 5.5}, preset
        ports = sorted(abs(p) for g in robot.drivetrain.gearing.values() for p in g.motors)
        assert ports[0] == 3, preset  # 1 and 2 are the intake's and the IMU's
        assert robot.mechanisms["intake"].motors == (1,) and robot.sensors[0].port == 2
        assert comments(driven) == comments(text), preset


def test_a_preset_drive_fits_inside_a_robot_that_isnt_a_box():
    # a round robot: its box's corners are off it, so the wheels come in until they're on it
    round_robot = robot_text("Round", "tank4").replace(
        "{type: rect, pos_in: [0, 0], size_in: [15, 15]}", "{type: circle, diameter_in: 16}"
    )
    driven = apply(round_robot, preset_changes(round_robot, "xdrive"))
    assert check_text(driven, "robot").issues == []
    assert all(x * x + y * y <= 7.5**2 for x, y in wheels_of(driven))
    # without a test of what's on the robot, the wheels go by the box alone
    assert drivetrain("tank4", (-8, -8, 8, 8), [1, 2, 3, 4])["wheels"][0]["pos_in"] == [6, 6.5]


def test_a_preset_says_why_it_cant_go_on():
    text = robot_text("Bot", "tank4")
    with pytest.raises(PatchError, match="no drive preset"):
        preset_changes(text, "tank8")
    with pytest.raises(PatchError, match="errors to fix"):
        preset_changes(text.replace("mass_kg: 6.5", "mass_kg: -1"), "tank6")
    sensors = [Change("add", "sensors", {"type": "imu", "port": p}) for p in range(1, 18)]
    crowded = apply(text, sensors)  # 17 ports taken: 4 free
    with pytest.raises(PatchError, match="needs 6 free ports"):
        preset_changes(crowded, "tank6")
    assert len(preset_changes(crowded, "tank4")) == 3


# --- the server --------------------------------------------------------------------------------


def test_the_server_makes_robots_and_changes_them_as_the_design_view_does(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    shutil.copy(ROBOT_1239E, tmp_path / "team.yaml")
    app = create_app(
        tmp_path, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as client:
        authorized(client)
        made = client.post("/api/config/new", json={"path": "robots/bot.yaml", "name": "Bot"})
        assert made.status_code == 200 and made.json() == {"path": "robots/bot.yaml"}
        opened = client.get("/api/config", params={"path": "robots/bot.yaml"}).json()
        assert opened["kind"] == "robot" and opened["check"]["issues"] == []
        again = client.post("/api/config/new", json={"path": "robots/bot.yaml", "name": "Bot"})
        assert again.status_code == 422 and "already there" in again.json()["detail"]
        outside = client.post("/api/config/new", json={"path": "../bot.yaml", "name": "Bot"})
        assert outside.status_code == 422
        copy = {"path": "team_copy.yaml", "name": "Team copy", "source": "team.yaml"}
        assert client.post("/api/config/new", json=copy).status_code == 200
        copied = (tmp_path / "team_copy.yaml").read_text(encoding="utf-8")
        assert "name: Team copy" in copied and comments(copied) == comments(
            ROBOT_1239E.read_text(encoding="utf-8")
        )

        # a six-motor drive, an IMU and a distance sensor, a mechanism (renamed)
        text = opened["text"]
        drive = client.post("/api/config/drive", json={"text": text, "preset": "tank6"}).json()
        assert len(drive["check"]["robot"]["drivetrain"]["wheels"]) == 6
        imu = {"type": "imu", "port": 7}
        distance = {"type": "distance", "port": 8, "pos_in": [7, 0]}
        edits = [
            {"location": "sensors", "op": "add", "value": imu},
            {"location": "sensors", "op": "add", "value": distance},
            {"location": "mechanisms.intake", "op": "set", "value": {"motors": [9],
                                                                     "cartridge": "green"}},
            {"location": "mechanisms.intake", "op": "rename", "value": "roller"},
            {"location": "body.mass_kg", "op": "set", "value": 7.25},
            {"location": "body.cg_in", "value": [0.5, 0, 3.5]},  # a number list, as dragged
        ]  # fmt: skip
        request = {"kind": "robot", "text": drive["text"], "edits": edits}
        patched = client.post("/api/config/patch", json=request).json()
        robot = patched["check"]["robot"]
        assert [s["type"] for s in robot["sensors"]] == ["imu", "distance"]
        assert robot["mechanisms"] == {"roller": {**robot["mechanisms"]["roller"], "motors": [9]}}
        assert robot["body"]["mass_kg"] == 7.25 and robot["body"]["cg_in"] == [0.5, 0, 3.5]
        assert patched["check"]["issues"] == []
        assert comments(patched["text"]) == comments(text)  # the template's, every one
        assert "mechanisms:                     # other motors" in patched["text"]  # in place

        # what can't be done says why
        bad = {**request, "edits": [{"location": "drivetrain.wheels[9]", "op": "remove"}]}
        refused = client.post("/api/config/patch", json=bad)
        assert refused.status_code == 422 and "isn't in the file" in refused.json()["detail"]
        words = {**request, "edits": [{"location": "name", "value": "words"}]}
        assert client.post("/api/config/patch", json=words).status_code == 422  # no op: numbers
        no_preset = client.post("/api/config/drive", json={"text": text, "preset": "tank8"})
        assert no_preset.status_code == 422 and "no drive preset" in no_preset.json()["detail"]

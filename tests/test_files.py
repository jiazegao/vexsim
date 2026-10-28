"""The workspace list's Duplicate and Delete (vexsim/app/files.py and the server): a copy
beside the file (a robot's or field's named as a copy, the rest of it as it was), never over
a file; only the workspace's own files, and no project's folder."""

import shutil
from pathlib import Path

import pytest

from tests.test_ui import TOKEN, authorized
from vexsim.app.files import duplicate

ROOT = Path(__file__).resolve().parents[1]
ROBOT = ROOT / "examples" / "robots" / "1239e_2026-27.yaml"
FIELD = ROOT / "examples" / "fields" / "practice_elements.yaml"


def test_a_robots_copy_is_named_as_one_with_the_rest_as_it_was(tmp_path):
    robot = tmp_path / "team.yaml"
    shutil.copy(ROBOT, robot)
    text = robot.read_text(encoding="utf-8")
    first = duplicate(robot, "robot")
    assert first.name == "team_copy.yaml"
    assert first.read_text(encoding="utf-8") == text.replace(
        "name: 1239E 2026-27", "name: 1239E 2026-27 (copy)"
    )
    second = duplicate(robot, "robot")  # never over the first
    assert second.name == "team_copy_2.yaml"
    assert "name: 1239E 2026-27 (copy 2)" in second.read_text(encoding="utf-8")
    assert duplicate(first, "robot").name == "team_copy_copy.yaml"

    field = tmp_path / "field.yaml"
    shutil.copy(FIELD, field)
    copied = duplicate(field, "field").read_text(encoding="utf-8")
    assert "(copy)" in copied and len(copied.splitlines()) == len(field.read_text().splitlines())


def test_a_copy_keeps_line_endings_and_a_byte_order_mark_and_other_files_are_copied_as_they_are(
    tmp_path,
):
    robot = tmp_path / "windows.yaml"
    raw = b"\xef\xbb\xbf" + ROBOT.read_bytes().replace(b"\n", b"\r\n")
    robot.write_bytes(raw)
    copied = duplicate(robot, "robot").read_bytes()
    assert copied.startswith(b"\xef\xbb\xbf") and b"\n" not in copied.replace(b"\r\n", b"")
    assert copied == raw.replace(b"name: 1239E 2026-27", b"name: 1239E 2026-27 (copy)")

    program = tmp_path / "auton.py"
    program.write_bytes(b"print('hi')\r\n")
    assert duplicate(program, "program").read_bytes() == b"print('hi')\r\n"
    nameless = tmp_path / "nameless.yaml"
    nameless.write_text(ROBOT.read_text().replace("name: 1239E 2026-27\n", ""))
    assert duplicate(nameless, "robot").read_bytes() == nameless.read_bytes()
    broken = tmp_path / "broken.yaml"
    broken.write_text("name: [unclosed\n")
    assert duplicate(broken, "invalid").read_text() == "name: [unclosed\n"


def test_the_server_duplicates_and_deletes_only_the_workspaces_files(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    shutil.copy(ROBOT, tmp_path / "team.yaml")
    shutil.copytree(ROOT / "examples" / "pros_projects" / "minimal_pros4", tmp_path / "project")
    (tmp_path / "notes.txt").write_text("not one of vexsim's files\n")
    app = create_app(
        tmp_path, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as client:
        authorized(client)
        made = client.post("/api/files/duplicate", json={"path": "team.yaml"})
        assert made.status_code == 200 and made.json() == {"path": "team_copy.yaml"}
        listed = {i["path"]: i for i in client.get("/api/workspace").json()["items"]}
        assert listed["team_copy.yaml"]["name"] == "1239E 2026-27 (copy)"

        assert client.delete("/api/files", params={"path": "team_copy.yaml"}).status_code == 204
        assert not (tmp_path / "team_copy.yaml").exists()
        for path, why in [
            ("notes.txt", "isn't one of the workspace's files"),
            ("../team.yaml", "isn't one of the workspace's files"),
            ("project", "PROS project's folder"),
            ("team_copy.yaml", "isn't one of the workspace's files"),  # gone already
        ]:
            refused = client.delete("/api/files", params={"path": path})
            assert refused.status_code == 422 and why in refused.json()["detail"], path
            copied = client.post("/api/files/duplicate", json={"path": path})
            assert copied.status_code == 422 and why in copied.json()["detail"], path
        assert (tmp_path / "notes.txt").exists() and (tmp_path / "project" / "src").is_dir()

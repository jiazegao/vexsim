"""A way in (phase 15.4): the starter program, and vexsim's own documents for the app's Guide
page."""

from pathlib import Path

import pytest

from tests.conftest import ROOT
from tests.test_ui import TOKEN, authorized
from vexsim.app import guide, newrobot, starter
from vexsim.app.runspec import RunSpec, check, program_factory, simulation_factory
from vexsim.app.workspace import Workspace
from vexsim.runtime.simulation import ScriptedInput

IN = 0.0254


def run(folder: Path, robot: str, mode: str, input_source=None, seconds: float = 60.0):
    """The starter program on a robot, headless: the simulation where it ended."""
    spec = RunSpec(robot=robot, program="programs/first_program.py", mode=mode)
    prepared = check(spec, folder)
    make, mode = program_factory(prepared, None)
    sim = simulation_factory(
        prepared, make, mode, input_source=input_source, echo=None, drawings=False
    )()
    while not sim.finished and sim.world.time < seconds:
        sim.world.step()
    return sim


# --- the starter program --------------------------------------------------------------------


@pytest.mark.parametrize("preset", list(newrobot.PRESETS))
def test_the_starter_program_runs_on_every_robot_the_app_makes(tmp_path, preset):
    starter.write_starter(tmp_path)
    newrobot.create(tmp_path / "robot.yaml", "First robot", preset)
    sim = run(tmp_path, "robot.yaml", "autonomous")
    try:
        assert sim.finished, sim.console  # a program that fails raises as it runs
        x, y = (float(v) / IN for v in sim.robot.cg_position[:2])
        if preset.startswith("tank"):  # its square brings it back
            assert "back at Pose(" in sim.console[-1]
            assert abs(x) < 5 and abs(y) < 5
            assert 5 < sim.world.time < 20
        else:  # a robot that can strafe: forward, then back
            assert "forward for a second, then back" in sim.console[-1]
            assert 0 < x < 30 and abs(y) < 1
    finally:
        sim.close()


@pytest.mark.parametrize("preset", ["tank4", "mecanum"])
def test_the_starter_program_drives_from_the_sticks(tmp_path, preset):
    starter.write_starter(tmp_path)
    newrobot.create(tmp_path / "robot.yaml", "First robot", preset)
    forward = ScriptedInput([(0.0, {"LEFT_Y": 100.0}, set())])
    sim = run(tmp_path, "robot.yaml", "driver", forward, seconds=4.0)
    try:
        x, y = (float(v) / IN for v in sim.robot.cg_position[:2])
        assert x > 20 and abs(y) < 2  # the left stick pushed up: forward
    finally:
        sim.close()


def test_the_starter_is_never_written_over_a_file(tmp_path):
    first = starter.write_starter(tmp_path)
    assert first == tmp_path / "programs" / "first_program.py"
    first.write_text("# mine now\n", encoding="utf-8")
    second = starter.write_starter(tmp_path)
    assert (
        second.name == "first_program_2.py" and first.read_text(encoding="utf-8") == "# mine now\n"
    )
    assert starter.write_starter(tmp_path).name == "first_program_3.py"
    text = second.read_text(encoding="utf-8")
    assert text == starter.PROGRAM and "\r" not in text
    listed = {item.path: item for item in Workspace(tmp_path).scan()}
    assert listed["programs/first_program_2.py"].detail == "Python: autonomous, opcontrol"


# --- the documents ----------------------------------------------------------------------------


def test_every_document_is_listed_once_and_is_there():
    found = guide.documents()
    assert [d.id for d in found][:2] == ["readme", "calibration_guide"]  # where a student starts
    assert len({d.id for d in found}) == len(found) == len(guide.listed())
    assert {d.path for d in found} == {
        "README.md",
        *(f"docs/{p.name}" for p in (ROOT / "docs").glob("*.md")),
    }
    for document in found:
        text = (ROOT / document.path).read_text(encoding="utf-8")
        assert text.startswith("# "), document.path
        assert document.title == text.splitlines()[0][2:].replace("`", "").strip()
        assert document.about
    same, text = guide.read("cpp")
    assert same.path == "docs/cpp.md" and text == (ROOT / "docs" / "cpp.md").read_text("utf-8")
    with pytest.raises(KeyError):
        guide.read("plan")  # the plan is for whoever works on vexsim


def test_only_the_documents_pictures_are_served():
    assert guide.picture("docs/img/ui_1239e.png") == ROOT / "docs" / "img" / "ui_1239e.png"
    for path in (
        "README.md",
        "docs/cpp.md",  # not a picture
        "docs/img/nothing.png",
        "docs/../pyproject.toml",
        "docs/img/../../vexsim/ui/static/icons/icon.svg",  # a picture, but not a document's
        "../etc/passwd",
        "/etc/passwd",
    ):
        with pytest.raises(ValueError):
            guide.picture(path)


def test_a_copy_installed_without_its_documents_has_none(tmp_path):
    assert guide.documents(tmp_path) == []
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("# Only this\n\ntext\n", encoding="utf-8")
    assert [(d.id, d.title) for d in guide.documents(tmp_path)] == [("readme", "Only this")]


# --- the server ---------------------------------------------------------------------------------


@pytest.fixture
def served(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    app = create_app(
        tmp_path, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as client:
        authorized(client)
        yield client


def test_the_server_writes_a_starter_program_into_the_folder(served, tmp_path):
    assert served.get("/api/workspace").json()["items"] == []
    made = served.post("/api/programs/starter")
    assert made.status_code == 200 and made.json() == {"path": "programs/first_program.py"}
    assert (tmp_path / "programs" / "first_program.py").read_text("utf-8") == starter.PROGRAM
    assert served.post("/api/programs/starter").json() == {"path": "programs/first_program_2.py"}
    items = served.get("/api/workspace", params={"fresh": True}).json()["items"]
    assert [(i["kind"], i["path"]) for i in items] == [
        ("program", "programs/first_program.py"),
        ("program", "programs/first_program_2.py"),
    ]


def test_the_server_serves_the_documents(served):
    index = served.get("/api/guide").json()
    assert index["available"] is True and index["repository"] == guide.REPOSITORY
    assert [d["id"] for d in index["documents"]] == [d.id for d in guide.documents()]
    readme = served.get("/api/guide/doc", params={"id": "readme"}).json()
    assert readme["document"] == index["documents"][0]
    assert readme["text"] == (ROOT / "README.md").read_text(encoding="utf-8")
    assert served.get("/api/guide/doc", params={"id": "nothing"}).status_code == 404
    picture = served.get("/api/guide/file", params={"path": "docs/img/ui_1239e.png"})
    assert picture.status_code == 200 and picture.headers["content-type"] == "image/png"
    assert picture.content == (ROOT / "docs" / "img" / "ui_1239e.png").read_bytes()
    for path in ("README.md", "docs/../pyproject.toml", "docs/img/nothing.png"):
        assert served.get("/api/guide/file", params={"path": path}).status_code == 404


def test_the_server_says_where_the_documents_are_when_it_has_none(served, monkeypatch):
    monkeypatch.setattr(guide, "root", lambda: None)
    index = served.get("/api/guide").json()
    assert index["available"] is False and index["repository"] == guide.REPOSITORY
    assert [(d["id"], d["path"]) for d in index["documents"]] == [
        (name, path) for name, path, _ in guide.listed()
    ]
    assert served.get("/api/guide/doc", params={"id": "readme"}).status_code == 404
    assert (
        served.get("/api/guide/file", params={"path": "docs/img/ui_1239e.png"}).status_code == 404
    )

"""Nothing stale (phase 15.3): Restart runs the code as it is now, a run says when its files
have changed, and a folder that hasn't changed isn't read again."""

import os
import shutil
import time
from pathlib import Path

import pytest

from tests.conftest import ROOT
from tests.test_ui import ROBOT, TOKEN, Messages, authorized, wait_for
from vexsim.app.runfiles import RunFiles, changed, run_files
from vexsim.app.runspec import RunSpec, check
from vexsim.app.workspace import RACY_S, Workspace

PROGRAM = """\
from helper import WORD
from vexsim.api import delay


def autonomous(bot):
    print("says", "{word}", WORD)
    while True:
        yield delay(100)
"""


@pytest.fixture(autouse=True)
def runs_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setenv("VEXSIM_RUNS_DIR", str(tmp_path / "recorded-runs"))
    monkeypatch.setenv("VEXSIM_CHILD_DUMP_S", "15")


def settle(*paths: Path, ago: float = 10.0) -> None:
    """Date files as written a while ago, so their stamps stand for them (RACY_S)."""
    then = time.time() - ago
    for path in paths:
        os.utime(path, (then, then))


def workspace(folder: Path, word: str = "one") -> Path:
    """A folder with a robot and a program that prints a word of its own and one of a
    module's beside it."""
    shutil.copy(ROOT / ROBOT, folder / "robot.yaml")
    (folder / "prog.py").write_text(PROGRAM.format(word=word), encoding="utf-8")
    (folder / "helper.py").write_text('WORD = "apple"\n', encoding="utf-8")
    settle(*folder.iterdir())
    return folder


@pytest.fixture
def served(tmp_path):
    """client: the server on a workspace of its own (``workspace``)."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    folder = tmp_path / "ws"  # beside where its runs are recorded, not around it
    folder.mkdir()
    workspace(folder)
    app = create_app(
        folder, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as client:
        authorized(client)
        client.folder = folder
        yield client


def said(client, session_id: str, text: str, timeout: float = 60.0) -> list[dict]:
    """Wait for the session's console to say ``text``; the messages up to then."""
    with client.websocket_connect(f"/api/sessions/{session_id}/ws") as socket:
        messages = Messages(socket)
        messages.until(
            lambda m: m["type"] == "console" and any(text in line for line in m["lines"]), timeout
        )
        return messages.seen


# --- a run's files ------------------------------------------------------------------------


def test_a_runs_files_are_its_configs_and_its_program(tmp_path):
    folder = workspace(tmp_path)
    prepared = check(RunSpec(robot="robot.yaml", program="prog.py"), folder)
    files = run_files(prepared)
    assert sorted(p.name for p in files.files) == ["prog.py", "robot.yaml"]
    assert files.project is None
    before = files.stamp()
    assert changed(before, files.stamp()) == []
    (folder / "prog.py").write_text(PROGRAM.format(word="two"), encoding="utf-8")
    assert [Path(p).name for p in changed(before, files.stamp())] == ["prog.py"]
    (folder / "robot.yaml").unlink()  # gone is a change too
    assert [Path(p).name for p in changed(before, files.stamp())] == ["prog.py", "robot.yaml"]


def test_a_projects_files_are_whatever_its_build_reads(tmp_path):
    project = tmp_path / "bot"
    shutil.copytree(ROOT / "examples" / "pros_projects" / "minimal_pros4", project)
    (project / "include" / "pros").mkdir(parents=True, exist_ok=True)
    (project / "include" / "pros" / "motors.hpp").write_text("// the SDK's\n", encoding="utf-8")
    files = RunFiles([], project)
    before = files.stamp()
    names = {Path(p).relative_to(project).as_posix() for p in before}
    assert {"project.pros", "src/main.cpp"} <= names
    assert "include/pros/motors.hpp" not in names  # the build uses vexsim's own
    (project / "src" / "extra.cpp").write_text("int extra = 1;\n", encoding="utf-8")  # a new file
    (project / "include" / "pros" / "motors.hpp").write_text("// changed\n", encoding="utf-8")
    assert [Path(p).name for p in changed(before, files.stamp())] == ["extra.cpp"]


# --- Restart ------------------------------------------------------------------------------


def test_restart_runs_the_program_as_it_is_now(served):
    client, folder = served, served.folder
    spec = {"robot": "robot.yaml", "program": "prog.py"}
    first = client.post("/api/sessions", json={"spec": spec}).json()
    said(client, first["id"], "says one apple")

    # nothing changed: the same session starts again at once, in its own worker
    session = client.app.state.server.sessions[first["id"]]
    run = session.run_id
    again = client.post(f"/api/sessions/{first['id']}/restart").json()
    assert again["id"] == first["id"]
    wait_for(lambda: session.run_id != run and session.state == "running")

    # the program edited: checked and started afresh, in the old one's place
    (folder / "prog.py").write_text(PROGRAM.format(word="two"), encoding="utf-8")
    second = client.post(f"/api/sessions/{first['id']}/restart").json()
    assert second["id"] != first["id"] and second["spec"] == first["spec"]
    said(client, second["id"], "says two apple")
    assert client.get(f"/api/sessions/{first['id']}").json()["state"] == "stopped"

    # a module it imports edited: that's the run's code too
    (folder / "helper.py").write_text('WORD = "pear"\n', encoding="utf-8")
    third = client.post(f"/api/sessions/{second['id']}/restart").json()
    assert third["id"] != second["id"]
    said(client, third["id"], "says two pear")

    # a stopped run starts again too
    client.delete(f"/api/sessions/{third['id']}")
    fourth = client.post(f"/api/sessions/{third['id']}/restart").json()
    assert fourth["id"] != third["id"]
    said(client, fourth["id"], "says two pear")
    client.delete(f"/api/sessions/{fourth['id']}")
    assert client.post("/api/sessions/s99/restart").status_code == 404


def test_restart_says_why_it_cant_and_leaves_the_run_there(served):
    client, folder = served, served.folder
    spec = {"robot": "robot.yaml", "program": "prog.py"}
    first = client.post("/api/sessions", json={"spec": spec}).json()
    said(client, first["id"], "says one apple")
    (folder / "robot.yaml").write_text("name: no drivetrain\n", encoding="utf-8")
    response = client.post(f"/api/sessions/{first['id']}/restart")
    assert response.status_code == 422
    assert "invalid robot config" in response.json()["error"]
    assert client.get(f"/api/sessions/{first['id']}").json()["state"] == "running"
    client.delete(f"/api/sessions/{first['id']}")


def test_a_program_that_doesnt_load_is_watched_and_runs_once_mended(served):
    client, folder = served, served.folder
    (folder / "prog.py").write_text("def autonomous(bot)\n    pass\n", encoding="utf-8")  # no colon
    spec = {"robot": "robot.yaml", "program": "prog.py"}
    first = client.post("/api/sessions", json={"spec": spec}).json()
    with client.websocket_connect(f"/api/sessions/{first['id']}/ws") as socket:
        messages = Messages(socket)
        error = messages.until(lambda m: m["type"] == "error")
        assert "SyntaxError" in error["message"]
        (folder / "prog.py").write_text(PROGRAM.format(word="mended"), encoding="utf-8")
        told = messages.until(lambda m: m["type"] == "changed", 10)
        assert told["files"] == ["prog.py"]
    second = client.post(f"/api/sessions/{first['id']}/restart").json()
    assert second["id"] != first["id"]
    said(client, second["id"], "says mended apple")
    client.delete(f"/api/sessions/{second['id']}")


def test_restart_builds_a_project_that_changed(tmp_path, in_cache):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    project = tmp_path / "bot"
    shutil.copytree(ROOT / "examples" / "pros_projects" / "minimal_pros4", project)
    main_cpp = project / "src" / "main.cpp"
    source = main_cpp.read_text(encoding="utf-8")
    at = source.index("{", source.index("void autonomous()")) + 1
    main_cpp.write_text(source[:at] + '\n\tprintf("first build\\n");' + source[at:], "utf-8")
    shutil.copy(ROOT / ROBOT, tmp_path / "robot.yaml")
    app = create_app(
        tmp_path, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with in_cache(), TestClient(app) as client:
        authorized(client)
        spec = {"robot": "robot.yaml", "program": "bot", "mode": "autonomous"}
        first = client.post("/api/sessions", json={"spec": spec}).json()
        said(client, first["id"], "first build", 300)
        again = client.post(f"/api/sessions/{first['id']}/restart").json()
        assert again["id"] == first["id"]  # nothing to build

        main_cpp.write_text(
            source[:at] + '\n\tprintf("second build\\n");' + source[at:], encoding="utf-8"
        )
        second = client.post(f"/api/sessions/{first['id']}/restart").json()
        assert second["id"] != first["id"] and second["state"] == "building"
        seen = said(client, second["id"], "second build", 300)
        assert any(m["type"] == "build" for m in seen)  # it was compiled again
        client.delete(f"/api/sessions/{second['id']}")


# --- "code changed" -------------------------------------------------------------------------


def test_a_run_says_when_its_files_change_while_a_page_shows_it(served):
    client, folder = served, served.folder
    spec = {"robot": "robot.yaml", "program": "prog.py"}
    first = client.post("/api/sessions", json={"spec": spec}).json()
    with client.websocket_connect(f"/api/sessions/{first['id']}/ws") as socket:
        messages = Messages(socket)
        messages.until(lambda m: m["type"] == "frame" and m["t"] > 0.2)
        time.sleep(1.6)  # three looks: nothing changed, nothing said
        (folder / "notes.txt").write_text("not the run's\n", encoding="utf-8")
        (folder / "helper.py").write_text('WORD = "plum"\n', encoding="utf-8")
        told = messages.until(lambda m: m["type"] == "changed", 10)
        assert told["files"] == ["helper.py"]  # the module it imported, by its workspace name
        assert not [m for m in messages.seen if m["type"] == "changed" and m is not told]
        (folder / "robot.yaml").write_text(
            (ROOT / ROBOT).read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8"
        )
        more = messages.until(lambda m: m["type"] == "changed" and m is not told, 10)
        assert more["files"] == ["helper.py", "robot.yaml"]
    # a page that opens it later hears so too
    with client.websocket_connect(f"/api/sessions/{first['id']}/ws") as socket:
        late = Messages(socket).until(lambda m: m["type"] == "changed", 10)
        assert late["files"] == ["helper.py", "robot.yaml"]
    client.delete(f"/api/sessions/{first['id']}")


# --- the workspace list -----------------------------------------------------------------------


def test_a_folder_that_hasnt_changed_isnt_read_again(tmp_path):
    folder = workspace(tmp_path)
    ws = Workspace(folder)
    first = ws.scan()
    assert [item.path for item in first] == ["robot.yaml", "prog.py"]
    assert ws.scan() == first and ws.scans == 1  # answered from the scan before
    assert ws.stamp() == ws.stamp() and ws.stamp().settled

    shutil.copy(ROOT / ROBOT, folder / "other.yaml")  # a new file
    settle(folder / "other.yaml")
    assert [item.path for item in ws.scan()] == ["other.yaml", "robot.yaml", "prog.py"]
    assert ws.scans == 2

    (folder / "robot.yaml").write_text("name: no drivetrain\n", encoding="utf-8")  # just written
    assert not ws.stamp().settled
    for count in (3, 4):  # its stamp doesn't stand for it yet: read every time
        assert [item.path for item in ws.scan()] == ["other.yaml", "prog.py"]
        assert ws.scans == count
    settle(folder / "robot.yaml", ago=RACY_S + 1)
    ws.scan()
    assert ws.scan() and ws.scans == 5
    assert ws.scan(fresh=True) and ws.scans == 6  # Refresh reads it whatever the stamp says


def test_the_stamp_covers_a_projects_routes_and_what_theyre_checked_against(tmp_path):
    project = tmp_path / "bot"
    shutil.copytree(ROOT / "examples" / "pros_projects" / "1239e_2026-27", project)
    for path in project.rglob("*"):
        if path.is_file():
            settle(path)
    ws = Workspace(tmp_path)
    before = ws.stamp()
    assert before.settled
    header = project / "include" / "custom" / "util_funcs.hpp"
    for edited in (project / "routes" / "left_start.yaml", header):
        text = edited.read_text(encoding="utf-8")
        edited.write_text(text + "\n", encoding="utf-8")
        settle(edited, ago=5)
        after = ws.stamp()
        assert after.digest != before.digest, edited.name
        before = after
    source = project / "src" / "main.cpp"  # not what a scan reads
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    settle(source, ago=5)
    assert ws.stamp().digest == before.digest


def test_the_server_answers_from_the_stamp_when_nothing_changed(served):
    client, folder = served, served.folder
    ws = client.app.state.server.workspace
    first = client.get("/api/workspace").json()
    assert first["stamp"] and [i["path"] for i in first["items"]] == ["robot.yaml", "prog.py"]
    scans = ws.scans
    same = client.get("/api/workspace", params={"unless": first["stamp"]}).json()
    assert same == {"unchanged": True, "stamp": first["stamp"]} and ws.scans == scans

    shutil.copy(ROOT / ROBOT, folder / "other.yaml")
    settle(folder / "other.yaml")
    second = client.get("/api/workspace", params={"unless": first["stamp"]}).json()
    assert [i["path"] for i in second["items"]] == ["other.yaml", "robot.yaml", "prog.py"]
    assert second["stamp"] not in ("", first["stamp"])

    # the saved runs' file is part of it: the page reads them with the list
    (folder / ".vexsim").mkdir()
    (folder / ".vexsim" / "launch.yaml").write_text("configurations: []\n", encoding="utf-8")
    settle(folder / ".vexsim" / "launch.yaml")
    third = client.get("/api/workspace", params={"unless": second["stamp"]}).json()
    assert third["stamp"] not in ("", second["stamp"]) and third["items"] == second["items"]

    # a file just written: no stamp to ask again with, so the next answer is read afresh
    (folder / "prog.py").write_text(PROGRAM.format(word="new"), encoding="utf-8")
    racy = client.get("/api/workspace", params={"unless": third["stamp"]}).json()
    assert racy["stamp"] == "" and len(racy["items"]) == 3
    scans = ws.scans
    fresh = client.get("/api/workspace", params={"fresh": True}).json()
    assert len(fresh["items"]) == 3 and ws.scans == scans + 1

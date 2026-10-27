"""The UI's services and server (vexsim/app, vexsim/ui): run specs, the workspace, jobs,
live sessions in worker processes, the HTTP/WebSocket API and the generated protocol."""

import json
import shutil
import sys
import time

import pytest
from pydantic import TypeAdapter

from tests.conftest import ROOT
from vexsim.app.jobs import JobManager
from vexsim.app.runspec import RunError, RunSpec, check, quote_arg
from vexsim.app.session import Session
from vexsim.app.workspace import Workspace
from vexsim.cli import build_parser, main
from vexsim.ui.protocol import ServerMessage, typescript

ROBOT = "examples/robots/full_omni_6m.yaml"
TOUR = "examples/programs/tour.py"
MESSAGES = TypeAdapter(ServerMessage)


def wait_for(predicate, timeout=20.0, interval=0.05):
    """Wait until predicate() is true; fail after ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout} s")


# --- run specs ----------------------------------------------------------------------------


def test_run_spec_round_trips_vexsim_run():
    argv = ["run", ROBOT, "--program", TOUR, "--field", "f.yaml", "--start=-12,3.5,90"]
    argv += ["--seed", "4", "--noise", "ideal", "--mode", "driver"]
    argv += ["--env", "VEXSIM_AUTON=Left 40", "--env", "X=1"]
    spec = RunSpec.from_args(build_parser().parse_args(argv))
    assert spec.start == (-12, 3.5, 90) and spec.env == {"VEXSIM_AUTON": "Left 40", "X": "1"}
    again = RunSpec.from_args(build_parser().parse_args(spec.to_args()))
    assert again == spec
    assert spec.command_line() == (
        "vexsim run examples/robots/full_omni_6m.yaml --program examples/programs/tour.py "
        "--field f.yaml --mode driver --start=-12,3.5,90 --seed 4 --noise ideal "
        '--env "VEXSIM_AUTON=Left 40" --env X=1'
    )
    assert RunSpec(robot="r.yaml").to_args() == ["run", "r.yaml"]  # defaults left out
    assert quote_arg('say "hi" now') == '"say \\"hi\\" now"'


def test_check_names_files_as_the_spec_does(tmp_path):
    with pytest.raises(RunError) as error:
        check(RunSpec(robot="nope.yaml"), tmp_path)
    assert error.value.message == "nope.yaml: invalid robot config"
    assert error.value.issues[0].message == "file not found"
    with pytest.raises(RunError, match="program not found: missing.py"):
        check(RunSpec(robot=ROBOT, program="missing.py"), ROOT)
    (tmp_path / "field.yaml").write_text("version: 1\nsize_in: [144, -3]\n")
    with pytest.raises(RunError) as error:
        check(RunSpec(robot=str(ROOT / ROBOT), field="field.yaml"), tmp_path)
    assert error.value.message == "field.yaml: invalid field config" and error.value.issues

    prepared = check(RunSpec(robot=ROBOT, program="examples/pros_projects/minimal_pros4"), ROOT)
    assert prepared.project == ROOT / "examples" / "pros_projects" / "minimal_pros4"
    pros = "examples/pros_projects/minimal_pros4/project.pros"
    assert check(RunSpec(robot=ROBOT, program=pros), ROOT).project == prepared.project
    assert check(RunSpec(robot=ROBOT, program=TOUR), ROOT).program_file == ROOT / TOUR


# --- the workspace --------------------------------------------------------------------------


def test_workspace_finds_what_vexsim_can_use(tmp_path):
    examples = ROOT / "examples"
    (tmp_path / "robots").mkdir()
    shutil.copy(examples / "robots" / "full_omni_6m.yaml", tmp_path / "robots")
    shutil.copy(examples / "fields" / "practice_elements.yaml", tmp_path)
    shutil.copy(examples / "programs" / "tour.py", tmp_path)
    shutil.copy(examples / "scenarios" / "s_curve.yaml", tmp_path)
    shutil.copy(examples / "inputs" / "strafe_square.csv", tmp_path)
    shutil.copytree(examples / "pros_projects" / "minimal_pros4", tmp_path / "minimal")
    (tmp_path / "run.csv").write_text("time_s,phase,x_in,y_in,heading_deg,est_x_in\n0,a,0,0,0,0\n")
    (tmp_path / "broken.yaml").write_text("drivetrain: [unclosed\n")
    (tmp_path / "notes.yaml").write_text("anything: else\n")  # not a vexsim config
    (tmp_path / "helper.py").write_text("def helper():\n    pass\n")  # not a program
    for hidden in ("node_modules", ".git"):
        (tmp_path / hidden).mkdir()
        shutil.copy(examples / "robots" / "mecanum_4m.yaml", tmp_path / hidden)

    workspace = Workspace(tmp_path)
    found = {(i.kind, i.path): i for i in workspace.scan()}
    assert set(found) == {
        ("robot", "robots/full_omni_6m.yaml"),
        ("field", "practice_elements.yaml"),
        ("program", "tour.py"),
        ("project", "minimal"),
        ("scenario", "s_curve.yaml"),
        ("input", "strafe_square.csv"),
        ("log", "run.csv"),
        ("invalid", "broken.yaml"),
    }
    assert found[("robot", "robots/full_omni_6m.yaml")].detail == "differential, 6 drive motors"
    assert found[("program", "tour.py")].detail == "Python: autonomous, opcontrol"
    assert found[("invalid", "broken.yaml")].problem
    assert (
        workspace.path("robots/full_omni_6m.yaml")
        == tmp_path.resolve() / "robots" / "full_omni_6m.yaml"
    )
    with pytest.raises(ValueError, match="outside the workspace"):
        workspace.path("../elsewhere.yaml")


# --- jobs -----------------------------------------------------------------------------------


def test_jobs_run_in_their_own_processes():
    jobs = JobManager()
    heard = []
    jobs.add_listener(lambda event, job, line: heard.append((event, job.id, line)))
    job = jobs.submit("echo", {"lines": ["one", "two"], "sleep_s": 0.3, "result": 7}, key="k")
    assert jobs.submit("echo", {}, key="k") is job  # the same key joins the running job
    assert jobs.wait(job, 30)
    assert (job.state, job.log, job.result) == ("succeeded", ["one", "two"], {"echo": 7})
    assert ("log", job.id, "two") in heard and ("state", job.id, None) in heard
    failed = jobs.submit("echo", {"fail": "it broke"})
    assert jobs.wait(failed, 30) and (failed.state, failed.error) == ("failed", "it broke")
    slow = jobs.submit("echo", {"sleep_s": 60})
    wait_for(lambda: slow.state == "running")
    jobs.cancel(slow)
    assert jobs.wait(slow, 30) and slow.state == "cancelled"


# --- live sessions --------------------------------------------------------------------------


class Recorder:
    def __init__(self):
        self.messages = []

    def __call__(self, session, seq, message):
        self.messages.append((seq, message))

    def of(self, kind):
        return [m for _, m in self.messages if m["type"] == kind]


def test_a_session_runs_a_python_program_in_its_own_process():
    heard = Recorder()
    session = Session("s1", RunSpec(robot=ROBOT, program=TOUR), base=ROOT, listener=heard)
    session.start()
    try:
        wait_for(lambda: session.frame is not None and session.frame["t"] > 0.5)
        assert session.state == "running" and session.scene["robot"]["name"]
        session.command({"cmd": "pause"})
        wait_for(lambda: session.state == "paused")
        frozen = session.frame["t"]
        time.sleep(0.3)
        assert session.frame["t"] == frozen
        session.command({"cmd": "step", "ms": 50})
        wait_for(lambda: session.frame["t"] > frozen)
        assert session.frame["t"] == pytest.approx(frozen + 0.05)
        session.command({"cmd": "speed", "value": 0})  # as fast as possible
        session.command({"cmd": "resume"})
        wait_for(lambda: session.frame["t"] > 10)
        session.command({"cmd": "restart"})
        wait_for(lambda: len(heard.of("scene")) == 2)
        # the restart's console starts empty, then the program runs from the start again
        wait_for(lambda: any("autonomous start" in line for line in session.console))
        kinds = [m["type"] for _, m in heard.messages]
        restarted = len(kinds) - kinds[::-1].index("scene")
        assert next(m for _, m in heard.messages[restarted:] if m["type"] == "frame")["t"] < 1
        caught_up, last = session.catch_up()
        assert caught_up[0]["type"] == "session" and last == session.seq
    finally:
        session.stop()
    assert session.state == "stopped" and not session.child.alive
    seqs = [seq for seq, _ in heard.messages]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    for _, message in heard.messages:
        MESSAGES.validate_python(message)  # every message matches the protocol


def test_a_session_reports_a_program_that_fails(tmp_path):
    (tmp_path / "bad.py").write_text("def autonomous(bot):\n    yield\n\n1 / 0\n")
    shutil.copy(ROOT / ROBOT, tmp_path / "robot.yaml")
    session = Session("s2", RunSpec(robot="robot.yaml", program="bad.py"), base=tmp_path)
    session.start()
    try:
        wait_for(lambda: session.state == "error")
        assert "ZeroDivisionError" in session.message
        assert "1 / 0" in session.error["traceback"]
    finally:
        session.stop()


def test_a_session_stops_a_program_that_never_yields(tmp_path):
    stuck = "def autonomous(bot):\n    while True:\n        pass\n    yield\n"
    (tmp_path / "stuck.py").write_text(stuck)
    shutil.copy(ROOT / ROBOT, tmp_path / "robot.yaml")
    session = Session("s3", RunSpec(robot="robot.yaml", program="stuck.py"), base=tmp_path)
    session.start()
    wait_for(lambda: session.frame is not None and session.frame["t"] > 1.5)
    time.sleep(1.0)  # autonomous starts at 2 s and never gives the simulation back
    stuck_at = session.frame["t"]
    time.sleep(0.3)
    assert session.frame["t"] == stuck_at < 2.1
    started = time.monotonic()
    session.stop(timeout=1.0)  # it can't hear "stop": killed after the timeout
    assert 0.9 <= time.monotonic() - started < 5  # (Windows clocks tick every 15.6 ms)
    assert session.state == "stopped" and not session.child.alive


def test_protocol_typescript_is_current():
    path = ROOT / "frontend" / "src" / "protocol.ts"
    assert path.read_text(encoding="utf-8") == typescript(), (
        "regenerate it: python -m vexsim.ui.protocol frontend/src/protocol.ts"
    )


# --- the server -----------------------------------------------------------------------------

TOKEN = "test-token"


@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    app = create_app(
        ROOT, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as test_client:
        yield test_client


def authorized(client):
    response = client.get(f"/api/info?token={TOKEN}")
    assert response.status_code == 200
    assert "vexsim_token_8642" in response.headers["set-cookie"]
    return client


def test_the_server_needs_its_token(client):
    assert client.get("/api/info").status_code == 401
    page = client.get("/", headers={"accept": "text/html"})
    assert page.status_code == 401 and "needs its key" in page.text
    assert client.get("/api/info?token=wrong").status_code == 401
    bearer = {"authorization": f"Bearer {TOKEN}"}
    assert client.get("/api/info", headers=bearer).status_code == 200
    authorized(client)
    assert client.get("/api/info").status_code == 200  # the cookie
    assert client.get("/api/info", headers={"host": "evil.example"}).status_code == 403
    from starlette.websockets import WebSocketDisconnect

    evil = {"origin": "http://evil.example"}  # a WebSocket from another site's page
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/api/sessions/s1/ws", headers=evil):
            pass
    assert refused.value.code == 4403


def test_the_server_lists_the_workspace_and_serves_the_app(client):
    authorized(client)
    info = client.get("/api/info").json()
    assert info["workspace"] == str(ROOT)
    items = client.get("/api/workspace").json()["items"]
    assert {"kind": "robot", "path": ROBOT} in [
        {"kind": i["kind"], "path": i["path"]} for i in items
    ]
    page = client.get("/")
    assert page.status_code == 200 and '<div id="root">' in page.text


def test_the_server_says_why_a_run_cant_start(client):
    authorized(client)
    response = client.post("/api/sessions", json={"spec": {"robot": "examples/robots/nope.yaml"}})
    assert response.status_code == 422
    assert response.json() == {
        "error": "examples/robots/nope.yaml: invalid robot config",
        "issues": [{"severity": "error", "location": "", "message": "file not found"}],
    }
    response = client.post("/api/sessions", json={"spec": {"robot": "../outside.yaml"}})
    assert response.status_code == 422 and "outside the workspace" in response.json()["error"]


def receive_until(socket, predicate, limit=5000):
    for _ in range(limit):
        message = json.loads(socket.receive_text())
        if predicate(message):
            return message
    raise AssertionError("never came")


def test_the_server_streams_a_session_and_takes_commands(client):
    authorized(client)
    response = client.post("/api/sessions", json={"spec": {"robot": ROBOT, "program": TOUR}})
    assert response.status_code == 200
    session = response.json()
    assert session["command"] == f"vexsim run {ROBOT} --program {TOUR}"
    with client.websocket_connect(f"/api/sessions/{session['id']}/ws") as socket:
        first = json.loads(socket.receive_text())
        assert first["type"] == "session" and first["session"]["id"] == session["id"]
        receive_until(socket, lambda m: m["type"] == "frame" and m["t"] > 0.5)
        socket.send_json({"cmd": "pause"})
        receive_until(socket, lambda m: m["type"] == "status" and m["state"] == "paused")
        socket.send_json({"cmd": "jump"})
        error = receive_until(socket, lambda m: m["type"] == "error")
        assert error["message"].startswith("bad command")
    assert client.delete(f"/api/sessions/{session['id']}").status_code == 204
    assert client.get(f"/api/sessions/{session['id']}").json()["state"] == "stopped"


def test_the_server_builds_a_pros_project_then_runs_it(client, in_cache):
    authorized(client)
    spec = {"robot": ROBOT, "program": "examples/pros_projects/minimal_pros4", "start": [0, 0, 90]}
    with in_cache():
        response = client.post("/api/sessions", json={"spec": spec})
        assert response.status_code == 200 and response.json()["state"] == "building"
        session_id = response.json()["id"]
        with client.websocket_connect(f"/api/sessions/{session_id}/ws") as socket:
            frame = receive_until(socket, lambda m: m["type"] == "frame" and m["t"] > 2.5, 20000)
        assert frame["estimate"] is not None  # the program reports its own pose
    jobs = client.get("/api/jobs").json()
    assert [(j["title"], j["state"]) for j in jobs] == [("Build minimal_pros4", "succeeded")]
    client.delete(f"/api/sessions/{session_id}")


def test_vexsim_ui_needs_a_folder(capsys):
    assert main(["ui", "no/such/folder"]) == 1
    assert "is not a folder" in capsys.readouterr().out


def test_vexsim_ui_says_how_to_install_what_it_needs(monkeypatch, capsys):
    monkeypatch.delitem(sys.modules, "vexsim.ui.server", raising=False)
    monkeypatch.setitem(sys.modules, "fastapi", None)  # as if it weren't installed
    assert main(["ui", str(ROOT), "--no-browser"]) == 1
    assert 'the UI needs fastapi; install it with: pip install -e ".[ui]"' in (
        capsys.readouterr().out
    )

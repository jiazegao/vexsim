"""The UI's services and server (vexsim/app, vexsim/ui): run specs, the workspace, jobs,
live sessions in worker processes, the HTTP/WebSocket API and the generated protocol."""

import json
import queue
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from tests.conftest import ROOT
from vexsim.app import runs
from vexsim.app.jobs import JobManager
from vexsim.app.launch import (
    LaunchFileError,
    RunConfiguration,
    read_configurations,
    write_configurations,
)
from vexsim.app.runspec import RunError, RunSpec, check, quote_arg
from vexsim.app.session import Session
from vexsim.app.workspace import Workspace
from vexsim.cli import build_parser, main
from vexsim.ui.protocol import ServerMessage, Tape, Telemetry, typescript

ROBOT = "examples/robots/full_omni_6m.yaml"
TOUR = "examples/programs/tour.py"
PRACTICE = "examples/fields/practice_elements.yaml"
MESSAGES = TypeAdapter(ServerMessage)


@pytest.fixture(autouse=True)
def runs_elsewhere(tmp_path, monkeypatch):
    """Runs these tests start are recorded in a temporary folder, not the repository's
    .vexsim/runs (worker processes inherit the variable). A worker or job process that's
    still going after 15 s prints where it is, which a failed test's message shows."""
    monkeypatch.setenv("VEXSIM_RUNS_DIR", str(tmp_path / "recorded-runs"))
    monkeypatch.setenv("VEXSIM_CHILD_DUMP_S", "15")


def wait_for(predicate, timeout=20.0, interval=0.05, about=None):
    """Wait until predicate() is true; fail after ``timeout`` seconds, saying ``about()``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout} s" + (f"; {about()}" if about else ""))


def doing(session) -> str:
    """What a session was doing, for a failed test's message."""
    console = "\n".join(list(session.console)[-80:])
    return f"state {session.state!r} ({session.message}); its console:\n{console}"


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


def test_check_warns_when_the_robot_starts_on_an_obstacle(capsys):
    def start_warnings(start):
        prepared = check(RunSpec(robot=ROBOT, field=PRACTICE, start=start), ROOT)
        return [w.message for w in prepared.warnings if w.location == "start"]

    assert start_warnings((0, 0, 0)) == ["the robot starts on top of barrier; move its start"]
    assert start_warnings((-48, 48, 45)) == ["the robot starts on top of red goal; move its start"]
    outside = "the robot starts partly outside the walls; move its start in"
    assert start_warnings((70, 0, 0)) == [outside]
    assert start_warnings((-48, -24, 0)) == []
    assert start_warnings((0, 9, 0)) == []  # half its 15 in width + the barrier's 1.5: touching
    robot, field = str(ROOT / ROBOT), str(ROOT / PRACTICE)
    assert main(["run", robot, "--field", field, "--headless", "--seconds", "0.05"]) == 0
    assert "warning: the robot starts on top of barrier" in capsys.readouterr().out


# --- saved runs ---------------------------------------------------------------------------


def test_run_configurations_round_trip_through_launch_yaml(tmp_path):
    assert read_configurations(tmp_path) == []
    saved = [
        RunConfiguration(
            name="Left 40", robot="r.yaml", program="p", start=(60, 0, 0), env={"A": "Left 40"}
        ),
        RunConfiguration(name="Drive", robot="r.yaml", mode="driver", start=(-12.5, 3, 90)),
    ]
    path = write_configurations(tmp_path, saved)
    assert path == tmp_path / ".vexsim" / "launch.yaml"
    text = path.read_text(encoding="utf-8")
    assert "start: [60, 0, 0]" in text and "env: {A: Left 40}" in text
    assert "start: [-12.5, 3, 90]" in text and "seed" not in text  # defaults left out
    assert read_configurations(tmp_path) == saved
    with pytest.raises(LaunchFileError, match="two run configurations are named 'drive'"):
        write_configurations(tmp_path, [*saved, RunConfiguration(name="drive", robot="r.yaml")])
    path.write_text("configurations:\n  - {name: x}\n", encoding="utf-8")
    with pytest.raises(LaunchFileError, match=r"configuration 1 \(x\): robot: Field required"):
        read_configurations(tmp_path)
    path.write_text("configurations: [unclosed\n", encoding="utf-8")
    with pytest.raises(LaunchFileError, match="launch.yaml"):
        read_configurations(tmp_path)


def test_the_example_run_configurations_check_out():
    configurations = read_configurations(ROOT)
    names = {c.name for c in configurations}
    assert {"Drive: full omni", "Tour (Python)", "1239E: Left 40", "1239E: driver"} <= names
    for configuration in configurations:
        prepared = check(configuration, ROOT)  # its files are there and its configs load
        assert not [w for w in prepared.warnings if w.location == "start"], configuration.name


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
        wait_for(
            lambda: session.frame is not None and session.frame["t"] > 0.5,
            about=lambda: doing(session),
        )
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
        wait_for(lambda: session.state == "error", about=lambda: doing(session))
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
    wait_for(
        lambda: session.frame is not None and session.frame["t"] > 1.5, about=lambda: doing(session)
    )
    time.sleep(1.0)  # autonomous starts at 2 s and never gives the simulation back
    stuck_at = session.frame["t"]
    time.sleep(0.3)
    assert session.frame["t"] == stuck_at < 2.1
    started = time.monotonic()
    session.stop(timeout=1.0)  # it can't hear "stop": killed after the timeout
    assert 0.9 <= time.monotonic() - started < 5  # (Windows clocks tick every 15.6 ms)
    assert session.state == "stopped" and not session.child.alive


def test_a_session_takes_the_controller_and_times_a_match():
    heard = Recorder()
    spec = RunSpec(robot=ROBOT, field=PRACTICE, mode="match", start=(-48, -24, 0))
    session = Session("s4", spec, base=ROOT, listener=heard)
    session.start()
    try:
        wait_for(
            lambda: session.frame is not None and session.frame["phase"] == "autonomous",
            about=lambda: doing(session),
        )
        left = session.frame["period_left"]
        assert 0 < left <= 15
        session.command({"cmd": "speed", "value": 0})
        wait_for(lambda: session.frame["phase"] == "opcontrol")
        assert 100 < session.frame["period_left"] <= 105
        session.command({"cmd": "speed", "value": 1})
        session.command({"cmd": "input", "analog": {"LEFT_Y": 127}, "digital": ["L1", "A"]})
        wait_for(lambda: session.frame["controller"]["analog"]["LEFT_Y"] == 127)
        assert session.frame["controller"]["digital"] == ["A", "L1"]
        wait_for(lambda: session.frame["pose"][0] > -40)  # driven forward, along +x
        frame = session.frame
        assert len(frame["wheels"][0]) == 5 and frame["imu"] and frame["mechanisms"] == []
    finally:
        session.stop()
    scene = heard.of("scene")[0]
    assert {o["name"] for o in scene["field"]["obstacles"]} == {"barrier", "red goal", "blue goal"}
    for _, message in heard.messages:
        MESSAGES.validate_python(message)


def test_a_session_warns_when_its_robot_starts_on_an_obstacle():
    session = Session("s5", RunSpec(robot=ROBOT, field=PRACTICE), base=ROOT)
    session.start()
    try:
        wait_for(
            lambda: any("starts on top of barrier" in line for line in session.console),
            about=lambda: doing(session),
        )
    finally:
        session.stop()


# --- recorded runs --------------------------------------------------------------------------


def tour_workspace(folder: Path) -> Path:
    """A workspace with a robot, the tour, and an empty field: the tour's own."""
    shutil.copy(ROOT / ROBOT, folder / "robot.yaml")
    shutil.copy(ROOT / TOUR, folder / "tour.py")
    return folder


def test_every_run_is_recorded(tmp_path):
    workspace = tour_workspace(tmp_path)
    heard = Recorder()
    spec = RunSpec(robot="robot.yaml", program="tour.py")
    session = Session("s6", spec, base=workspace, listener=heard, name="The tour")
    session.start()
    try:
        session.command({"cmd": "speed", "value": 0})  # as fast as possible
        # it finished, and was written
        wait_for(lambda: heard.of("recorded"), timeout=60, about=lambda: doing(session))
        first = heard.of("recorded")[0]["run"]
        assert first["ended"] == "finished" and first["name"] == "The tour"
        assert first["id"] == heard.of("scene")[0]["run_id"] == session.info()["run_id"]
        session.command({"cmd": "restart"})
        wait_for(lambda: session.frame is not None and session.frame["t"] > 1)
    finally:
        session.stop()
    wait_for(lambda: len(heard.of("recorded")) == 2)
    second = heard.of("recorded")[1]["run"]
    assert second["ended"] == "stopped" and second["id"] != first["id"]

    root = runs.runs_root(workspace)
    assert [r.id for r in runs.list_runs(root)] == [second["id"], first["id"]]  # newest first
    record = runs.read_record(root, first["id"])
    assert record.duration > 10 and record.pose_error.final_in < 3
    assert record.command == "vexsim run robot.yaml --program tour.py"
    folder = root / first["id"]
    assert {p.name for p in folder.iterdir()} == {
        "run.json",
        "tape.json.gz",
        "telemetry.csv.gz",
        "console.txt",
        "sd",
    }
    tape = Tape.model_validate(runs.read_tape(root, first["id"]))
    times = [s.t for s in tape.samples]
    assert times[0] == 0 and times[-1] == record.duration and len(times) == record.samples
    assert all(0.04 < b - a < 0.06 for a, b in zip(times[:-2], times[1:-1], strict=True))
    assert tape.scene.run_id == first["id"] and tape.events.overlay  # the tour's motions
    assert "autonomous start" in (folder / "console.txt").read_text(encoding="utf-8")
    plots = Telemetry.model_validate(runs.telemetry_columns(folder / "telemetry.csv.gz"))
    assert len(plots.columns["time_s"]) == len(plots.columns["error_in"]) > 1000
    assert [name for _, name in plots.phases] == ["initialize", "autonomous"]
    assert main(["plot", str(folder / "telemetry.csv.gz"), "--out", str(tmp_path / "p.png")]) == 0


def test_old_runs_go_unless_kept(tmp_path):
    root = tmp_path / "runs"
    base = {"spec": RunSpec(robot="r.yaml"), "command": "vexsim run r.yaml", "mode": "driver"}
    base |= {"robot": "r", "field": "f", "duration": 1.0, "ended": "stopped", "message": None}
    for i in range(5):
        record = runs.RunRecord(
            id=f"20261027-00000{i}-000{i}",
            name=f"run {i}",
            created=1000.0 + i,
            pose_error=None,
            samples=1,
            kept=i == 0,
            **base,
        )
        (root / record.id).mkdir(parents=True)
        runs._write_record(root / record.id, record)
    assert runs.prune(root, keep=2) == ["20261027-000002-0002", "20261027-000001-0001"]
    assert [r.name for r in runs.list_runs(root)] == ["run 4", "run 3", "run 0"]  # 0 is kept
    with pytest.raises(ValueError, match="no run"):
        runs.run_dir(root, "../elsewhere")


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


def test_the_server_previews_a_robot_and_field(client):
    authorized(client)
    preview = client.post("/api/preview", json={"robot": ROBOT, "field": PRACTICE}).json()
    assert preview["robot"]["footprint"] == [15.0, 15.0] and len(preview["robot"]["wheels"]) == 6
    assert {o["name"] for o in preview["field"]["obstacles"]} == {
        "barrier",
        "red goal",
        "blue goal",
    }
    assert len(preview["pieces"]) == 6 and preview["pieces"][0] == [-24.0, 24.0]
    empty = client.post("/api/preview", json={"robot": ROBOT}).json()
    assert empty["field"]["size"] == [144.0, 144.0] and empty["pieces"] == []
    assert client.post("/api/preview", json={"robot": "nope.yaml"}).status_code == 422
    outside = client.post("/api/preview", json={"robot": "../x.yaml"})
    assert outside.status_code == 422 and "outside the workspace" in outside.json()["error"]


def test_the_server_keeps_run_configurations(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    app = create_app(
        tmp_path, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    launch = tmp_path / ".vexsim" / "launch.yaml"
    with TestClient(app) as client:
        authorized(client)
        empty = {"file": ".vexsim/launch.yaml", "configurations": [], "error": None}
        assert client.get("/api/configurations").json() == empty
        left = {"name": "Left 40", "robot": "robot.yaml", "start": [60, 0, 0], "env": {"A": "1"}}
        saved = client.put("/api/configurations", json={"configurations": [left]}).json()
        assert [c["name"] for c in saved["configurations"]] == ["Left 40"] and launch.is_file()
        twice = client.put("/api/configurations", json={"configurations": [left, left]})
        assert twice.status_code == 422 and "named 'Left 40'" in twice.json()["detail"]
        launch.write_text("configurations: [unclosed\n", encoding="utf-8")
        broken = client.get("/api/configurations").json()
        assert broken["configurations"] == [] and "launch.yaml" in broken["error"]
        refused = client.put("/api/configurations", json={"configurations": [left]})
        assert refused.status_code == 409  # someone's broken file isn't overwritten
        assert launch.read_text(encoding="utf-8") == "configurations: [unclosed\n"


class Messages:
    """A test WebSocket's messages, read in the background, so a test that waits for one
    fails (and says what came instead) rather than hangs."""

    def __init__(self, socket):
        self.queue: queue.Queue = queue.Queue()
        self.seen: list[dict] = []
        threading.Thread(target=self._pump, args=(socket,), daemon=True).start()

    def _pump(self, socket) -> None:
        try:
            while True:
                self.queue.put(json.loads(socket.receive_text()))
        except Exception as exc:  # the socket closed
            self.queue.put(exc)

    def until(self, predicate, timeout: float = 90.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            try:
                item = self.queue.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty:
                raise AssertionError(f"not within {timeout} s; lately: {self.lately()}") from None
            if isinstance(item, Exception):
                raise AssertionError(f"the socket closed ({item!r}); lately: {self.lately()}")
            self.seen.append(item)
            if predicate(item):
                return item

    def lately(self) -> list[str]:
        """The last few messages, and the last lines of output (they may say where a worker
        or a build is stuck)."""

        def brief(m: dict) -> str:
            detail = {k: m[k] for k in ("state", "message", "t") if k in m}
            return f"{m['type']} {detail}"[:300]

        printed = ("console", "build")
        output = [line for m in self.seen if m["type"] in printed for line in m["lines"]]
        recent = [brief(m) for m in self.seen if m["type"] not in printed][-8:]
        return recent + (["output:\n" + "\n".join(output[-80:])] if output else [])


def test_the_server_streams_a_session_and_takes_commands(client):
    authorized(client)
    response = client.post("/api/sessions", json={"spec": {"robot": ROBOT, "program": TOUR}})
    assert response.status_code == 200
    session = response.json()
    assert session["command"] == f"vexsim run {ROBOT} --program {TOUR}"
    with client.websocket_connect(f"/api/sessions/{session['id']}/ws") as socket:
        messages = Messages(socket)
        first = messages.until(lambda m: True)
        assert first["type"] == "session" and first["session"]["id"] == session["id"]
        messages.until(lambda m: m["type"] == "frame" and m["t"] > 0.5)
        socket.send_json({"cmd": "pause"})
        messages.until(lambda m: m["type"] == "status" and m["state"] == "paused")
        socket.send_json({"cmd": "jump"})
        error = messages.until(lambda m: m["type"] == "error")
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
            frame = Messages(socket).until(lambda m: m["type"] == "frame" and m["t"] > 2.5, 300)
        assert frame["estimate"] is not None  # the program reports its own pose
    jobs = client.get("/api/jobs").json()
    assert [(j["title"], j["state"]) for j in jobs] == [("Build minimal_pros4", "succeeded")]
    client.delete(f"/api/sessions/{session_id}")


def test_a_failed_build_says_where(tmp_path, in_cache):
    """The browser's Problems tab reads file:line:col from this message."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    project = tmp_path / "bot"
    shutil.copytree(ROOT / "examples" / "pros_projects" / "minimal_pros4", project)
    main_cpp = project / "src" / "main.cpp"
    lines = main_cpp.read_text(encoding="utf-8").splitlines(keepends=True)
    at = next(i for i, line in enumerate(lines) if "void autonomous()" in line) + 1
    lines.insert(at, "\tdrive_in_circles(3);\n")  # not declared anywhere
    main_cpp.write_text("".join(lines), encoding="utf-8")
    shutil.copy(ROOT / ROBOT, tmp_path / "robot.yaml")
    app = create_app(
        tmp_path, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with in_cache(), TestClient(app) as client:
        authorized(client)
        spec = {"robot": "robot.yaml", "program": "bot"}
        session_id = client.post("/api/sessions", json={"spec": spec}).json()["id"]
        with client.websocket_connect(f"/api/sessions/{session_id}/ws") as socket:
            error = Messages(socket).until(lambda m: m["type"] == "error", 300)
    line = next(t for t in error["message"].splitlines() if "error:" in t and "drive_in" in t)
    path = Path(line.split(f":{at + 1}:")[0])  # the project's own file, not a build copy
    assert path.is_absolute() and path.parts[-3:] == ("bot", "src", "main.cpp")


def test_the_server_serves_recorded_runs(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    workspace = tour_workspace(tmp_path)
    app = create_app(
        workspace, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as client:
        authorized(client)
        spec = {"robot": "robot.yaml", "program": "tour.py"}
        started = client.post("/api/sessions", json={"spec": spec, "name": "Tour"}).json()
        with client.websocket_connect(f"/api/sessions/{started['id']}/ws") as socket:
            messages = Messages(socket)
            socket.send_json({"cmd": "speed", "value": 0})
            recorded = messages.until(lambda m: m["type"] == "recorded")["run"]
        run_id = recorded["id"]
        assert [r["id"] for r in client.get("/api/runs").json()] == [run_id]
        details = client.get(f"/api/runs/{run_id}").json()
        assert details["run"]["name"] == "Tour" and details["console"]
        tape = client.get(f"/api/runs/{run_id}/tape", headers={"accept-encoding": "gzip"})
        assert tape.headers["content-encoding"] == "gzip"
        assert len(tape.json()["samples"]) == recorded["samples"]
        plots = client.get(f"/api/runs/{run_id}/telemetry").json()
        assert "error_in" in plots["columns"]
        csv = client.get(f"/api/runs/{run_id}/telemetry.csv")
        assert csv.text.startswith("time_s,phase,x_in,y_in,heading_deg")
        kept = client.patch(f"/api/runs/{run_id}", json={"kept": True, "name": "Best"}).json()
        assert kept["kept"] is True and kept["name"] == "Best"
        assert client.get("/api/runs/..%2Fescape/tape").status_code == 404
        assert client.delete(f"/api/runs/{run_id}").status_code == 204
        assert client.get("/api/runs").json() == []
        assert client.get(f"/api/runs/{run_id}").status_code == 404

        # a telemetry log in the workspace opens as a replay
        robot, log = str(workspace / "robot.yaml"), str(workspace / "log.csv")
        argv = ["run", robot, "--program", str(workspace / "tour.py"), "--headless"]
        assert main([*argv, "--seconds", "4", "--record", log]) == 0
        replay = client.post("/api/replay", json={"log": "log.csv", "robot": "robot.yaml"})
        body = replay.json()
        Tape.model_validate(body["tape"])
        assert body["name"] == "log.csv (replay)" and len(body["tape"]["samples"]) == 80
        assert body["tape"]["scene"]["command"] == "vexsim replay robot.yaml log.csv"
        assert body["telemetry"]["columns"]["time_s"][-1] == pytest.approx(4.0, abs=0.02)
        not_a_log = client.post("/api/replay", json={"log": "tour.py", "robot": "robot.yaml"})
        assert not_a_log.status_code == 422


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

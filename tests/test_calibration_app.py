"""Phase 14.7: a calibration session in the app. Robot logs on the field (their tapes), the
workspace's sessions and format-2 logs, the session's services (each run's result, collecting,
leaving runs out, applying a fit, the pass marks, tape marks read as typed), a USB listener that
stops when asked, and the endpoints. The whole session, through the server (plan, practice,
fit, apply), is marked ``session``."""

import json
import math
import sys
import time
from pathlib import Path

import pytest

from tests.conftest import ROOT
from vexsim.app import calsession
from vexsim.app.jobs import JobManager
from vexsim.app.logtape import LogTapeError, robot_log_tape
from vexsim.app.workspace import Workspace
from vexsim.calibration.log import RobotLog
from vexsim.calibration.session import Session
from vexsim.config import load_field, load_robot

ROBOT = "examples/robots/1239e_2026-27.yaml"
FIELD = "examples/fields/1239e_2026-27.yaml"
CONFIG, FIELD_CONFIG = load_robot(ROOT / ROBOT), load_field(ROOT / FIELD)
TOKEN = "test-token"


@pytest.fixture(autouse=True)
def elsewhere(tmp_path, monkeypatch):
    """Runs and results go to a temporary folder, not the repository's .vexsim."""
    monkeypatch.setenv("VEXSIM_RUNS_DIR", str(tmp_path / "recorded-runs"))
    monkeypatch.setenv("VEXSIM_RESULTS_DIR", str(tmp_path / "results"))


def routine_log(path: Path, seconds: float = 2.0) -> Path:
    """A routine's log, as 1239E's code writes one: LemLib's pose driving +x from (10, 0)
    (theta 90: facing +x), MCL's beside it, and the front-left distance sensor reading 500 mm."""
    rows = []
    for k in range(int(seconds * 100)):
        t = k * 10.0
        x = 10 + 20 * t / 1000
        reading = 500.0 if k < seconds * 100 - 1 else float("nan")  # the last: nothing in range
        rows.append([t, 12000, x, 0.0, 90.0, x + 0.5, 0.2, 91.0, reading, 0.0])
    names = [
        "time_ms",
        "battery_mv",
        "pose_lemlib_x_in",
        "pose_lemlib_y_in",
        "pose_lemlib_theta_deg",
    ]
    names += ["pose_mcl_x_in", "pose_mcl_y_in", "pose_mcl_theta_deg", "d1_mm", "imu16_deg"]
    return RobotLog.from_rows(names, rows, {"name": "Left 40", "mode": "autonomous"}).write(path)


def calibration_log(path: Path, test: str, run: int = 1, **info) -> Path:
    """A calibration program's log of a test: the drive's motors turning ``turn`` degrees
    forward (both sides alike: straight), the IMU still, the info its program writes."""
    turn = float(info.pop("turn", 0.0))
    rows = []
    for k in range(101):
        t, f = k * 10.0, k / 100
        left, right = turn * f, turn * f
        rows.append([t, 12000, left, left, right, right, 600.0, 600.0, -600.0, -600.0, 0.0])
    names = ["time_ms", "battery_mv", "m10_deg", "m9_deg", "m19_deg", "m17_deg"]
    names += ["m10_rpm", "m9_rpm", "m19_rpm", "m17_rpm", "imu16_deg"]
    # the robot's right side runs reversed (ports -19, -17): its raw degrees go the other way
    for row in rows:
        row[4], row[5] = -row[4], -row[5]
    meta = {"robot": CONFIG.name, "program": "vexsim calibration", "test": test, "run": str(run)}
    meta.update({"ended": "finished", **{k: str(v) for k, v in info.items()}})
    return RobotLog.from_rows(names, rows, meta).write(path)


# --- robot logs on the field ------------------------------------------------------------------


def test_a_routines_log_plays_its_codes_pose_with_rays_and_other_poses(tmp_path):
    tape = robot_log_tape(routine_log(tmp_path / "left40.csv"), "left40.csv", CONFIG)
    assert tape["kind"] == "robot" and tape["name"] == "Left 40"
    assert tape["summary"]["pose"] == "lemlib" and tape["summary"]["poses"] == ["lemlib", "mcl"]
    assert tape["summary"]["routine"] == "Left 40"
    x, y, heading = tape["estimate"][0]
    assert (x, y) == pytest.approx((10.0, 0.0)) and heading == pytest.approx(0.0)  # facing +x
    assert tape["times"][0] == 0 and tape["times"][-1] == pytest.approx(1.99)
    layers = tape["drawings"][0][1]
    assert sorted(layers) == ["poses", "rays"]
    # the front-left sensor (port 1) at (4.66, 5.69) on the robot, facing forward, read 500 mm
    seen = [s for s in layers["rays"] if s[0] == "line" and s[5] == "yellow"]
    assert len(seen) == 1
    _, x1, y1, x2, y2, _ = seen[0]
    assert (x1, y1) == pytest.approx((10 + 4.656, 5.694), abs=0.01)
    assert (x2 - x1, y2 - y1) == pytest.approx((500 / 25.4, 0.0), abs=0.01)
    # only the sensors it logged are drawn; one that read nothing, as a short muted ray
    assert len(layers["rays"]) == 2  # its ray, and the point it read
    last = tape["drawings"][-1][1]["rays"]
    assert [s[0] for s in last] == ["line"] and last[0][5] == "muted"
    assert layers["poses"] == [["pose", 10.5, 0.2, -1.0, "violet"]]  # MCL's, theta 91
    # MCL's path beside it, a point a frame
    (path,) = tape["paths"]
    assert (path["name"], path["color"], path["first"]) == ("mcl", "violet", 0)
    assert len(path["xs"]) == len(path["ys"]) == len(tape["times"])
    assert (path["xs"][0], path["ys"][0], path["xs"][-1]) == pytest.approx((10.5, 0.2, 50.3))


def test_another_poses_path_starts_at_its_first_reading_and_waits_through_gaps(tmp_path):
    nan = float("nan")
    names = ["time_ms", "pose_a_x_in", "pose_a_y_in", "pose_a_theta_deg"]
    names += ["pose_b_x_in", "pose_b_y_in", "pose_b_theta_deg"]
    rows = [[0, 0.0, 0, 90, nan, nan, nan], [10, 0.2, 0, 90, 5, 5, 0]]
    rows += [[20, 0.4, 0, 90, nan, nan, nan], [30, 0.6, 0, 90, 7, 6, 0]]
    log = RobotLog.from_rows(names, rows, {"name": "r"}).write(tmp_path / "r.csv")
    (path,) = robot_log_tape(log, "r.csv", None)["paths"]
    assert path["first"] == 1 and path["xs"] == [5, 5, 7] and path["ys"] == [5, 5, 6]


def test_a_calibration_log_plays_from_its_spot_by_odometry(tmp_path):
    # both sides forward 1000 motor degrees: the wheels roll pi * 3.25 * 0.75 * 1000/360 in
    log = calibration_log(
        tmp_path / "straight.csv", "straight", spot="-20.00 10.00 90.0", turn=1000
    )
    tape = robot_log_tape(log, "straight.csv", CONFIG)
    assert tape["summary"]["pose"] == "odometry" and tape["summary"]["routine"] is None
    assert tape["estimate"][0] == [-20.0, 10.0, 90.0]
    rolled = math.pi * 3.25 * 0.75 * 1000 / 360
    x, y, heading = tape["estimate"][-1]
    assert (x, y) == pytest.approx((-20.0, 10.0 + rolled), abs=0.05)  # facing +y, straight on
    assert heading == pytest.approx(90.0)


def test_a_log_that_goes_nowhere_on_the_field_says_so(tmp_path):
    log = calibration_log(tmp_path / "free_spin.csv", "free_spin")
    with pytest.raises(LogTapeError, match=r"its test \(free spin\) doesn't start on a spot"):
        robot_log_tape(log, "free_spin.csv", CONFIG)
    spotted = calibration_log(tmp_path / "push.csv", "push", spot="0 0 0")
    with pytest.raises(LogTapeError, match="pick the robot it ran on"):
        robot_log_tape(spotted, "push.csv", None)


# --- the workspace ----------------------------------------------------------------------------


def test_the_workspace_lists_format_2_logs_and_sessions_not_their_runs(tmp_path):
    (tmp_path / "card").mkdir()
    routine_log(tmp_path / "card" / "vexsim_0001_left_40.csv")
    session = Session.open(tmp_path / "sessions" / "2026-11-07")
    calibration_log(tmp_path / "card" / "vexsim_0002_straight.csv", "straight", run=2, spot="0 0 0")
    calsession.collect_logs(session.folder, tmp_path / "card")
    found = {(i.kind, i.path, i.detail) for i in Workspace(tmp_path).scan()}
    assert ("robotlog", "card/vexsim_0001_left_40.csv", "robot log: Left 40") in found
    assert (
        "robotlog",
        "card/vexsim_0002_straight.csv",
        "calibration log: straight, run 2",
    ) in found
    assert (
        "calsession",
        "sessions/2026-11-07",
        f"calibration session: 1 run of {CONFIG.name}",
    ) in found
    assert not any("sessions/2026-11-07/runs" in path for _, path, _ in found)  # the session's


# --- the session's services -------------------------------------------------------------------


def test_each_run_says_what_it_measured(tmp_path):
    session = Session.open(tmp_path / "s")
    card = tmp_path / "card"
    card.mkdir()
    calibration_log(card / "vexsim_0001_push_forward.csv", "push", length_in="96.0", turn=4500)
    calibration_log(card / "vexsim_0002_straight.csv", "straight", spot="0 0 0", turn=1000)
    collected = calsession.collect_logs(session.folder, card)
    assert collected["added"] == 2 and collected["card"] == str(card)
    state = calsession.session_state(tmp_path, session.folder, CONFIG)
    results = {r["test"]: r["result"] for r in state["runs"]}
    wheels = 4500 / 360 * math.pi * 3.25 * 0.75
    assert results["push"] == (
        f"the wheels say {wheels:.1f} in for 96 in: {abs(wheels / 96 - 1) * 100:.1f}% less"
    )
    speed = 600 * math.pi * 3.25 * 0.75 / 60
    assert results["straight"] == f"1.0 s, wheels up to {speed:.0f} in/s, turned 0 deg"
    calsession.set_use(session.folder, "vexsim_0002_straight.csv", False)
    assert not Session.open(session.folder).runs[1].use
    with pytest.raises(ValueError, match="no run"):
        calsession.set_use(session.folder, "nothing.csv", True)


def test_practice_and_real_runs_dont_mix(tmp_path):
    card = tmp_path / "card"
    card.mkdir()
    calibration_log(card / "vexsim_0001_straight.csv", "straight", spot="0 0 0")
    practice = Session.open(tmp_path / "practice")
    practice.practice = True
    practice.save()
    with pytest.raises(ValueError, match="practice session"):
        calsession.collect_logs(practice.folder, card)
    assert Session.open(practice.folder).practice  # it says so in session.yaml
    with pytest.raises(ValueError, match="no logs in"):
        calsession.collect_logs(tmp_path / "real", tmp_path)


def test_applying_a_fit_writes_its_changes_into_the_config_it_was_fitted_to(tmp_path):
    text = (ROOT / ROBOT).read_text(encoding="utf-8")
    folder = tmp_path / "2026-11-07"
    with pytest.raises(ValueError, match="hasn't been fitted"):
        calsession.apply_session(folder, text)
    (folder / "report").mkdir(parents=True)
    report = {
        "config_digest": calsession.digest(text),
        "fitted": "2026-11-07",
        "changes": [
            {"location": 'overrides["motor.voltage_cap"]', "value": 1.0, "key": "x"},
            {"location": "drivetrain.wheels[0].diameter_in", "value": 3.2, "key": "y"},
        ],
    }
    (folder / "report" / "report.json").write_text(json.dumps(report), encoding="utf-8")
    applied, count = calsession.apply_session(folder, text)
    assert count == 2 and "# Calibrated from session 2026-11-07 on " in applied
    assert (ROOT / ROBOT).read_text(encoding="utf-8") == text  # the file stays as it was
    assert "voltage_cap: 1" in applied and "diameter_in: 3.2}" in applied
    with pytest.raises(ValueError, match="has changed since"):
        calsession.apply_session(folder, text + "# edited\n")


def test_the_pass_marks_are_the_teams_once_saved(tmp_path):
    marks = calsession.pass_marks(tmp_path)
    assert (marks["max_distance_in"], marks["max_heading_deg"]) == (2.0, 2.0)
    saved = calsession.save_marks(tmp_path, 2.0, 4.0)
    assert saved["max_heading_deg"] == 4.0 and "calibration.yaml" in saved["source"]
    file = tmp_path / ".vexsim" / "calibration.yaml"
    assert "max_heading_deg: 4.0" in file.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="above 0"):
        calsession.save_marks(tmp_path, 0.0, 4.0)
    # the team's own file, changed in place: its comments and other keys stay
    file.write_text(
        "# the coach's\nmax_distance_in: 2  # in\nmax_heading_deg: 4\nnote: x\n", "utf-8"
    )
    calsession.save_marks(tmp_path, 1.5, 3.0)
    text = file.read_text(encoding="utf-8")
    assert text == "# the coach's\nmax_distance_in: 1.5  # in\nmax_heading_deg: 3\nnote: x\n"


def test_tape_marks_read_as_typed():
    found = calsession.end_found(
        CONFIG, FIELD_CONFIG, "FL: 27.25 from +x, 56.5 from +y; BR: 19.75 from +x, 39.25 from +y"
    )
    assert (found["x"], found["y"], found["heading"]) == pytest.approx(
        (46.7, 22.33, 204.7), abs=0.05
    )
    assert found["corners"] == ["front-left", "back-right"] and found["warning"] is None
    with pytest.raises(ValueError, match="one x wall and one y"):
        calsession.end_found(CONFIG, FIELD_CONFIG, "front-left: 27.25 from +x")


# --- listening over USB -----------------------------------------------------------------------


def test_listening_over_usb_stops_when_asked_and_keeps_its_logs(tmp_path):
    log = calibration_log(tmp_path / "log.csv", "straight", spot="0 0 0").read_text()
    script = tmp_path / "terminal.py"  # a brain's terminal: one log, then it waits
    script.write_text(
        "import sys, time\n"
        f"print('#vexsim-log begin')\nsys.stdout.write({log!r})\nprint('#vexsim-log end')\n"
        "sys.stdout.flush()\ntime.sleep(600)\n",
        encoding="utf-8",
    )
    jobs = JobManager()
    command = [sys.executable, str(script)]
    job = jobs.submit("calibration_usb", {"session": str(tmp_path / "s"), "command": command})
    deadline = time.monotonic() + 60
    while not any("straight, run 1" in line for line in job.log):
        assert time.monotonic() < deadline, job.log
        time.sleep(0.1)
    jobs.cancel(job)  # asked to stop: it finishes, with what it has
    assert jobs.wait(job, 30)
    assert job.state == "succeeded" and job.result["added"] == 1, (job.state, job.error)
    assert [r.test for r in Session.open(tmp_path / "s").runs] == ["straight"]


# --- through the server -----------------------------------------------------------------------


@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    app = create_app(
        ROOT, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as test_client:
        test_client.headers["authorization"] = f"Bearer {TOKEN}"
        yield test_client


def test_the_server_plays_robot_logs_and_reads_tape_marks(client):
    # the quick fit's routine logs no pose: not an error, but nothing to play (it's for a fit)
    found = client.get("/api/robotlog", params={"path": "examples/logs/full_omni_routine.csv"})
    assert found.status_code == 200 and found.json()["kind"] == "none", found.text
    assert "nothing to play" in found.json()["why"]
    missing = client.get("/api/robotlog", params={"path": "examples/logs/no_such_log.csv"})
    assert missing.status_code == 422
    end = client.post(
        "/api/calibration/end",
        json={"robot": ROBOT, "field": FIELD, "text": "FL -x 30 +y 40, BR -x 44 +y 52.5"},
    ).json()
    assert end["corners"] == ["front-left", "back-right"] and math.isfinite(end["heading"])
    bad = client.post("/api/calibration/end", json={"robot": ROBOT, "field": FIELD, "text": "x"})
    assert bad.status_code == 422
    marks = client.get("/api/calibration/marks").json()
    assert marks["max_distance_in"] > 0 and marks["source"]
    missing = client.get("/api/calibration/program", params={"folder": "examples/nothing_here"})
    assert missing.json() == {
        "folder": "examples/nothing_here",
        "exists": False,
        "pros_project": False,
        "written": False,
        "plan": None,
    }
    image = client.get("/api/image", params={"path": "docs/img/guide/map_push.png"})
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert client.get("/api/image", params={"path": "README.md"}).status_code == 404
    assert client.get("/api/image", params={"path": "../outside.png"}).status_code == 404


def test_the_server_starts_calibration_jobs_only_with_their_files(client):
    for request, says in (
        ({"kind": "calibration_usb", "session": "."}, "isn't a folder of its own"),
        ({"kind": "calibration_fit", "robot": "nothing.yaml", "session": "x"}, "doesn't exist"),
        (
            {"kind": "calibration_check", "robot": ROBOT, "field": FIELD, "program": "examples",
             "logs": ["examples/logs/full_omni_routine.csv"], "ends": []},
            "give where each run ended",
        ),
    ):  # fmt: skip
        refused = client.post("/api/jobs", json=request)
        assert refused.status_code == 422 and says in refused.json()["detail"], refused.text
    # listening over USB runs `pros terminal`: a request can't name another command
    usb = {"kind": "calibration_usb", "session": "calibration/x", "command": ["sh", "-c", "id"]}
    refused = client.post("/api/jobs", json=usb)
    assert refused.status_code == 422 and "command" in refused.text, refused.text


# --- the whole session, through the server ----------------------------------------------------


def finished(client, request: dict, timeout: float = 900) -> dict:
    started = client.post("/api/jobs", json=request)
    assert started.status_code == 200, started.text
    job = started.json()
    deadline = time.monotonic() + timeout
    while job["state"] in ("queued", "running"):
        assert time.monotonic() < deadline, f"{request['kind']} took too long"
        time.sleep(0.5)
        job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["state"] == "succeeded", job["error"]
    return job


@pytest.mark.session
def test_a_whole_session_runs_in_the_app(tmp_path, build):
    """Plan and write the program, practice the session in vexsim on a robot unlike its
    config, fit it, apply what it found: as the Calibrate page does, through the server."""
    pytest.importorskip("fastapi")
    import shutil

    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    (tmp_path / "robots").mkdir()
    (tmp_path / "fields").mkdir()
    shutil.copy(ROOT / ROBOT, tmp_path / "robots")
    shutil.copy(ROOT / FIELD, tmp_path / "fields")
    robot, field = "robots/1239e_2026-27.yaml", "fields/1239e_2026-27.yaml"
    app = create_app(
        tmp_path, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as client:
        client.headers["authorization"] = f"Bearer {TOKEN}"
        folder = "calibration/vexsim_calibration"
        finished(
            client,
            {"kind": "calibration_program", "robot": robot, "field": field, "folder": folder},
        )
        program = client.get("/api/calibration/program", params={"folder": folder}).json()
        assert program["written"] and not program["pros_project"]
        tests = program["plan"]["tests"]
        assert [t["key"] for t in tests][:5] == [
            "device_check",
            "free_spin",
            "imu_still",
            "imu_turns",
            "push",
        ]
        assert all(t["map"] for t in tests if t["kind"] != "on_hand")
        practice = ["device_check", "free_spin", "push", "straight", "spin"]
        job = finished(
            client,
            {"kind": "calibration_practice", "robot": robot, "field": field, "program": folder,
             "session": "calibration/practice", "tests": practice},
        )  # fmt: skip
        assert job["result"]["added"] == 10
        state = client.get(
            "/api/calibration/session", params={"path": "calibration/practice", "robot": robot}
        ).json()
        assert state["practice"] and all(r["quality"] == "good" for r in state["runs"])
        assert state["runs"][0]["result"].startswith("passed")
        fit = {"robot": robot, "session": "calibration/practice", "field": field}
        finished(client, {"kind": "calibration_fit", **fit})
        state = client.get(
            "/api/calibration/session", params={"path": "calibration/practice", "robot": robot}
        ).json()
        report = state["report"]
        assert report["held_out"]["matches"], report["held_out"]
        changed = {c["location"]: c["value"] for c in report["changes"]}
        diameters = [v for k, v in changed.items() if k.endswith("diameter_in")]
        assert diameters and all(abs(d - 3.20) < 0.02 for d in diameters)  # unlike: 3.20 in
        assert changed['overrides["motor.voltage_cap"]'] == 1.0
        text = (tmp_path / robot).read_text(encoding="utf-8")
        applied = client.post(
            "/api/calibration/apply", json={"session": "calibration/practice", "text": text}
        ).json()
        assert applied["changes"] == len(changed) and applied["check"]["issues"] == []
        assert applied["text"].count("# Calibrated from session practice on ") == 1
        straight = next(r["file"] for r in state["runs"] if r["test"] == "straight")
        tape = client.get(
            "/api/robotlog",
            params={"path": f"calibration/practice/runs/{straight}", "robot": robot},
        ).json()
        assert tape["summary"]["pose"] == "odometry" and len(tape["times"]) > 100
        x0, y0, _ = tape["estimate"][0]
        far = max(math.hypot(x - x0, y - y0) for x, y, _ in tape["estimate"])
        assert 15 < far < 60  # out and back, as the plan's straight test goes

"""The browser app's pages (phase 11.5): jobs with progress, the results they keep, sweeps,
benchmarks, calibration and analysis, through their services and the server."""

import csv
import math
import os
import time
from pathlib import Path

import numpy as np
import pytest

from tests.conftest import ROOT
from vexsim.app import results
from vexsim.app.jobs import JobManager
from vexsim.app.jsonsafe import finite
from vexsim.app.launch import RunConfiguration, read_configurations
from vexsim.app.sweeps import (
    PLACEMENT_STREAM,
    Sweep,
    SweepError,
    expand,
    label,
    measure,
    read_sweeps,
    run_trial,
    variations,
    write_sweeps,
)
from vexsim.ui.protocol import (
    BenchResult,
    CalibrationResult,
    Drift,
    MotorCurves,
    Odometry,
    RoutinePlan,
    ScenarioInfo,
    SweepResult,
)

ROBOT_LOG = "examples/logs/full_omni_routine.csv"
TOKEN = "test-token"


@pytest.fixture(autouse=True)
def elsewhere(tmp_path, monkeypatch):
    """Runs and results go to a temporary folder, not the repository's .vexsim (job
    processes inherit the variables)."""
    monkeypatch.setenv("VEXSIM_RUNS_DIR", str(tmp_path / "recorded-runs"))
    monkeypatch.setenv("VEXSIM_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("VEXSIM_CHILD_DUMP_S", "15")


# --- jobs ---------------------------------------------------------------------------------


def test_jobs_report_progress_and_parts_of_their_result():
    jobs = JobManager()
    heard = []
    jobs.add_listener(lambda event, job, line: heard.append(event))
    items = [{"trial": 1}, {"trial": 2, "error_in": float("nan")}]
    job = jobs.submit("echo", {"items": items, "result": np.float64(2.5)})
    assert jobs.wait(job, 30) and job.state == "succeeded"
    assert job.items == [{"trial": 1}, {"trial": 2, "error_in": None}]  # JSON can't hold NaN
    assert job.progress == (2, 2) and {"progress", "item"} <= set(heard)
    later = job.to_dict(items_since=1)
    assert later["items"] == [{"trial": 2, "error_in": None}] and later["items_size"] == 2
    brief = job.to_dict(brief=True)  # as GET /api/jobs lists it
    assert brief["log"] == brief["items"] == [] and brief["result"] is None


def test_data_for_browsers_is_plain_json():
    data = {"a": np.float32(1.5), "b": np.array([1, 2]), "c": [math.inf, np.bool_(True)], 3: None}
    assert finite(data) == {"a": 1.5, "b": [1, 2], "c": [None, True], "3": None}


# --- the results the long jobs keep -----------------------------------------------------------


def test_results_are_kept_newest_first_and_pruned(tmp_path):
    root = tmp_path / "bench"
    first, folder = results.new_result(root)
    (folder / "trials.csv").write_text("seed\n0\n")
    results.write_result(folder, "bench", "S-curve", "2 trials", {"rows": [1.5, math.nan]})
    time.sleep(0.1)  # a clock tick apart even on Windows
    second, folder2 = results.new_result(root)
    results.write_result(folder2, "bench", "Pose", "1 trial", {})
    listed = results.list_results(root)
    assert [a["id"] for a in listed] == [second, first] and listed[1]["title"] == "S-curve"
    assert results.read_result(root, first)["rows"] == [1.5, None]
    assert results.result_file(root, first, "trials.csv").read_text() == "seed\n0\n"
    with pytest.raises(ValueError):
        results.result_file(root, first, "../../elsewhere.txt")
    with pytest.raises(FileNotFoundError):
        results.result_file(root, first, "report.html")
    with pytest.raises(ValueError):
        results.read_result(root, "../x")

    abandoned, partial = results.new_result(root)  # a job cancelled partway: no result.json
    os.utime(partial, (time.time() - 2 * results.STALE_S,) * 2)
    assert set(results.prune(root, keep=1)) == {first, abandoned}
    assert [a["id"] for a in results.list_results(root)] == [second]
    results.delete_result(root, second)
    assert results.list_results(root) == []
    assert results.results_root("ws", "sweeps") == Path(os.environ["VEXSIM_RESULTS_DIR"]) / "sweeps"


# --- sweeps ------------------------------------------------------------------------------------


def saved(name, **spec):
    return RunConfiguration(name=name, robot="robot.yaml", **spec)


def test_a_sweep_runs_each_saved_run_per_variation_and_seed():
    configurations = [
        saved("Left", start=(60, 0, 0), env={"AUTON": "Left", "MODE": "saved"}),
        saved("Right", start=(-60, 0, 180), env={"AUTON": "Right"}),
    ]
    sweep = Sweep(
        name="s",
        runs=["Right", "Left"],
        vary={"MODE": ["a", "b"], "SPEED": ["1", "2"]},
        seeds=2,
        first_seed=5,
        placement_sd=(0.5, 0.5, 1),
    )
    assert [label(v) for v in variations(sweep)] == [
        "MODE=a, SPEED=1", "MODE=a, SPEED=2", "MODE=b, SPEED=1", "MODE=b, SPEED=2",
    ]  # fmt: skip
    trials = expand(sweep, configurations)
    assert len(trials) == 2 * 4 * 2 and [t.index for t in trials] == list(range(16))
    first = trials[0]
    assert (first.run, first.variation, first.seed) == ("Right", {"MODE": "a", "SPEED": "1"}, 5)
    assert first.spec.env == {"AUTON": "Right", "MODE": "a", "SPEED": "1"}  # varied over saved
    assert first.spec.seed == 5 and first.spec.robot == "robot.yaml"
    # a seed puts the robot down the same way for every run and variation, as a hand would
    dx, dy, dh = np.random.default_rng([5, PLACEMENT_STREAM]).normal(0.0, (0.5, 0.5, 1))
    for t in trials:
        if t.seed == 5:
            base = (60, 0, 0) if t.run == "Left" else (-60, 0, 180)
            assert t.spec.start == pytest.approx((base[0] + dx, base[1] + dy, base[2] + dh))
    still = expand(Sweep(name="s", runs=["Left"]), configurations)
    assert [label(t.variation) for t in still] == ["as saved"] * 3
    assert all(t.spec.start == (60, 0, 0) for t in still)  # no placement error asked for

    with pytest.raises(SweepError, match="no saved run named 'Up'"):
        expand(Sweep(name="s", runs=["Up"]), configurations)
    with pytest.raises(SweepError, match="listed twice"):
        expand(Sweep(name="s", runs=["Left", "Left"]), configurations)
    with pytest.raises(SweepError, match="at most 5000"):
        expand(
            Sweep(name="s", runs=["Left"], vary={"X": list("abcdefghijk")}, seeds=500),
            configurations,
        )


def test_sweep_values_are_what_a_program_reads_from_its_environment():
    sweep = Sweep.model_validate({"name": "s", "runs": ["r"], "vary": {"X": [1, 2.5, True]}})
    assert sweep.vary == {"X": ["1", "2.5", "true"]}
    with pytest.raises(ValueError):
        Sweep.model_validate({"name": "s", "runs": ["r"], "vary": {"NOT A NAME": ["1"]}})
    with pytest.raises(ValueError):
        Sweep.model_validate({"name": "s", "runs": ["r"], "vary": {"X": []}})


def test_sweeps_round_trip_through_sweeps_yaml(tmp_path):
    assert read_sweeps(tmp_path) == []
    sweeps = [
        Sweep(name="Quick", runs=["A"], seeds=1, max_seconds=5),
        Sweep(name="Full", description="it all", runs=["A", "B"], vary={"T": ["x", "y"]},
              placement_sd=(0.5, 0.5, 1), first_seed=3),
    ]  # fmt: skip
    path = write_sweeps(tmp_path, sweeps)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Sweeps for `vexsim ui`") and "T: [x, y]" in text
    assert "placement_sd: [0.5, 0.5, 1]" in text and "\n\n  - name: Full" in text
    assert read_sweeps(tmp_path) == sweeps
    with pytest.raises(SweepError, match="two sweeps are named"):
        write_sweeps(tmp_path, [sweeps[0], sweeps[0]])
    path.write_text("sweeps:\n  - name: x\n    runs: []\n", encoding="utf-8")
    with pytest.raises(SweepError, match=r"sweep 1 \(x\): runs"):
        read_sweeps(tmp_path)


def test_the_1239e_evaluation_is_saved_as_sweeps():
    sweeps = {s.name: s for s in read_sweeps(ROOT)}
    configurations = read_configurations(ROOT)
    full = expand(sweeps["1239E: localization"], configurations)
    assert len(full) == 9 * 4 * 6  # every routine, every localization mode, 6 seeds
    quick = expand(sweeps["1239E: RCL + MCL vs odometry"], configurations)
    assert len(quick) == 9 * 2 * 3  # evaluate_1239e.py's defaults
    assert {t.spec.program for t in full} == {"examples/pros_projects/1239e_2026-27"}
    assert {t.variation["VEXSIM_TRACKING"] for t in full} == {"rcl+mcl", "mcl", "rcl", "odom"}


def test_a_trial_is_measured_while_its_program_runs():
    def row(t, phase, true, estimate):
        return [t, phase, *true, *(estimate or (math.nan,) * 3)]

    rows = [row(0.0, "initialize", (0, 0, 0), None), row(0.01, "initialize", (0, 0, 0), (0, 0, 0))]
    rows += [row(1.0 + k * 0.01, "autonomous", (k, 0, 0), (k, 0.1 * k, 2)) for k in range(25)]
    rows[12] = row(1.1, "autonomous", (10, 0, 0), None)  # no estimate for a moment
    rows.append(row(1.25, "done", (30, 0, 0), (30, 0, 0)))
    m = measure(rows)
    assert m["seconds"] == pytest.approx(0.24) and m["end"] == [24, 0, 0]
    assert m["end_estimate"] == pytest.approx([24, 2.4, 2]) and m["final_in"] == pytest.approx(2.4)
    assert m["max_in"] == pytest.approx(2.4) and m["max_deg"] == pytest.approx(2)
    errors = [0.1 * k for k in range(25) if k != 10]
    assert m["mean_in"] == pytest.approx(sum(errors) / len(errors))
    assert m["trace"] == [0.0, None, 2.0]  # every 0.1 s from the first estimate; none at 1.1 s
    assert measure([])["mean_in"] is None and measure([])["trace"] == []


def test_a_sweep_runs_as_a_job_and_keeps_its_trials():
    sweep = Sweep(
        name="Tour",
        runs=["Tour (Python)"],
        vary={"TOUR_FLAVOR": ["a", "b"]},
        seeds=2,
        placement_sd=(0.5, 0.5, 1),
        max_seconds=3,
    )
    store = results.results_root(ROOT, "sweeps")
    params = {"sweep": sweep.model_dump(), "root": str(ROOT), "results": str(store), "workers": 2}
    jobs = JobManager()
    job = jobs.submit("sweep", params)
    assert jobs.wait(job, 180), job.log
    assert job.state == "succeeded", job.error
    assert job.progress == (4, 4) and sorted(i["index"] for i in job.items) == [0, 1, 2, 3]
    result = SweepResult.model_validate(results.read_result(store, job.result["id"]))
    assert [v.label for v in result.variations] == ["a", "b"]
    assert [t.index for t in result.trials] == [0, 1, 2, 3]
    trial = result.trials[3]
    assert (trial.variation, trial.seed, trial.error) == ("b", 1, None)
    assert trial.spec.env["TOUR_FLAVOR"] == "b" and len(trial.trace) > 5
    assert trial.mean_in is not None and not trial.finished  # the tour takes longer than 3 s
    # a trial runs again exactly: the same spec gives the same numbers
    again = run_trial(9, trial.spec.model_dump(), str(ROOT), None, 3)
    assert again["mean_in"] == pytest.approx(trial.mean_in) and again["trace"] == trial.trace
    with (store / result.about.id / "trials.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 4 and rows[0]["run"] == "Tour (Python)"


def test_a_failed_trial_is_its_rows_error():
    outcome = run_trial(0, {"robot": "missing.yaml"}, str(ROOT), None, 1)
    assert outcome["error"] == "missing.yaml: invalid robot config"
    assert outcome["finished"] is False and outcome["mean_in"] is None


# --- through the server ---------------------------------------------------------------------


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


def finished(client, request: dict, timeout: float = 180) -> dict:
    """Start a job and follow it, as a page does, until it ends; its last JobInfo."""
    started = client.post("/api/jobs", json=request)
    assert started.status_code == 200, started.text
    job, log, items = started.json(), [], []
    deadline = time.monotonic() + timeout
    while job["state"] in ("queued", "running"):
        assert time.monotonic() < deadline, f"{request['kind']} took too long: {log[-20:]}"
        time.sleep(0.2)
        job = client.get(f"/api/jobs/{job['id']}?since={len(log)}&items_since={len(items)}").json()
        log += job["log"]
        items += job["items"]
    return {**job, "log": log, "items": items}


def test_the_server_runs_the_analyses(client):
    curves = MotorCurves.model_validate(finished(client, {"kind": "motor_curves"})["result"])
    assert curves.cartridge == "green" and [c.command for c in curves.curves] == [
        "velocity",
        "voltage",
    ]
    assert curves.current_limit_a == 2.5 and curves.curves[0].speed_rpm[0] == 0

    robot = "examples/robots/full_omni_6m.yaml"
    job = finished(client, {"kind": "drift", "robot": robot, "lateral_mu": [0.4, 0.1]})
    drift = Drift.model_validate(job["result"])
    assert [r.lateral_mu for r in drift.runs] == [0.4, 0.1]
    assert drift.runs[1].final_error_in > drift.runs[0].final_error_in  # slippier, further off
    assert "roller friction 0.1" in job["log"][1]
    mecanum = finished(client, {"kind": "drift", "robot": "examples/robots/mecanum_4m.yaml"})
    assert mecanum["state"] == "failed" and "differential drivetrain" in mecanum["error"]

    job = finished(client, {"kind": "odometry", "robot": robot, "script": "gentle", "seed": 2})
    odometry = Odometry.model_validate(job["result"])
    names = [e.name for e in odometry.estimates]
    assert "tracking wheels + IMU" in names and len(odometry.time_s) == len(odometry.truth)

    assert client.post("/api/jobs", json={"kind": "nope"}).status_code == 422
    outside = client.post("/api/jobs", json={"kind": "drift", "robot": "../robot.yaml"})
    assert outside.status_code == 422 and "outside the workspace" in outside.json()["detail"]
    listed = client.get("/api/jobs").json()
    assert {j["kind"] for j in listed} >= {"motor_curves", "drift", "odometry"}
    assert all(j["result"] is None and j["log"] == [] for j in listed)


def test_the_server_benchmarks_a_scenario_and_keeps_it(client):
    scenario = "examples/scenarios/s_curve.yaml"
    info = ScenarioInfo.model_validate(client.get(f"/api/bench/scenario?path={scenario}").json())
    assert info.localizers == ["tracking wheels + IMU", "drive encoders + IMU"]
    assert [c.name for c in info.controllers] == ["pure pursuit", "RAMSETE"]
    assert "→" in info.task and info.disturbances == ["push (0, 25) N for 0.3 s at 1.2 s"]

    request = {"kind": "bench", "scenario": scenario, "seeds": 2, "workers": 1}
    request |= {"localizers": ["tracking wheels + IMU"]}
    job = finished(client, request)
    assert job["state"] == "succeeded", job["error"]
    assert job["progress"] == [4, 4]  # 2 seeds x 1 localizer x 2 controllers
    listed = client.get("/api/results/bench").json()
    assert [a["id"] for a in listed] == [job["result"]["id"]]
    result_id = listed[0]["id"]
    bench = BenchResult.model_validate(client.get(f"/api/results/bench/{result_id}").json())
    assert len(bench.rows) == 4 and [c.controller for c in bench.combos] == [
        "pure pursuit",
        "RAMSETE",
    ]
    assert bench.summary[0].stats["final_error_in"] is not None
    assert (
        bench.command == f'vexsim bench {scenario} --seeds 2 --localizers "tracking wheels + IMU"'
    )
    assert len(bench.worst) == 2 and bench.worst[0].file in bench.files

    files = f"/api/results/bench/{result_id}/files"
    trials = client.get(f"{files}/trials.csv")
    assert trials.status_code == 200 and "attachment" in trials.headers["content-disposition"]
    if bench.report:  # matplotlib draws the report's charts
        report = client.get(f"{files}/report.html")
        assert report.headers["content-security-policy"] == "sandbox" and "<html" in report.text
    assert client.get(f"{files}/../../../pyproject.toml").status_code == 404
    replay = client.post(
        f"/api/results/bench/{result_id}/replay", json={"file": bench.worst[0].file}
    )
    assert replay.status_code == 200
    assert replay.json()["name"].startswith("S-curve under a mid-path shove: the worst of")
    assert client.delete(f"/api/results/bench/{result_id}").status_code == 204
    assert client.get(f"/api/results/bench/{result_id}").status_code == 404
    assert client.get("/api/results/nope").status_code == 404


def test_the_server_says_why_a_benchmark_cant_start(client, tmp_path):
    missing = client.get("/api/bench/scenario?path=examples/robots/full_omni_6m.yaml")
    assert missing.status_code == 422 and missing.json()["issues"]  # not a scenario
    started = client.post("/api/jobs", json={"kind": "bench", "scenario": "nope.yaml"})
    assert started.status_code == 422 and started.json()["error"]


def test_the_server_keeps_sweeps_and_runs_them(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    app = create_app(
        tmp_path, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as client:
        client.headers["authorization"] = f"Bearer {TOKEN}"
        assert client.get("/api/sweeps").json() == {
            "file": ".vexsim/sweeps.yaml", "sweeps": [], "error": None,
        }  # fmt: skip
        sweep = {"name": "Quick", "runs": ["A"], "seeds": 1}
        saved_ = client.put("/api/sweeps", json={"sweeps": [sweep]}).json()
        assert [s["name"] for s in saved_["sweeps"]] == ["Quick"]
        assert (tmp_path / ".vexsim" / "sweeps.yaml").is_file()
        unknown = client.post("/api/jobs", json={"kind": "sweep", "sweep": sweep})
        assert unknown.status_code == 422 and "no saved run named 'A'" in unknown.json()["detail"]
        (tmp_path / ".vexsim" / "sweeps.yaml").write_text("sweeps: [unclosed\n", encoding="utf-8")
        assert "sweeps.yaml" in client.get("/api/sweeps").json()["error"]
        refused = client.put("/api/sweeps", json={"sweeps": [sweep]})
        assert refused.status_code == 409  # someone's broken file isn't overwritten


def test_the_server_calibrates_with_a_robot_log(client, tmp_path):
    robot = "examples/robots/full_omni_6m.yaml"
    setup = client.get(f"/api/calibrate/parameters?robot={robot}").json()
    assert [p["name"] for p in setup["parameters"]] == [
        "wheel.omni.longitudinal_mu", "wheel.omni.lateral_mu", "wheel.omni.rolling_resistance",
    ]  # fmt: skip
    plan = client.post(
        "/api/calibrate/routine",
        json={"robot": robot, "project": "examples/pros_projects/calibration"},
    )
    plan = RoutinePlan.model_validate(plan.json())
    assert [f.path.rsplit("/", 1)[1] for f in plan.files] == [
        "vexsim_calibration.hpp",
        "vexsim_calibration.cpp",
        "vexsim_log.hpp",  # vexsim's logger, which the routine logs through
        "vexsim_log.cpp",
    ]
    assert plan.seconds > 5 and plan.steps[0].name == "settle"
    assert (
        client.post(
            "/api/calibrate/routine", json={"robot": robot, "project": "examples"}
        ).status_code
        == 422
    )

    compared = finished(
        client, {"kind": "calibrate", "robot": robot, "log": ROBOT_LOG, "compare_only": True}
    )
    assert compared["state"] == "succeeded", compared["error"]
    result = CalibrationResult.model_validate(
        client.get(f"/api/results/calibrations/{compared['result']['id']}").json()
    )
    assert result.compare_only and result.overrides == {} and result.log_facts.rows == 700
    assert {r.group for r in result.rms} == {
        "motor velocity",
        "motor current",
        "tracking wheels",
        "heading rate",
    }
    assert [p.series[0].name for p in result.panels][:1] == ["robot log"]

    request = {
        "kind": "calibrate",
        "robot": robot,
        "log": ROBOT_LOG,
        "fit": ["wheel.omni.lateral_mu"],
    }
    fitted = finished(client, {**request, "max_iterations": 3})
    assert fitted["state"] == "succeeded", fitted["error"]
    result = CalibrationResult.model_validate(
        client.get(f"/api/results/calibrations/{fitted['result']['id']}").json()
    )
    assert [p.name for p in result.parameters] == ["wheel.omni.lateral_mu"]
    assert result.overrides["battery.internal_resistance_ohm"] == pytest.approx(0.15, abs=0.01)
    assert {"overrides.yaml", "simulated.csv"} <= set(result.files)
    text = (ROOT / robot).read_text(encoding="utf-8")
    patched = client.post(
        "/api/config/overrides", json={"text": text, "values": result.overrides}
    ).json()
    assert (
        patched["text"].startswith(text.rstrip("\n"))
        and "\noverrides:\n  wheel.omni.lateral_mu: " in patched["text"]
    )
    assert patched["check"]["issues"] == []

"""Phase 6: scenarios, trials, metrics, the Monte-Carlo runner, and reports."""

import copy
import math

import numpy as np
import pytest

from tests.conftest import ROOT
from vexsim.bench.metrics import score
from vexsim.bench.runner import run_bench
from vexsim.bench.scenario import (
    ControllerSpec,
    FollowTask,
    LoadedScenario,
    MoveToPointTask,
    MoveToPoseTask,
    Scenario,
    load_scenario,
    validate_scenario,
)
from vexsim.bench.trial import run_trial
from vexsim.cli import main
from vexsim.config.yaml_io import load_yaml_file

S_CURVE = ROOT / "examples" / "scenarios" / "s_curve.yaml"
POSE = ROOT / "examples" / "scenarios" / "pose_approach.yaml"
SCENARIO_DIR = S_CURVE.parent


def scenario(**changes) -> LoadedScenario:
    data = copy.deepcopy(load_yaml_file(S_CURVE))
    data.update(changes)
    return LoadedScenario(validate_scenario(data).raise_for_errors(), SCENARIO_DIR)


def same(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


# --- scenario files -------------------------------------------------------------------------------


def test_example_scenarios_are_valid():
    for path in (S_CURVE, POSE):
        report = validate_scenario(path)
        assert report.ok, report.issues


def test_scenario_errors_are_reported():
    data = copy.deepcopy(load_yaml_file(S_CURVE))
    data["controllers"] = [{"name": "a", "kind": "boomerang"}, {"name": "a", "kind": "ramsete"}]
    data["randomize"]["battery_soc"] = [0.9, 0.5]
    data["task"]["tolerance_in"] = -1
    report = validate_scenario(data)
    assert not report.ok
    data["task"]["tolerance_in"] = 2
    locations = {i.location for i in validate_scenario(data).errors}
    assert locations == {"controllers[0].kind", "controllers[1].name", "randomize.battery_soc"}


def test_default_controller_per_task():
    loaded = LoadedScenario(
        Scenario(
            name="x", robot="r.yaml", task=MoveToPoseTask(type="move_to_pose", x=1, y=2, heading=3)
        ),
        SCENARIO_DIR,
    )
    assert loaded.controllers == (ControllerSpec(name="boomerang", kind="boomerang"),)


# --- metrics ----


def test_metrics_for_a_point_task():
    task = MoveToPointTask(type="move_to_point", x=10, y=0, tolerance_in=1.0)
    t = np.arange(0, 2.0, 0.01)
    x = np.minimum(t * 12, 11.0) - np.where(
        t > 1.2, (t - 1.2) * 2.0, 0
    )  # overshoots to 11, backs to ~9.4
    truth = np.column_stack([x, np.zeros_like(t), np.zeros_like(t)])
    est = truth + [0.5, 0.0, 0.0]
    m = score(
        task,
        t,
        truth,
        est,
        completion_time_s=1.5,
        timed_out=False,
        energy_j=10,
        peak_motor_temp_c=30,
    )
    assert m.overshoot_in == pytest.approx(1.0)
    assert m.final_error_in == pytest.approx(abs(x[-1] - 10))
    assert m.success == (abs(x[-1] - 10) <= 1.0)
    assert math.isnan(m.final_heading_error_deg) and math.isnan(m.path_rms_in)
    assert m.loc_error_final_in == pytest.approx(0.5)
    assert m.distance_in == pytest.approx(11.0 + abs(x[-1] - 11.0), rel=1e-6)


def test_metrics_settle_time_and_paths():
    task = FollowTask(type="follow", waypoints=((0, 0), (20, 0)), tolerance_in=1.0)
    t = np.arange(0, 2.0, 0.01)
    x = np.minimum(t * 20, 20.0)
    truth = np.column_stack([x, np.full_like(t, 0.5), np.zeros_like(t)])  # 0.5 in off the path
    m = score(
        task,
        t,
        truth,
        truth,
        completion_time_s=1.0,
        timed_out=False,
        energy_j=0,
        peak_motor_temp_c=0,
    )
    assert m.path_rms_in == pytest.approx(0.5, abs=0.01) and m.path_max_in == pytest.approx(
        0.5, abs=0.01
    )
    # Within 1 in of (20, 0) (0.5 in off the line) needs x >= 19.13, reached at t = 0.96 s.
    assert m.settle_time_s == pytest.approx(0.96, abs=0.006)
    assert m.success


# --- trials ----


def test_trials_are_deterministic_and_seeds_differ():
    loaded = load_scenario(S_CURVE)
    ctrl = loaded.controllers[0]
    a = run_trial(loaded, 4, "tracking wheels + IMU", ctrl).row()
    b = run_trial(loaded, 4, "tracking wheels + IMU", ctrl).row()
    c = run_trial(loaded, 5, "tracking wheels + IMU", ctrl).row()
    assert all(same(a[k], b[k]) for k in a)
    assert a["true_start_x"] != c["true_start_x"]
    assert a["param:wheel.omni.lateral_mu"] != c["param:wheel.omni.lateral_mu"]
    assert 0.15 <= a["param:wheel.omni.lateral_mu"] <= 0.25 and 0.6 <= a["battery_soc"] <= 1.0


def test_start_error_shows_up_as_localization_error():
    still = scenario(randomize={}, disturbances=[])
    off = scenario(randomize={"start_xy_in": 3.0}, disturbances=[])
    ctrl = still.controllers[0]
    exact = run_trial(still, 1, "tracking wheels + IMU", ctrl).metrics.loc_error_final_in
    shifted = run_trial(off, 1, "tracking wheels + IMU", ctrl).metrics.loc_error_final_in
    assert shifted > exact + 1.0


def test_push_disturbance_moves_the_robot_and_fools_drive_encoders():
    calm = scenario(disturbances=[], randomize={})
    shoved = scenario(
        disturbances=[{"type": "push", "at_s": 1.0, "duration_s": 0.4, "force_n": [0, 40]}],
        randomize={},
    )
    ctrl = calm.controllers[0]
    calm_loc = run_trial(calm, 0, "drive encoders + IMU", ctrl).metrics.loc_error_final_in
    shoved_loc = run_trial(shoved, 0, "drive encoders + IMU", ctrl).metrics.loc_error_final_in
    tracked = run_trial(shoved, 0, "tracking wheels + IMU", ctrl).metrics.loc_error_final_in
    assert shoved_loc > calm_loc + 2.0  # the encoders never saw the shove...
    assert tracked < shoved_loc / 2  # ...the horizontal tracking wheel did


def test_imu_bias_step_and_liftoff_disturbances():
    base = load_yaml_file(POSE)
    clean = copy.deepcopy(base)
    clean["disturbances"] = []
    clean["randomize"] = {}
    biased = copy.deepcopy(clean)
    biased["disturbances"] = [{"type": "imu_bias_step", "at_s": 0.5, "deg_per_s": 5.0}]
    lifted = copy.deepcopy(clean)
    lifted["disturbances"] = [
        {"type": "tracking_wheel_liftoff", "port": 11, "at_s": 0.3, "duration_s": 0.8}
    ]

    def loc_error(data):
        loaded = LoadedScenario(validate_scenario(data).raise_for_errors(), SCENARIO_DIR)
        return run_trial(
            loaded, 0, "tracking wheels + IMU", loaded.controllers[0]
        ).metrics.loc_error_final_in

    reference = loc_error(clean)
    assert loc_error(biased) > reference + 1.0
    assert loc_error(lifted) > reference + 1.0


def test_custom_localizer_and_controller_from_files(tmp_path):
    (tmp_path / "algos.py").write_text(
        "from vexsim.algorithms.localization.baselines import baseline_localizers\n"
        "from vexsim.algorithms.control.motions import MoveToPoint\n"
        "def my_odom(config):\n"
        "    loc = baseline_localizers(config)[-1]\n"
        "    loc.name = 'mine'\n"
        "    return loc\n"
        "def slow_point(task, geometry, volts=6.0):\n"
        "    return MoveToPoint(task.x, task.y, max_volts=volts)\n"
    )
    data = copy.deepcopy(load_yaml_file(POSE))
    data.update(
        robot=str(SCENARIO_DIR / ".." / "robots" / "full_omni_6m.yaml"),
        task={"type": "move_to_point", "x": 20, "y": 0},
        localizers=["algos.py:my_odom"],
        controllers=[{"name": "slow", "kind": "algos.py:slow_point", "options": {"volts": 5}}],
        disturbances=[],
    )
    loaded = LoadedScenario(validate_scenario(data).raise_for_errors(), tmp_path)
    result = run_trial(loaded, 0, "algos.py:my_odom", loaded.controllers[0])
    assert result.localizer == "algos.py:my_odom" and result.controller == "slow"
    assert result.metrics.final_error_in < 2.0


# --- runner, report, CLI ----


def test_parallel_runner_matches_inline():
    kw = {"localizers": ["drive encoders + IMU"], "controllers": ["pure pursuit"]}
    inline = run_bench(S_CURVE, [0, 1], workers=1, **kw)
    parallel = run_bench(S_CURVE, [0, 1], workers=2, **kw)
    assert len(inline.rows) == 2
    for a, b in zip(inline.rows, parallel.rows, strict=True):
        assert all(same(a[k], b[k]) for k in a)
    summary = inline.summary()[0]
    assert summary["trials"] == 2 and 0 <= summary["success_rate"] <= 1
    assert inline.worst("drive encoders + IMU", "pure pursuit")["seed"] in (0, 1)
    with pytest.raises(ValueError, match="unknown localizers"):
        run_bench(S_CURVE, [0], localizers=["psychic"], workers=1)


def test_report_and_cli(tmp_path, capsys):
    pytest.importorskip("matplotlib")
    out = tmp_path / "bench"
    code = main(["bench", str(S_CURVE), "--seeds", "2", "--workers", "2", "--out", str(out),
                 "--controllers", "pure pursuit,RAMSETE"])  # fmt: skip
    assert code == 0
    printed = capsys.readouterr().out
    assert "8 trials" in printed and "tracking wheels + IMU / RAMSETE" in printed
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "S-curve under a mid-path shove" in html and html.count("data:image/png;base64") == 6
    assert "push (0, 25) N for 0.3 s at 1.2 s" in html
    assert len((out / "trials.csv").read_text().splitlines()) == 9
    assert len(list(out.glob("worst_*.csv"))) == 4
    assert main(["replay", str(SCENARIO_DIR / ".." / "robots" / "full_omni_6m.yaml"),
                 str(next(out.glob("worst_*.csv"))), "--headless"]) == 0  # fmt: skip


def test_cli_rejects_bad_scenarios(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: x\nrobot: r.yaml\ntask: {type: fly}\n")
    assert main(["bench", str(bad), "--seeds", "1"]) == 1
    assert "task" in capsys.readouterr().out

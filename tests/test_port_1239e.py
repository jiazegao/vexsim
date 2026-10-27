"""Team 1239E's 2026-27 code, ported (docs/porting_1239e.md): it builds, its routines run,
and its localization keeps LemLib's pose near the truth."""

import importlib.util
import math
import os
import re
import sys

import pytest

from tests.conftest import EXAMPLE_ROBOT, ROOT
from vexsim.algorithms.localization.base import Pose
from vexsim.bridge.program import CppProgram
from vexsim.cli import main
from vexsim.config import load_field, load_robot, validate_field, validate_robot
from vexsim.runtime.follow import ExpoCurve
from vexsim.runtime.simulation import Simulation

PROJECT = ROOT / "examples" / "pros_projects" / "1239e_2026-27"
ROBOT = ROOT / "examples" / "robots" / "1239e_2026-27.yaml"
FIELD = ROOT / "examples" / "fields" / "1239e_2026-27.yaml"


def team_routines() -> dict[str, str]:
    """The team's own names for its routines: its selector's AutonCollection."""
    text = (PROJECT / "include" / "custom" / "auton_selector.hpp").read_text()
    return dict(re.findall(r'\{"([^"]+)",\s*(\w+)\}', text))


def load_script(name="evaluate_1239e"):
    path = ROOT / "examples" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # for its dataclasses
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def port_exe(lemlib_build):
    result = lemlib_build(PROJECT)
    assert any("include/lemlib/pid.hpp" in note for note in result.notes)  # the team's edit
    return str(result.executable)


def test_configs_are_clean():
    for report in (validate_robot(ROBOT), validate_field(FIELD)):
        assert report.ok and report.issues == []
    field = load_field(FIELD)
    assert field.size_in == (140.4, 140.4)
    assert sum(not o.solid for o in field.obstacles) == 9  # the bases


def test_left_40_runs_and_localizes(port_exe, in_cache):
    evaluate = load_script()
    with in_cache():
        result = evaluate.run_one(("Left 40", "rcl+mcl", 0, port_exe))
        odometry = evaluate.run_one(("Left 40", "odom", 0, port_exe))
    assert result.finished and 12 < result.seconds < 18
    assert result.mean_in < 4.0 and result.final_in < 4.0
    assert odometry.final_in > 2 * result.final_in  # MCL corrects what odometry alone misses


def test_the_evaluation_runs_as_a_sweep(port_exe, in_cache):
    """The sweeps saved in .vexsim/sweeps.yaml are evaluate_1239e.py: the same runs, from the
    same hand placements, measured the same way."""
    from vexsim.app.launch import read_configurations
    from vexsim.app.sweeps import expand, read_sweeps, run_trial

    evaluate = load_script()
    sweep = next(s for s in read_sweeps(ROOT) if s.name == "1239E: localization")
    trials = expand(sweep, read_configurations(ROOT))
    assert {t.run.removeprefix("1239E: ") for t in trials} == set(evaluate.AUTONS)
    assert {t.variation["VEXSIM_TRACKING"] for t in trials} == set(evaluate.TRACKING)
    assert sweep.max_seconds == evaluate.MAX_SECONDS
    routines = team_routines()
    for t in trials:
        auton = t.run.removeprefix("1239E: ")
        assert t.spec.routine == routines[auton]  # the script picks it by the team's name
        assert t.spec.start == pytest.approx(evaluate.placement(auton, t.seed))
    trial = next(
        t
        for t in trials
        if t.run == "1239E: Left 30" and t.variation["VEXSIM_TRACKING"] == "mcl" and t.seed == 1
    )
    with in_cache():
        swept = run_trial(trial.index, trial.spec.model_dump(), str(ROOT), port_exe, 75)
        script = evaluate.run_one(("Left 30", "mcl", 1, port_exe))
    assert swept["error"] is None and swept["finished"] == script.finished
    for key in ("seconds", "mean_in", "max_in", "final_in", "max_deg"):
        assert swept[key] == pytest.approx(getattr(script, key), abs=1e-9), key


def test_a_routine_picked_runs_inside_autonomous(port_exe, tmp_path):
    """The routine switch (bridge/routines.py) runs right30() inside the team's own
    autonomous(), setup and all, exactly as the team's selector does when it picks it."""
    from vexsim.app.runspec import RunSpec
    from vexsim.bridge.routines import find_routines
    from vexsim.cli import build_parser

    found = find_routines(PROJECT)
    assert sorted(r.name for r in found.routines) == sorted(team_routines().values())
    assert found.named("right30").start_pose() == (-60, 0, 180)  # its setPose(-60, 0, -90)
    args = ["run", str(ROBOT), "--program", str(PROJECT), "--routine", "right30"]
    spec = RunSpec.from_args(build_parser().parse_args(args))
    assert spec.start == (-60, 0, 180) and spec.to_args()[4:6] == ["--routine", "right30"]
    poses, consoles = {}, {}
    picks = {"selector": {"env": {"VEXSIM_AUTON": "Right 30"}}, "switch": {"routine": "right30"}}
    for how, kwargs in picks.items():
        program = CppProgram(port_exe, **kwargs)
        sim = Simulation(load_robot(ROBOT), program=program, field=load_field(FIELD), seed=1,
                         start=Pose(-60, 0, 180), echo=None)  # fmt: skip
        sim.start("autonomous")
        sim.run_for(6.0)
        sim.close()
        poses[how], consoles[how] = sim.robot.pose, sim.console
    assert poses["switch"] == pytest.approx(poses["selector"], abs=1e-9)
    assert math.dist(poses["switch"][:2], (-60 * 0.0254, 0)) > 0.3  # it went somewhere
    note = "vexsim: autonomous() called left40(); running right30() instead"
    assert any(line.endswith(note) for line in consoles["switch"])


def test_routines_are_picked_by_name(port_exe):
    program = CppProgram(port_exe, env={"VEXSIM_AUTON": "Left 99"})
    sim = Simulation(load_robot(ROBOT), program=program, field=load_field(FIELD),
                     start=Pose(60, 0, 0), echo=None)  # fmt: skip
    sim.start("autonomous")
    sim.run_for(2.5)  # initialize() calibrates the IMU first
    sim.close()
    assert any('VEXSIM_AUTON: no routine named "Left 99"' in line for line in sim.console)
    # the routine that ran instead (the first, Left 40) says where the robot should start
    assert any("start the simulated robot with --start=60,0,0" in line for line in sim.console)


def test_run_passes_environment_variables(capsys, monkeypatch):
    monkeypatch.setenv("VEXSIM_PORT_TEST", "")  # restored afterwards
    args = ["run", str(EXAMPLE_ROBOT), "--headless", "--seconds", "0.01"]
    assert main([*args, "--env", "NO_EQUALS_SIGN"]) == 1
    assert "--env needs KEY=VALUE" in capsys.readouterr().out
    assert main([*args, "--env", "VEXSIM_PORT_TEST=a=b"]) == 0
    assert os.environ["VEXSIM_PORT_TEST"] == "a=b"  # a Python program runs in this process


def write_mcl_log(path, poses, t0=1.0):
    """An MCL log as the team's code writes it, for poses (x, y, theta) 30 ms apart."""
    lines = []
    for i, (x, y, theta) in enumerate(poses):
        for k in range(5):  # sensors: reading mm, ray origin, ray angle
            angle = theta + (0, 0, math.pi / 2, math.pi, -math.pi / 2)[k]
            lines.append(f"{1000 + k},{x:.4f},{y:.4f},{angle:.5f}")
        lines += [f"{x:.4f},{y:.4f}", f"{t0 + 0.03 * i:.5f}", f"{x:.4f},{y:.4f},{theta:.5f}",
                  "1.2,1.2,"]  # fmt: skip
    path.write_text("\n".join(lines) + "\n9999,1.0,")  # cut off mid-update, as on the robot


def test_mcl_logs_parse(tmp_path):
    replay = load_script("replay_1239e_mcl_log")
    log = tmp_path / "mcl_log7.1239e"
    write_mcl_log(log, [(62.8, 0.0, math.pi), (62.5, 0.0, math.pi)])
    updates = replay.parse_log(log)
    assert len(updates) == 2  # the cut-off third is left out
    assert updates[1].t == pytest.approx(1.03) and updates[1].estimate == (62.5, 0.0, 3.14159)
    assert updates[0].sensors[3][0] == 1003 and updates[0].spread == (1.2, 1.2)
    routine, start = replay.start_routine(updates)
    assert routine == "startMcl 60,0,270,0,0,1,0" and start == pytest.approx((62.8, 0, 180))


def test_mcl_map_and_throttle_curve():
    replay = load_script("replay_1239e_mcl_log")
    wall = replay.map_hit(60.0, 0.0, 0.0, high=True)
    assert wall.what == "wall" and wall.distance_in == pytest.approx(10.2)
    assert wall.incidence_deg == pytest.approx(0.0)
    assert replay.map_hit(60.0, 0.0, math.radians(30), True).incidence_deg == pytest.approx(30.0)
    pole = replay.map_hit(10.0, 0.0, math.pi, high=True)  # high sensors see the pole...
    assert pole.what == "pole" and pole.distance_in == pytest.approx(10 - 1.5937075)
    base = replay.map_hit(10.0, 0.0, math.pi, high=False)  # ...low ones the base under it
    assert base.what == "base" and base.distance_in == pytest.approx(10 - 2.8056165)
    curve = ExpoCurve(*replay.CURVE)  # the team's throttle curve, inverted
    assert curve.stick(0) == 0 and curve.stick(127) == 127 and curve.stick(-200) == -127
    output = dict(curve.table)[abs(curve.stick(-60))]
    assert curve.stick(-60) < 0 and abs(output - 60) < 1.5


def test_replay_drives_a_logged_path(port_exe, in_cache, tmp_path):
    replay = load_script("replay_1239e_mcl_log")
    log = tmp_path / "mcl_log7.1239e"
    # 1 s still, then 24 in forward (toward -x) in 1.2 s, then 1 s still
    xs = [62.8] * 33 + [62.8 - 24 * (i / 40) ** 2 * (3 - 2 * i / 40) for i in range(41)]
    write_mcl_log(log, [(x, 0.0, math.pi) for x in xs + [xs[-1]] * 33])
    with in_cache():
        result = replay.replay((str(log), str(tmp_path / "out"), 1, port_exe, "hold"))
    assert result.sim_log.parent == tmp_path / "out" / "mcl_log7_s1"
    sim = replay.parse_log(result.sim_log)
    assert len(sim) > 90 and sim[-1].estimate[0] == pytest.approx(38.8, abs=3)
    following = sorted(result.following_in)  # the drive lags the reference a little
    assert following[len(following) // 2] < 1.5 and following[-1] < 6
    numbers = replay.measure(sim, result.truth_csv)
    assert numbers["interval median ms"] == pytest.approx(30.0)
    assert numbers["MCL error median in"] < 2

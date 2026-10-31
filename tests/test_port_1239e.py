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


LOGGING_GONE = ("initLog", "logMcl", "mclLog", "MCL_Log_Format", "LogData", "log_queue",
                "AsyncLogger", "DATA.1239e", "mcl_log", "VEXSIM_SD_DIR")  # fmt: skip


def test_the_mcl_log_is_gone():
    """Phase 14.2: the team's code no longer logs MCL to the SD card; vexsim's logger logs
    each routine instead (the next test)."""
    for path in sorted((PROJECT / "src").rglob("*")) + sorted((PROJECT / "include").rglob("*")):
        if path.suffix in (".c", ".cpp", ".h", ".hpp"):
            text = path.read_text(errors="replace")
            left = [name for name in LOGGING_GONE if name in text]
            assert not left, f"{path.relative_to(PROJECT)} still has {left}"


def test_a_routine_logs_itself_to_the_card(port_exe, tmp_path):
    """With a card in (here, the folder standing in for one), runAuton() logs the routine it
    runs with vexsim's logger: every device, LemLib's and MCL's poses, MCL's spread; and the
    log saves when autonomous() is done."""
    from vexsim.app.runspec import log_start, logged_path
    from vexsim.calibration.log import RobotLog

    card = tmp_path / "card"
    env = {"VEXSIM_AUTON": "Right 30", "VEXSIM_SD_DIR": str(card)}
    program = CppProgram(port_exe, env=env)
    sim = Simulation(load_robot(ROBOT), program=program, field=load_field(FIELD), seed=1,
                     start=Pose(-60, 0, 180), echo=None)  # fmt: skip
    sim.start("autonomous")
    assert sim.run_until_finished(30.0)
    sim.close()
    path = card / "vexsim_0001_right_30.csv"
    log = RobotLog.read(path)
    assert (log.info["name"], log.info["mode"]) == ("Right 30", "autonomous")
    assert log.ports("m") == [4, 5, 7, 9, 10, 17, 19, 20, 21]  # the drive's and mechanisms'
    assert log.ports("d") == [1, 2, 3, 8, 18] and log.ports("imu") == [16]
    assert log.poses() == ["lemlib", "mcl"] and len(log) > 1000
    assert 0 < log["val_mcl_spread_x"][-1] < 10 and 0 < log["val_mcl_spread_y"][-1] < 10
    x, y, theta = log.pose("lemlib")  # where the code believed the robot was, at the end
    believed = sim.reported_pose
    assert math.dist((x[-1], y[-1]), (believed.x, believed.y)) < 0.5
    mcl_x, mcl_y, _ = log.pose("mcl")  # MCL keeps LemLib's pose in step
    assert math.dist((x[-1], y[-1]), (mcl_x[-1], mcl_y[-1])) < 3
    # following it: from the routine's setPose(-60, 0, -90), not the code's pose before it
    assert logged_path(path)[1][0][:2] == pytest.approx((-60, 0), abs=0.5)
    assert log_start(path) == pytest.approx((-60, 0, 180), abs=0.5)

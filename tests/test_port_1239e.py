"""Team 1239E's 2026-27 code, ported (docs/porting_1239e.md): it builds, its routines run,
and its localization keeps LemLib's pose near the truth."""

import importlib.util
import os
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


def load_script():
    path = ROOT / "examples" / "scripts" / "evaluate_1239e.py"
    spec = importlib.util.spec_from_file_location("evaluate_1239e", path)
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

"""Phase 14.1: vexsim's logger (bridge/cpp/logger), robot logs in format 2
(calibration/log.py), and the simulator's stand-in for the SD card (vexsim run --sd).

The C++ tests build a small PROS project that logs with vexsim_log, so they need g++."""

import math
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pytest

from tests.conftest import EXAMPLE_ROBOT, ROOT
from vexsim.algorithms.localization.base import Pose
from vexsim.app.runspec import RunSpec
from vexsim.bridge.logger import add_logger, logger_files
from vexsim.bridge.program import CppProgram
from vexsim.calibration.log import BEGIN, END, RobotLog, columns_for
from vexsim.calibration.record import RobotLogger
from vexsim.cli import build_parser, main
from vexsim.config import load_robot
from vexsim.physics.world import PRIORITY_RECORD
from vexsim.runtime.simulation import Simulation

CONFIG = load_robot(EXAMPLE_ROBOT)
MAIN_H = ROOT / "examples" / "pros_projects" / "calibration" / "include" / "main.h"
DEVICES = (
    "1 motor, 2 motor, 3 motor, 4 motor, 5 motor, 6 motor, 10 imu, 11 rotation, 12 rotation, "
    "13 distance"
)
CODE_COLUMNS = ["pose_odom_x_in", "pose_odom_y_in", "pose_odom_theta_deg", "val_count"]

PROGRAM = r"""
#include "main.h"

#include <cstdlib>
#include <fstream>

#include "vexsim_log.hpp"

double g_count = 0;

void initialize() {
	vexsim_log::pose("Odom", [] { return vexsim_log::Pose{1.5, -2.25, 90.0}; });
	vexsim_log::value("count", [] { return g_count; });
	if (const char* limit = std::getenv("LOG_LIMIT_S")) vexsim_log::set_limit_s(std::atoi(limit));
}

void autonomous() {
	vexsim_log::info("robot", "test bot");
	vexsim_log::start("Left 40");
	pros::c::motor_move_voltage(1, 6000);
	pros::c::motor_move_voltage(4, 6000);
	vexsim_log::command(1, 6000);
	pros::delay(500);
	vexsim_log::mark("half way");
	g_count = 1;
	pros::delay(500);
	if (std::getenv("KEEP_GOING")) {
		while (true) pros::delay(10);  // a routine that runs past its period
	}
	std::printf("rows: %d\n", vexsim_log::stop());
	std::ofstream("/usd/stream.txt") << "from a C++ stream\n";
	if (std::FILE* file = std::fopen("/usd/c.txt", "w")) {
		std::fputs("from fopen\n", file);
		std::fclose(file);
	}
}
"""


class Built(NamedTuple):
    project: Path
    executable: Path


@pytest.fixture(scope="module")
def logging_project(build, tmp_path_factory):
    """A PROS project whose autonomous logs a second of driving, with a pose and a number of
    its own; built."""
    project = tmp_path_factory.mktemp("logging") / "project"
    (project / "include").mkdir(parents=True)
    (project / "src").mkdir()
    (project / "include" / "main.h").write_text(MAIN_H.read_text())
    (project / "src" / "main.cpp").write_text(PROGRAM)
    assert [state for _, state in add_logger(project)] == ["new", "new"]
    return Built(project, build(project).executable)


def run(built, mode="autonomous", seconds=None, robot_log=False, **env):
    """Run the program: its console lines, and if asked, the simulator's own robot log
    (``RobotLogger``'s columns), every millisecond of the run."""
    lines, rows = [], []
    program = CppProgram(built.executable, env={k: str(v) for k, v in env.items()})
    sim = Simulation(CONFIG, program=program, start=Pose(0, 0, 0), echo=lines.append)
    logger = RobotLogger(sim.robot, sim.sensors)
    if robot_log:
        sim.world.every(
            1, lambda w: rows.append(logger.row(w.clock.us / 1000)), priority=PRIORITY_RECORD
        )
    sim.start(mode, autonomous_limit_s=1.0 if mode == "match" else None)
    try:
        if seconds is None:
            assert sim.run_until_finished(20.0)
        else:
            sim.run_for(seconds)
    finally:
        sim.close()
    return lines, RobotLog.from_rows(logger.names, rows) if robot_log else None


# --- format 2 ------------------------------------------------------------------------------


LOG = """\
# vexsim-log: 2
# name: Left 40
# devices: 1 motor, 13 distance
time_ms,battery_mv,m1_cmd_mv,d13_mm,d13_conf,d13_size,pose_odom_x_in,pose_odom_y_in,\
pose_odom_theta_deg,val_count
0,12800,,,0,0,1.5,-2.25,90,0
#mark,5,intake on
10,12790,6000,412,63,400,1.6,-2.25,90,1
#mark,15,done
"""


def test_a_log_has_what_it_is_its_marks_and_the_codes_own_columns(tmp_path):
    log = RobotLog.parse(LOG)
    assert log.info == {"vexsim-log": "2", "name": "Left 40", "devices": "1 motor, 13 distance"}
    assert log.marks == [(5.0, "intake on"), (15.0, "done")]
    assert len(log) == 2 and log.ports("d") == [13] and math.isnan(log["m1_cmd_mv"][0])
    assert log.poses() == ["odom"]
    x, y, theta = log.pose("odom")
    assert list(x) == [1.5, 1.6] and list(y) == [-2.25, -2.25] and list(theta) == [90, 90]
    assert list(log["val_count"]) == [0, 1]
    # written and read again: the same, its marks among the rows
    again = RobotLog.read(log.write(tmp_path / "log.csv"))
    assert again.info == log.info and again.marks == log.marks
    assert (tmp_path / "log.csv").read_text().splitlines()[4:6] == [
        "0,12800,,,0,0,1.5,-2.25,90,0",
        "#mark,5,intake on",
    ]


def test_every_log_in_a_terminal_capture_reads():
    second = LOG.replace("Left 40", "Skills")
    capture = "\n".join(
        ["vexsim_log: starting", BEGIN, LOG, END, "some other output", BEGIN, second, END]
    )
    logs = RobotLog.parse_all(capture)
    assert [log.info["name"] for log in logs] == ["Left 40", "Skills"]
    assert RobotLog.parse(capture).info["name"] == "Skills"  # the last, as before
    cut_short = "\n".join([BEGIN, "time_ms,battery_mv", END, BEGIN, LOG, END])
    assert [log.info["name"] for log in RobotLog.parse_all(cut_short)] == ["Left 40"]
    with pytest.raises(ValueError, match="no robot log"):
        RobotLog.parse_all("nothing here")


def test_the_columns_cover_every_motor_and_sensor():
    config = load_robot(ROOT / "examples" / "robots" / "1239e_2026-27.yaml")
    columns = columns_for(config)
    motors = sorted({int(c[1:].split("_")[0]) for c in columns if c.startswith("m")})
    assert motors == [4, 5, 7, 9, 10, 17, 19, 20, 21]  # the drive's and the mechanisms'
    assert columns[-4:] == ["imu16_deg", "d18_mm", "d18_conf", "d18_size"]  # then by port


# --- the logger, in the simulator ------------------------------------------------------------


def test_the_logger_logs_every_device_and_the_codes_own_to_the_card(logging_project, tmp_path):
    sd = tmp_path / "sd"
    lines, _ = run(logging_project, VEXSIM_SD_DIR=sd)
    assert any(line.endswith("rows: 101") for line in lines)
    assert sorted(p.name for p in sd.iterdir()) == [
        "c.txt", "stream.txt", "vexsim_0001_left_40.csv", "vexsim_count.txt",
    ]  # fmt: skip
    assert (sd / "c.txt").read_text() == "from fopen\n"  # /usd/ files open in the folder
    assert (sd / "stream.txt").read_text() == "from a C++ stream\n"
    log = RobotLog.read(sd / "vexsim_0001_left_40.csv")
    info = log.info
    assert (info["vexsim-log"], info["name"], info["mode"]) == ("2", "Left 40", "autonomous")
    assert info["devices"] == DEVICES and info["robot"] == "test bot"
    assert list(log.columns) == columns_for(CONFIG) + CODE_COLUMNS
    assert len(log) == 101 and list(log.time_ms[:3]) == [0, 10, 20]
    assert log.marks == [(500.0, "half way")]
    x, y, theta = log.pose("odom")
    assert set(x) == {1.5} and set(y) == {-2.25} and set(theta) == {90}
    assert log["val_count"][0] == 0 and log["val_count"][-1] == 1
    commands = log["m1_cmd_mv"]
    assert math.isnan(commands[0]) and set(commands[1:]) == {6000}  # known once it's given
    assert np.isnan(log["m4_cmd_mv"]).all() and log["m4_mv"][-1] == 6000  # only measured
    assert log["m1_rpm"][-1] > 50 and log["imu10_deg"][-1] != 0

    run(logging_project, VEXSIM_SD_DIR=sd)  # numbered on: the next log
    assert (sd / "vexsim_0002_left_40.csv").is_file()
    assert (sd / "vexsim_count.txt").read_text().strip() == "2"


def test_a_simulated_runs_log_matches_the_simulators_own(logging_project, tmp_path):
    sd = tmp_path / "sd"
    _, recorded = run(logging_project, robot_log=True, VEXSIM_SD_DIR=sd)
    logged = RobotLog.read(sd / "vexsim_0001_left_40.csv")
    started = int(logged.info["started_ms"])  # the robot's clock is the simulation's
    assert started == 2  # autonomous starts after initialize()
    at = {round(t): i for i, t in enumerate(recorded.time_ms)}
    # from the second row: at 2 ms, before the motors' first readings, the code reads 0 where
    # the simulator has none yet
    rows = [at[started + round(t)] for t in logged.time_ms[1:]]

    def rounding(name: str) -> float:  # what the logger's decimals round away
        if name.startswith("imu"):
            return 6e-5
        if name.endswith(("_deg", "_rpm")):
            return 0.006
        return 0.06 if name.endswith("_temp") else 0

    for name in columns_for(CONFIG)[1:]:
        if name.endswith(("_cmd_mv", "_cmd_rpm")):
            continue  # the program only tells the logger what it told motor 1
        np.testing.assert_allclose(
            logged[name][1:],
            recorded[name][rows],
            atol=rounding(name),
            equal_nan=True,
            err_msg=name,
        )


def test_a_log_started_in_autonomous_saves_itself_when_autonomous_ends(logging_project, tmp_path):
    sd = tmp_path / "sd"
    run(logging_project, mode="match", seconds=1.5, VEXSIM_SD_DIR=sd, KEEP_GOING=1)
    log = RobotLog.read(sd / "vexsim_0001_left_40.csv")
    assert len(log) == 101 and log.marks[-1] == (1000.0, "mode: disabled")  # as on a field
    assert log.info["mode"] == "autonomous"


def test_a_log_saves_itself_when_it_reaches_its_limit(logging_project, tmp_path):
    sd = tmp_path / "sd"
    run(logging_project, seconds=2.5, VEXSIM_SD_DIR=sd, KEEP_GOING=1, LOG_LIMIT_S=1)
    assert len(RobotLog.read(sd / "vexsim_0001_left_40.csv")) == 100


def test_without_a_card_the_log_goes_to_the_terminal(logging_project):
    lines, _ = run(logging_project)
    logs = RobotLog.parse_all("\n".join(lines))
    assert len(logs) == 1 and logs[0].info["name"] == "Left 40" and len(logs[0]) == 101
    assert logs[0].marks == [(500.0, "half way")]


# --- the command line --------------------------------------------------------------------


def test_the_logger_is_added_to_a_project(tmp_path, capsys):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    assert main(["logger", "add", str(project)]) == 0
    out = capsys.readouterr().out
    assert "vexsim_log.hpp: new" in out and '#include "vexsim_log.hpp"' in out
    for path, text in logger_files(project):
        assert path.read_text() == text
    assert main(["logger", "add", str(project)]) == 0
    assert "vexsim_log.cpp: same" in capsys.readouterr().out
    (project / "src" / "vexsim_log.cpp").write_text("// changed\n")
    assert [state for _, state in add_logger(project)] == ["same", "updated"]
    assert main(["logger", "add", str(tmp_path / "nowhere")]) == 1


def test_a_run_takes_a_folder_for_the_sd_card(tmp_path):
    args = build_parser().parse_args(["run", "robot.yaml", "--program", "p", "--sd", "card"])
    spec = RunSpec.from_args(args)
    assert spec.sd == "card" and spec.to_args()[-2:] == ["--sd", "card"]
    assert spec.resolved(tmp_path).sd == str(tmp_path / "card")


def test_the_cli_runs_a_program_with_its_card(logging_project, in_cache, tmp_path):
    sd = tmp_path / "card"
    with in_cache():
        args = ["run", str(EXAMPLE_ROBOT), "--program", str(logging_project.project), "--headless"]
        assert main([*args, "--sd", str(sd)]) == 0
    assert RobotLog.read(sd / "vexsim_0001_left_40.csv").info["name"] == "Left 40"

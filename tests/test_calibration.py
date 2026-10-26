"""Phase 10: robot logs, the calibration routine, replays, and fitting parameters to logs.

The "real" robot here is the simulator with changed parameters and default
sensor noise: the fit must recover the parameters, and the fitted model must
reproduce a different run, which it never saw, within tolerance.
"""

import math
import re

import numpy as np
import pytest

from tests.conftest import EXAMPLE_ROBOT, ROOT
from vexsim.algorithms.localization.base import Pose
from vexsim.bridge.program import CppProgram
from vexsim.calibration.cpp import generate
from vexsim.calibration.fit import battery_resistance, compare, fit
from vexsim.calibration.log import BEGIN, END, RobotLog, columns_for
from vexsim.calibration.replay import replay
from vexsim.calibration.routine import (
    Step,
    motor_millivolts,
    run_routine,
    schedule,
    standard_routine,
)
from vexsim.cli import main
from vexsim.config import load_robot
from vexsim.runtime.simulation import Simulation

CONFIG = load_robot(EXAMPLE_ROBOT)
ROBOTS = ROOT / "examples" / "robots"
PROJECT = ROOT / "examples" / "pros_projects" / "calibration"
TRUTH = {  # the "real" robot: slippier, draggier, grippier sideways than the defaults
    "wheel.omni.longitudinal_mu": 0.75,
    "wheel.omni.lateral_mu": 0.28,
    "wheel.omni.rolling_resistance": 0.14,
    "battery.internal_resistance_ohm": 0.15,
}
SHORT = [  # the routine's informative steps, for speed
    Step("settle", 0.3),
    Step("launch", 0.5, forward=0.6),
    Step("coast", 0.8),
    Step("reverse", 0.8, forward=-0.5),
    Step("brake", 0.4, brake="brake"),
    Step("spin", 0.8, turn=0.6),
    Step("arc", 0.8, forward=0.55, turn=-0.3),
    Step("coast", 0.6),
]
HELD_OUT = [  # a different drive the fit never sees
    Step("settle", 0.3),
    Step("forward", 0.9, forward=0.4),
    Step("arc left", 1.0, forward=0.5, turn=0.25),
    Step("arc right", 1.0, forward=0.5, turn=-0.25),
    Step("coast", 0.7),
    Step("back", 0.8, forward=-0.4, turn=0.1),
    Step("brake", 0.4, brake="brake"),
]


@pytest.fixture(scope="module")
def real_log():
    return run_routine(CONFIG, SHORT, overrides=TRUTH, seed=1)


@pytest.fixture(scope="module")
def fitted(real_log):
    return fit(CONFIG, real_log)


def travel(log: RobotLog) -> tuple[float, float, float]:
    """End-of-run totals: the IMU's heading change and both tracking wheels' rotation."""
    return (
        log["imu10_deg"][-1] - log["imu10_deg"][0],
        (log["r11_cdeg"][-1] - log["r11_cdeg"][0]) / 100,
        (log["r12_cdeg"][-1] - log["r12_cdeg"][0]) / 100,
    )


# --- the log format ---------------------------------------------------------------------


def test_columns_follow_the_config():
    columns = columns_for(CONFIG)
    assert columns[:3] == ["time_ms", "battery_mv", "battery_ma"]
    assert columns[3:11] == [
        "m1_cmd_mv", "m1_cmd_rpm", "m1_brake", "m1_deg", "m1_rpm", "m1_ma", "m1_mv", "m1_temp",
    ]  # fmt: skip
    assert columns[-4:] == ["imu10_deg", "r11_cdeg", "r12_cdeg", "d13_mm"]


def test_log_round_trip_and_extraction(real_log, tmp_path):
    again = RobotLog.read(real_log.write(tmp_path / "log.csv"))
    assert list(again.columns) == list(real_log.columns)
    for name, values in real_log.columns.items():
        np.testing.assert_allclose(again[name], values, rtol=1e-5, equal_nan=True)
    # Cut out of console output: timestamps, other prints and a garbled line around it.
    lines = real_log.to_csv().splitlines()
    console = ["[   0.10] starting", "[   9.90] " + BEGIN]
    console += [f"[   9.90] {line}" for line in lines[:50]]
    console += ["[   9.91] 12,garbled", f"[   9.91] {END}", "[   9.95] done"]
    cut = RobotLog.parse("\n".join(console))
    assert len(cut) == 49 and cut.skipped_lines == 1
    assert cut.ports("m") == [1, 2, 3, 4, 5, 6] and cut.ports("imu") == [10]
    with pytest.raises(ValueError, match="no robot log"):
        RobotLog.parse("nothing here")
    # Captured with Windows PowerShell's `>`: UTF-16 with a byte-order mark.
    (tmp_path / "ps.txt").write_text("\r\n".join(console), encoding="utf-16")
    assert len(RobotLog.read(tmp_path / "ps.txt")) == 49


# --- the routine ------------------------------------------------------------------------


def test_routine_voltages_follow_the_kinematics():
    launch = Step("launch", 1.0, forward=1.0)
    mv = motor_millivolts(CONFIG, launch)
    assert mv == {1: 12000, 2: 12000, 3: 12000, 4: -12000, 5: -12000, 6: -12000}  # raw
    spin = motor_millivolts(CONFIG, Step("spin", 1.0, turn=0.5))
    assert spin[1] == -6000 and spin[4] == -6000  # left back, right forward (raw reversed)
    plan = schedule(CONFIG, SHORT)
    assert [t for t, _, _ in plan][:3] == [0, 300, 800]
    assert plan[-1][1].name == "end" and plan[-1][0] == 5000


def test_routine_adds_strafing_for_holonomic_robots():
    xdrive = load_robot(ROBOTS / "xdrive_4m.yaml")
    assert "strafe" in [s.name for s in standard_routine(xdrive)]
    assert "strafe" not in [s.name for s in standard_routine(CONFIG)]


@pytest.mark.parametrize("name", ["full_omni_6m", "mecanum_4m", "xdrive_4m"])
def test_routine_stays_near_its_start(name):
    path = []
    run_routine(load_robot(ROBOTS / f"{name}.yaml"), truth=path)
    assert max(math.hypot(x, y) for x, y, _ in path) < 50  # in: fits a field from its center


# --- replays ------------------------------------------------------------------------------


def test_replay_reproduces_a_log_with_the_same_parameters(real_log):
    rms, sim = compare(CONFIG, real_log, TRUTH)
    assert rms["motor velocity"] < 5  # rpm: the log's own sensor noise
    assert rms["motor current"] < 0.01  # A
    assert rms["heading rate"] < 1.5  # deg/s
    assert rms["tracking wheels"] < 20  # deg/s (scrub and per-device errors in the "real" log)
    wrong, _ = compare(CONFIG, real_log)
    assert wrong["heading rate"] > 5 * rms["heading rate"]


def test_replay_without_logged_commands_uses_measured_voltages(real_log):
    blind = RobotLog({k: v.copy() for k, v in real_log.columns.items()})
    for port in blind.ports("m"):
        blind.columns[f"m{port}_cmd_mv"][:] = np.nan  # e.g. the background logger
    rms, _ = compare(CONFIG, blind, TRUTH)
    assert rms["motor velocity"] < 6 and rms["heading rate"] < 2


def test_battery_resistance_comes_from_the_log(real_log):
    assert battery_resistance(real_log) == pytest.approx(0.15, rel=0.03)


# --- fitting --------------------------------------------------------------------------------


def test_fit_recovers_the_real_parameters(fitted):
    for name in ("wheel.omni.longitudinal_mu", "wheel.omni.lateral_mu"):
        assert fitted.after[name] == pytest.approx(TRUTH[name], rel=0.04), name
    assert fitted.after["wheel.omni.rolling_resistance"] == pytest.approx(0.14, rel=0.06)
    assert fitted.direct["battery.internal_resistance_ohm"] == pytest.approx(0.15, rel=0.03)
    assert fitted.age_ms == 10  # the routine logs readings published 5 ms after a 10 ms sample
    assert fitted.rms_after["heading rate"] < fitted.rms_before["heading rate"] / 5


def test_fitted_model_reproduces_a_run_it_never_saw(fitted):
    held_out = run_routine(CONFIG, HELD_OUT, overrides=TRUTH, seed=2)
    real = travel(held_out)
    default = travel(replay(CONFIG, held_out))
    calibrated = travel(replay(CONFIG, held_out, fitted.overrides))
    heading, vertical, horizontal = (abs(a - b) for a, b in zip(calibrated, real, strict=True))
    assert heading < 3.0  # degrees of total turn
    assert vertical < 10.0 and horizontal < 10.0  # degrees of tracking wheel rotation (~0.2 in)
    assert abs(default[0] - real[0]) > 3 * heading  # the defaults were clearly off


def test_fit_rejects_unknown_parameters(real_log):
    with pytest.raises(ValueError, match="unknown"):
        fit(CONFIG, real_log, ["wheel.omni.grip"])
    with pytest.raises(ValueError, match="only physics"):
        fit(CONFIG, real_log, ["sensor.imu.scale_error"])


# --- the C++ routine --------------------------------------------------------------------------


def test_example_project_matches_the_generator():
    header, source = generate(CONFIG)
    assert (PROJECT / "include" / "vexsim_calibration.hpp").read_text() == header
    assert (PROJECT / "src" / "vexsim_calibration.cpp").read_text() == source


def test_cpp_routine_logs_what_the_python_routine_logs(build, tmp_path):
    exe = build(PROJECT).executable
    lines = []
    sim = Simulation(CONFIG, program=CppProgram(exe), start=Pose(0, 0, 0), echo=lines.append)
    sim.start("autonomous")
    try:
        assert sim.run_until_finished(20.0)
    finally:
        sim.close()
    log = RobotLog.parse("\n".join(lines))
    assert list(log.columns) == columns_for(CONFIG)
    expected = run_routine(CONFIG)
    assert len(log) == len(expected)
    np.testing.assert_array_equal(log["m1_cmd_mv"], expected["m1_cmd_mv"])
    np.testing.assert_array_equal(log["m4_brake"], expected["m4_brake"])
    rms, _ = compare(CONFIG, log)  # the C++ code ran on the default model
    assert rms["motor velocity"] < 5 and rms["motor current"] < 0.01
    assert rms["heading rate"] < 1.5


# --- the command line -----------------------------------------------------------------------


def test_calibration_commands(real_log, tmp_path, capsys):
    project = tmp_path / "project"
    assert main(["calibration-routine", str(ROBOTS / "xdrive_4m.yaml"), str(project)]) == 0
    source = (project / "src" / "vexsim_calibration.cpp").read_text()
    assert '{"strafe", 600, 0,' in source and "imu_reset_blocking(10)" in source
    capsys.readouterr()

    path = real_log.write(tmp_path / "log.csv")
    assert main(["calibrate", str(EXAMPLE_ROBOT), str(path), "--fit", "none"]) == 0
    out = capsys.readouterr().out
    assert "Robot log: 500 rows (5.0 s): 6 motors, 2 rotation sensors, 1 IMU" in out
    assert re.search(r"heading rate \(deg/s\): [\d.]+", out)

    args = ["calibrate", str(EXAMPLE_ROBOT), str(path), "--fit", "wheel.omni.lateral_mu"]
    out_dir = tmp_path / "out"
    assert main([*args, "--max-iterations", "2", "--workers", "1", "--out", str(out_dir)]) == 0
    out = capsys.readouterr().out
    assert "wheel.omni.lateral_mu" in out and "battery.internal_resistance_ohm: 0.15" in out
    overrides = (out_dir / "overrides.yaml").read_text()
    assert re.match(r"overrides:\n  wheel.omni.lateral_mu: 0\.\d+\n  battery", overrides)
    assert (tmp_path / "out" / "simulated.csv").exists()

    assert main(["calibrate", str(EXAMPLE_ROBOT), str(tmp_path / "missing.csv")]) == 1


def test_run_writes_a_robot_log(tmp_path, capsys):
    out = tmp_path / "robot.csv"
    program = ROOT / "examples" / "programs" / "tour.py"
    args = ["run", str(EXAMPLE_ROBOT), "--program", str(program), "--headless", "--seconds", "3"]
    assert main([*args, "--robot-log", str(out)]) == 0
    log = RobotLog.read(out)
    assert len(log) == 300 and log.ports("r") == [11, 12]
    assert np.isfinite(log["m1_cmd_mv"]).any()  # the chassis' voltage commands were recorded

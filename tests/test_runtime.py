"""Phase 5: running programs, competition modes, scripted input, telemetry, and the CLI."""

import math
import types

import pytest

from tests.conftest import EXAMPLE_ROBOT, ROOT
from vexsim.algorithms.localization.base import Pose
from vexsim.api import delay
from vexsim.cli import main
from vexsim.config import load_robot
from vexsim.runtime.program import load_program
from vexsim.runtime.recorder import Log
from vexsim.runtime.simulation import ScriptedInput, Simulation

CONFIG = load_robot(EXAMPLE_ROBOT)
TOUR = ROOT / "examples" / "programs" / "tour.py"


def run_program(mode="autonomous", seconds=None, **functions):
    sim = Simulation(CONFIG, program=types.SimpleNamespace(**functions), noise="ideal", echo=None)
    sim.start(mode)
    if seconds is None:
        assert sim.run_until_finished(30)
    else:
        sim.run_for(seconds)
    return sim


def test_delay_timing_and_bare_yield():
    stamps = []

    def autonomous(bot):
        stamps.append(bot.millis())
        yield delay(250)
        stamps.append(bot.millis())
        yield
        stamps.append(bot.millis())
        yield delay(1)
        stamps.append(bot.millis())

    run_program(autonomous=autonomous)
    start = stamps[0]
    assert [s - start for s in stamps] == [0, 250, 260, 261]


def test_default_initialize_waits_for_the_imu():
    started = []

    def autonomous(bot):
        started.append(bot.millis())
        yield

    sim = run_program(autonomous=autonomous)
    assert 2000 <= started[0] <= 2100
    assert sim.localizer_ready


def test_plain_functions_and_custom_initialize():
    log = []

    def initialize(bot):
        log.append("init")  # not a generator: runs once, no waiting

    def autonomous(bot):
        log.append(bot.millis())

    run_program(initialize=initialize, autonomous=autonomous)
    assert log[0] == "init" and log[1] < 10


def test_match_mode_cuts_autonomous_at_15_seconds():
    phases = []

    def autonomous(bot):
        phases.append(("auton", bot.millis()))
        while True:
            yield delay(100)

    def opcontrol(bot):
        phases.append(("driver", bot.millis()))
        yield delay(50)

    sim = run_program("match", autonomous=autonomous, opcontrol=opcontrol)
    (_, auton_start), (_, driver_start) = phases
    assert driver_start - auton_start == pytest.approx(15000, abs=2)
    assert sim.phase == "done"


def test_program_errors_propagate():
    def autonomous(bot):
        yield
        raise RuntimeError("bad auton")

    with pytest.raises(RuntimeError, match="bad auton"):
        run_program(autonomous=autonomous)

    def yields_garbage(bot):
        yield 42

    with pytest.raises(TypeError, match="yield delay"):
        run_program(autonomous=yields_garbage)


def test_driver_mode_with_scripted_input_uses_default_arcade():
    inputs = ScriptedInput([(2.5, {"LEFT_Y": 127}, set()), (3.5, {}, set())])
    sim = Simulation(CONFIG, input_source=inputs, noise="ideal", echo=None)
    sim.start("driver")
    sim.run_for(3.5)
    assert sim.robot.body_velocity[0] > 1.5  # driving forward at the 3.5 s release
    sim.run_for(2.5)  # releasing the stick sends 0 V: the default brake mode coasts to a stop
    x, y, heading = sim.robot.pose
    assert x > 0.5 and abs(y) < 0.01 and abs(heading) < 0.01
    assert abs(sim.robot.body_velocity[0]) < 0.01


def test_scripted_input_from_csv(tmp_path):
    path = tmp_path / "inputs.csv"
    path.write_text("time_s,LEFT_Y,RIGHT_X,buttons\n0,0,0,\n1.0,100,-20,R1 A\n2.0,0,0,\n")
    inputs = ScriptedInput.from_csv(path)
    assert inputs.poll(0.5) == ({"LEFT_Y": 0.0, "RIGHT_X": 0.0}, set())
    assert inputs.poll(1.5) == ({"LEFT_Y": 100.0, "RIGHT_X": -20.0}, {"R1", "A"})


def test_recorder_and_log_roundtrip(tmp_path):
    def autonomous(bot):
        yield from bot.chassis.move_to_point(20, 0)

    sim = run_program(autonomous=autonomous)
    path = sim.recorder.write_csv(tmp_path / "run.csv")
    log = Log.read(path)
    assert len(log) == len(sim.recorder.rows) > 200
    assert log.motor_ports == [1, 2, 3, 4, 5, 6]
    assert log["x_in"][-1] == pytest.approx(Pose.from_si(sim.robot.pose).x, abs=0.5)
    assert set(log.phase) >= {"initialize", "autonomous"}
    assert math.isnan(log["est_x_in"][0])  # no estimate until the IMU calibrated


def test_example_tour_program_runs():
    sim = Simulation(CONFIG, program=load_program(TOUR), seed=1, echo=None)
    sim.start("autonomous")
    assert sim.run_until_finished(40)
    assert any("autonomous done" in line for line in sim.console)
    end = Pose.from_si(sim.robot.pose)
    assert math.hypot(end.x, end.y) < 6  # the tour ends near where it started


def test_cli_run_headless(tmp_path, capsys):
    record, shot = tmp_path / "run.csv", tmp_path / "end.png"
    args = ["run", str(EXAMPLE_ROBOT), "--program", str(TOUR), "--headless", "--seconds", "4",
            "--record", str(record)]  # fmt: skip
    pytest.importorskip("pygame")
    args += ["--screenshot", str(shot)]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "true pose" in out and record.exists() and shot.read_bytes()[:4] == b"\x89PNG"

    plot = tmp_path / "telemetry.png"
    pytest.importorskip("matplotlib")
    assert main(["plot", str(record), "--out", str(plot)]) == 0
    assert plot.stat().st_size > 20_000

    replay = tmp_path / "replay.png"
    assert main(["replay", str(EXAMPLE_ROBOT), str(record), "--headless", "--at", "3",
                 "--screenshot", str(replay)]) == 0  # fmt: skip
    assert replay.exists()


def test_cli_rejects_bad_inputs(tmp_path, capsys):
    assert main(["plot", str(tmp_path / "nope.csv"), "--out", str(tmp_path / "x.png")]) == 1
    with pytest.raises(SystemExit):
        main(["run", str(EXAMPLE_ROBOT), "--start", "1,2", "--headless"])

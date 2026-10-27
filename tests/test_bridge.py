"""The C++ bridge: building PROS projects, the lockstep scheduler, and PROS device semantics.

They need g++ (see conftest.py for how they skip without one).
"""

from __future__ import annotations

import math
import os
import re
import shutil
import time
from pathlib import Path

import pytest

from vexsim.algorithms.localization.base import Pose
from vexsim.bridge.build import BuildError, build_project
from vexsim.bridge.host import HostError, RobotHost
from vexsim.bridge.program import CppProgram
from vexsim.config import load_robot
from vexsim.physics.motor import BrakeMode
from vexsim.runtime.simulation import ScriptedInput, Simulation
from vexsim.units import rad_s_to_rpm

ROOT = Path(__file__).resolve().parents[1]
ROBOT = ROOT / "examples" / "robots" / "full_omni_6m.yaml"
EXAMPLE = ROOT / "examples" / "pros_projects" / "minimal_pros4"
TEST_PROJECT = Path(__file__).parent / "cpp" / "bridge_test"


@pytest.fixture(scope="session")
def test_exe(build):
    return build(TEST_PROJECT).executable


@pytest.fixture(scope="session")
def example_exe(build):
    return build(EXAMPLE).executable


def run_host(exe, scenario, *, until_ms=500, modes=((0, "initialize", 0),), busy_timeout_s=5.0):
    """Run a scenario in a host with no devices: [(time_ms, line)], finished serials."""
    host = RobotHost(exe, [], env={"VEXSIM_TEST": scenario}, busy_timeout_s=busy_timeout_s)
    out = [(None, line) for line in host.startup.console]
    pending = sorted(modes)
    serial, finished, wake = 0, [], 0
    try:
        while True:
            due = ([wake] if wake is not None else []) + ([pending[0][0]] if pending else [])
            if not due or min(due) > until_ms:
                break
            t = min(due)
            lines = []
            while pending and pending[0][0] <= t:
                serial += 1
                _, name, status = pending.pop(0)
                lines.append(f"MODE {serial} {name} {status}")
            reply = host.run(t * 1000, lines)
            out += [(t, line) for line in reply.console]
            finished += reply.finished
            wake = None if reply.next_wake_us is None else reply.next_wake_us // 1000
    finally:
        host.close()
    return out, finished


def lines(out):
    return [line for _, line in out]


# --- building -----------------------------------------------------------------------------------


def test_example_builds_unchanged_ignoring_its_sdk_headers(example_exe):
    # The example ships stand-ins for include/api.h and include/pros/ that #error if used.
    assert example_exe.is_file()


def test_build_is_incremental(build, tmp_path):
    project = tmp_path / "proj"
    shutil.copytree(EXAMPLE, project)
    first = build(project)
    assert (first.compiled, first.total, first.kernel) == (2, 2, "4.2.1")
    assert build(project).compiled == 0
    later = time.time() + 10
    os.utime(project / "src" / "main.cpp", (later, later))
    assert build(project).compiled == 1
    os.utime(project / "include" / "drive.hpp", (later + 10, later + 10))
    assert build(project).compiled == 2  # both sources include it


def test_compile_errors_point_at_the_project(build, tmp_path):
    project = tmp_path / "broken"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.cpp").write_text('#include "api.h"\nvoid f() { undefined_thing(); }\n')
    with pytest.raises(BuildError) as err:
        build(project)
    assert str(project / "src" / "main.cpp") in str(err.value)
    assert "undefined_thing" in str(err.value)
    assert "stage" not in str(err.value)


def test_cpp_linkage_competition_function_is_reported(build, tmp_path):
    project = tmp_path / "linkage"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.cpp").write_text('#include "api.h"\nvoid autonomous() {}\n')
    result = build(project)
    assert any("autonomous() with C++ linkage" in note for note in result.notes)


def test_toolchain_programs_run_with_their_folder_on_path(tmp_path):
    # MSYS2's g++ helpers need DLLs from g++'s own folder, which may not be on PATH.
    import sys

    from vexsim.bridge.build import _run

    script = tmp_path / "bin" / "show_path.py"
    script.parent.mkdir()
    script.write_text("import os; print(os.environ['PATH'])")
    out = _run([sys.executable, str(script)]).stdout
    assert out.split(os.pathsep)[0] == str(Path(sys.executable).parent)


def test_not_a_project(tmp_path):
    with pytest.raises(BuildError, match="not a PROS project"):
        build_project(tmp_path / "nothing")


# --- lockstep scheduler -------------------------------------------------------------------------


def test_delay_wakes_exactly_on_time(test_exe):
    out, finished = run_host(test_exe, "delay")
    assert lines(out) == ["tick 0", "tick 7", "tick 14", "tick 21"]
    assert finished == [1]
    assert [t for t, _ in out] == [0, 7, 14, 21]


def test_delay_until_keeps_the_period(test_exe):
    out, _ = run_host(test_exe, "delay_until")
    assert lines(out) == ["loop 0", "loop 10", "loop 20", "loop 30"]


def test_higher_priority_runs_first(test_exe):
    out, _ = run_host(test_exe, "priority")
    assert lines(out) == ["high 10", "low 10"]


def test_preemption_and_same_priority_order(test_exe):
    out, _ = run_host(test_exe, "preempt")
    assert lines(out) == [
        "child runs",
        "parent continues",
        "parent before delay",
        "same priority runs",
    ]


def test_mutex_blocks_times_out_and_hands_over(test_exe):
    out, _ = run_host(test_exe, "mutex")
    assert lines(out) == [
        "holder took 0",
        "try for 20 ms: 0 at 30",
        "wait: 1 at 50",
        "take while held: 0",
        "recursive: 1 1 1 1 0",
    ]


def test_notifications(test_exe):
    out, _ = run_host(test_exe, "notify")
    assert lines(out) == ["woken 30 value 1", "timed out 45 value 0"]


def test_join_waits_for_the_task_to_end(test_exe):
    out, _ = run_host(test_exe, "join")
    assert lines(out) == ["joined 40 state 4"]  # E_TASK_STATE_DELETED


def test_suspend_resume_and_remove(test_exe):
    out, _ = run_host(test_exe, "suspend")
    assert lines(out) == ["count 0", "count 10", "count 20", "count 55", "removed 60 state 4"]


def test_busy_wait_on_the_clock_advances_time(test_exe):
    out, _ = run_host(test_exe, "spin")
    assert lines(out) == ["spun until 25"]


def test_infinite_loop_is_reported(test_exe):
    with pytest.raises(HostError, match=r"hung: task 'User Initialization \(PROS\)'"):
        run_host(test_exe, "busy", busy_timeout_s=0.5)


def test_crash_is_reported_with_task_and_console(test_exe):
    with pytest.raises(HostError, match="crashed in task 'crasher': segmentation fault") as err:
        run_host(test_exe, "crash")
    assert "about to crash" in err.value.console


def test_uncaught_exception_is_reported(test_exe):
    with pytest.raises(HostError, match="uncaught C\\+\\+ exception") as err:
        run_host(test_exe, "throw")
    assert any("boom" in line for line in err.value.console)


def test_console_output_is_captured(test_exe):
    out, _ = run_host(test_exe, "console")
    assert (None, "from a global constructor") in out
    assert lines(out)[1:] == ["no newline yet... done", "cout line", "stderr line"]


def test_mode_changes_kill_the_competition_task_but_not_user_tasks(test_exe):
    out, finished = run_host(
        test_exe,
        "competition",
        until_ms=520,
        modes=[
            (0, "initialize", 5),
            (10, "autonomous", 6),
            (350, "opcontrol", 4),
            (400, "disabled", 5),
        ],
    )
    assert lines(out) == [
        "background 0",
        "autonomous 10 status 6",
        "background 100",
        "autonomous 110 status 6",
        "background 200",
        "autonomous 210 status 6",
        "background 300",
        "autonomous 310 status 6",
        "opcontrol 350 status 4",
        "background 400",
        "disabled 400 status 5",
        "background 500",
    ]
    assert finished == [1, 3, 4]  # autonomous (2) never returned: it was deleted


# --- devices, through the simulation ------------------------------------------------------------


def sim_run(exe, scenario, seconds, *, mode="driver", **kwargs) -> Simulation:
    program = CppProgram(exe, env={"VEXSIM_TEST": scenario})
    sim = Simulation(load_robot(ROBOT), program=program, seed=0, echo=None, **kwargs)
    sim.start(mode)
    try:
        sim.run_for(seconds)
    finally:
        sim.close()
    return sim


def console(sim: Simulation) -> list[str]:
    return [re.sub(r"^\[\s*[\d.]+\] ", "", line) for line in sim.console]


def test_reversed_ports_drive_straight(test_exe):
    sim = sim_run(test_exe, "drive", 1.2)
    out = console(sim)
    left, right = (float(v) for v in re.match(r"left (\S+) right (\S+)", out[0]).groups())
    assert left > 1000 and right == pytest.approx(left, rel=0.05)
    rotation = int(out[1].split()[1])
    assert rotation > 0 and out[2] == f"reversed rotation {-rotation}"
    pose = Pose.from_si(sim.robot.pose)
    assert pose.x > 20 and abs(pose.y) < 1 and abs(pose.heading) < 2


def test_zero_position_follows_pros4(test_exe):
    # One motor drags the whole robot here, so it settles a few degrees off target.
    out = console(sim_run(test_exe, "zero", 3.2))
    assert float(out[0].split()[1]) == pytest.approx(100, abs=8)
    assert out[1] == "after set_zero_position(80): 80"  # the current position now reads 80
    moved, target = re.fullmatch(r"moved to (\S+) target (\S+)", out[2]).groups()
    assert float(moved) == pytest.approx(100, abs=8) and target == "100"
    assert re.fullmatch(r"after tare: -?0 reversed object: -?0", out[3])
    assert float(out[4].split()[1]) == pytest.approx(1.0, abs=0.03)


def test_declared_gearing_scales_like_the_real_motor(test_exe):
    # Declaring green on blue cartridges: the firmware holds "100 rpm" by its own count,
    # so the motors really turn 3x faster, and report a third of their true speed.
    sim = sim_run(test_exe, "gearing", 1.001)
    out = console(sim)
    assert any("port 1: the code declares the green (200 rpm) cartridge" in line for line in out)
    reported = float(re.search(r"reported (\S+) rpm", " ".join(out)).group(1))
    assert reported == pytest.approx(100, abs=5)
    assert rad_s_to_rpm(sim.robot.motors[1].velocity) == pytest.approx(3 * reported, rel=0.05)


def test_motor_group_setters_affect_only_the_first_motor(test_exe):
    sim = sim_run(test_exe, "group_brake", 0.05)
    assert console(sim) == ["left modes 2 0 0"]
    modes = {p: sim.robot.motors[p].brake_mode for p in range(1, 7)}
    assert [modes[1], modes[2], modes[3]] == [BrakeMode.HOLD, BrakeMode.COAST, BrakeMode.COAST]
    assert all(modes[p] is BrakeMode.BRAKE for p in (4, 5, 6))


def test_imu_offsets_and_calibration(test_exe):
    out = console(sim_run(test_exe, "imu", 2.5))
    assert out == [
        "calibrating 0 rotation 0.0",
        "heading 90.0 rotation 0.0",
        "reset took 2005 ms, heading 90.0",  # PROS keeps the heading offset across a reset
        "during calibration: PROS_ERR_F errno EAGAIN",
    ]


def test_wrong_and_unsimulated_devices(test_exe):
    out = console(sim_run(test_exe, "missing", 0.05))
    assert "move on empty port: PROS_ERR errno ENODEV" in out
    assert "imu on motor port: PROS_ERR_F errno ENODEV" in out
    assert "piston extended 1" in out
    warnings = " ".join(line for line in out if line.startswith("vexsim:"))
    assert "port 7: the code uses a motor here, but the robot config has nothing" in warnings
    assert "port 1: the code uses an IMU here, but the robot config has a motor" in warnings
    assert "three-wire (ADI) devices are not simulated" in warnings


def test_controller_screens_and_new_press(test_exe):
    inputs = ScriptedInput(
        [(0.0, {"LEFT_Y": 50}, set()), (0.03, {"LEFT_Y": 100}, {"A"}), (0.07, {}, set())]
    )
    sim = sim_run(test_exe, "controller", 0.2, input_source=inputs)
    assert console(sim) == [
        "t 0 LY 50 A 0 new 0",
        "t 20 LY 50 A 0 new 0",
        "t 40 LY 100 A 1 new 1",
        "t 60 LY 100 A 1 new 0",
        "t 80 LY 0 A 0 new 0",
        "t 100 LY 0 A 0 new 0",
    ]
    assert sim.controller_screen[0].rstrip() == "hello 7"
    assert sim.lcd[3] == "lcd 3"


def test_disabled_robot_ignores_motor_commands(test_exe):
    # "autonomous" mode: initialize runs while field control has the robot disabled.
    sim = sim_run(test_exe, "disabled", 0.6, mode="autonomous")
    assert console(sim) == ["moved 0"]


def test_api_surface_and_c_sources(test_exe):
    out = console(sim_run(test_exe, "kitchen_sink", 0.1))
    assert "group ports 1 2 3" in out  # {1, -2} + 3 + -2, minus 3, then none reversed
    assert "counts per rev 300" in out
    assert "partner connected 0" in out
    assert "adi 0 0 0 0" in out
    assert "unsupported 2147483647 1 2147483647 2147483647" in out  # PROS_ERR
    assert "battery 100% comp 0 usd 0" in out
    assert "imu q.w 1.00" in out
    assert "devices 10 motors 6 imus 1" in out
    assert "c api 5" in out
    # Warnings come out in order with the code's own output.
    unsupported = out.index("unsupported 2147483647 1 2147483647 2147483647")
    for device in ("pros::Optical", "pros::Vision", "pros::Serial"):
        warning = f"vexsim: {device} is not simulated yet: its calls fail with errno ENODEV"
        assert out.index("battery 100% comp 0 usd 0") > out.index(warning) < unsupported
    gps = [line for line in out if line.startswith("vexsim: port 6: the code uses a GPS sensor")]
    assert len(gps) == 1 and out.index(gps[0]) < unsupported  # simulated, but not on port 6


def test_lvgl_stand_in_runs_screen_code(test_exe):
    assert console(sim_run(test_exe, "lvgl", 0.01)) == [
        'label "auton 3" on screen 2 size 110 x 200 clicks 0',  # nobody touches the screen
        "logo 2x1 format 0x12",
        "after delete 1",
        "sqrtf 4.0 sinf 0.0",
    ]


def test_the_simulation_seed_reaches_the_program(test_exe):
    program = CppProgram(test_exe, env={"VEXSIM_TEST": "seed"})
    sim = Simulation(load_robot(ROBOT), program=program, seed=42, echo=None)
    sim.start("driver")
    sim.run_for(0.01)
    sim.close()
    assert console(sim) == ["seed 42"]


def test_reported_pose_becomes_the_estimate(test_exe):
    sim = sim_run(test_exe, "report_pose", 0.05)
    # LemLib convention (theta clockwise from +y) -> vexsim's (counter-clockwise from +x)
    assert sim.estimated_pose == Pose(12, 24, 0)
    assert sim.recorder.rows[-1][5:8] == [12, 24, 0]  # in the telemetry log too
    error = sim.recorder.pose_error()
    assert error.final_in == pytest.approx(math.hypot(12, 24)) and error.max_deg == 0


def test_robot_code_draws_on_the_field(test_exe):
    program = CppProgram(test_exe, env={"VEXSIM_TEST": "draw"})
    sim = Simulation(load_robot(ROBOT), program=program, echo=None)
    sim.start("driver")
    try:
        sim.run_for(0.005)
        assert sim.drawings.snapshot() == {
            "mcl": [["point", 1, 2, "violet", 3], ["point", 3, 4, "aqua", 5]],
            "rays": [["line", 0, 0, 10, 0, "yellow"]],
        }
        version = sim.drawings.version
        sim.run_for(0.02)
    finally:
        sim.close()
    assert sim.drawings.version > version
    # angles as LemLib's in C++ (clockwise from +y), counter-clockwise from +x here
    assert sim.drawings.snapshot() == {
        "mcl": [
            ["circle", 5, 6, 2.5, "violet"],
            ["ellipse", 5, 6, 4, 2, -30, "blue"],
            ["text", -1.5, 2, "spread 2.5 in max", "muted"],
        ],
        "rays": [["line", 0, 0, 10, 0, "yellow"]],
        "my_layer": [["pose", 12, 24, 0, "orange"]],
    }


def test_example_autonomous_is_deterministic(example_exe, capsys):
    def run():
        start = Pose(0, 0, 90)
        sim = Simulation(load_robot(ROBOT), program=CppProgram(example_exe), seed=3, start=start)
        sim.start("autonomous")
        assert sim.run_until_finished(30)
        sim.close()
        return console(sim), sim.robot.pose, sim.recorder.rows

    first, second = run(), run()
    assert first[0] == second[0]
    assert first[1] == second[1]
    assert first[2] == second[2]
    assert first[0][0].startswith("initialized at 2005 ms")
    end = Pose.from_si(first[1])
    assert abs(end.x) < 3 and abs(end.y) < 3  # drove a 24 in square back to the start

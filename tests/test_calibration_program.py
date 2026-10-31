"""Phase 14.3: the calibration program (bridge/cpp/calibration/main.cpp, and the header
calibration/program.py writes for a robot), run in vexsim from its menu by a simulated
student (calibration/student.py), on 1239E's robot and field.

The program's tests build it, so they need g++."""

from pathlib import Path
from typing import NamedTuple

import numpy as np
import pytest

from tests.conftest import ROOT
from vexsim.bridge.program import CppProgram
from vexsim.calibration import plan as planning
from vexsim.calibration.log import RobotLog
from vexsim.calibration.plan import MARGIN_IN, PUSH_MARGIN_IN, make_plan, shape_samples
from vexsim.calibration.program import (
    PROGRAM,
    ProgramError,
    _devices,
    check_folder,
    header_text,
    write_program,
)
from vexsim.calibration.routine import schedule
from vexsim.calibration.student import Student
from vexsim.cli import main
from vexsim.config import load_field, load_robot
from vexsim.runtime.simulation import Simulation

ROBOT = ROOT / "examples" / "robots" / "1239e_2026-27.yaml"
FIELD = ROOT / "examples" / "fields" / "1239e_2026-27.yaml"
CONFIG = load_robot(ROBOT)
FIELD_CONFIG = load_field(FIELD)
SESSION = [
    "device_check",
    "free_spin",
    "imu_still",
    "imu_turns",
    "push",
    "straight",
    "spin",
    "arc",
    "sweep_1",
    "sweep_2",
    "drive",
]
RUNS = {
    "device_check": 1,
    "free_spin": 1,
    "imu_still": 1,
    "imu_turns": 2,
    "push": 2,
    "straight": 3,
    "spin": 3,
    "arc": 3,
    "sweep_1": 1,
    "sweep_2": 1,
}


class Built(NamedTuple):
    folder: Path
    executable: Path


@pytest.fixture(scope="module")
def plan():
    return make_plan(CONFIG, FIELD_CONFIG, workers=4)


@pytest.fixture(scope="module")
def program(plan, build, tmp_path_factory):
    folder = tmp_path_factory.mktemp("calibration") / "program"
    write_program(CONFIG, plan, folder)
    return Built(folder, build(folder).executable)


def run_session(plan, program, tests, sd, real=CONFIG, **options):
    """The program on a robot (``real``: the config it was made for, unless the robot
    differs), the student running ``tests`` from its menu; the student and the simulation."""
    student = Student(plan, CONFIG, tests, **options)
    sim = Simulation(
        real,
        program=CppProgram(program.executable, env={"VEXSIM_SD_DIR": str(sd)}),
        field=FIELD_CONFIG,
        input_source=student,
        start=student.start,
        echo=None,
    )
    student.attach(sim)
    sim.start("driver")
    try:
        assert sim.run_until_finished(900.0)
    finally:
        sim.close()
    assert student.error is None
    return student, sim


@pytest.fixture(scope="module")
def full(plan, program, tmp_path_factory):
    """The whole session, every test from the menu in order."""
    sd = tmp_path_factory.mktemp("sd")
    student, sim = run_session(plan, program, SESSION, sd)
    return student, sim, sd


def logs(sd: Path) -> list[RobotLog]:
    return [RobotLog.read(p) for p in sorted(sd.glob("vexsim_*.csv"))]


def clearance(config, poses) -> float:
    """The least room between the robot's edge, at each pose (in, in, deg), and anything."""
    _, edge = shape_samples(config)
    fmap = planning.FieldMap(FIELD_CONFIG)
    points = np.concatenate([planning._moved(edge, p) for p in poses])
    return float(fmap.distances(points).min())


def miswired():
    """1239E as the config says, but with motor 9 the other way round and the distance
    sensors on ports 1 and 8 plugged into each other's ports."""
    gearing = dict(CONFIG.drivetrain.gearing)
    gearing["left"] = gearing["left"].model_copy(update={"motors": (10, -9)})
    sensors = tuple(
        s.model_copy(update={"port": {1: 8, 8: 1}[s.port]})
        if s.type == "distance" and s.port in (1, 8)
        else s
        for s in CONFIG.sensors
    )
    drivetrain = CONFIG.drivetrain.model_copy(update={"gearing": gearing})
    return CONFIG.model_copy(update={"drivetrain": drivetrain, "sensors": sensors})


# --- the header --------------------------------------------------------------------------------


def test_the_header_holds_the_robot_and_the_plan(plan):
    header = header_text(CONFIG, plan)
    for line in (
        'constexpr const char* ROBOT = "1239E 2026-27";',
        "\t{10, 1, 0, 600, 7.65763, 0.0212712},  // left",
        "\t{19, -1, 1, 600, 7.65763, 0.0212712},  // right",
        '\t{"left", "front"},',
        "\t{12000, 0, -12000},  // 10",  # forward, sideways, turning
        "\t{-12000, 0, -12000},  // 19",
        "constexpr int IMU_PORT = 16;  // 0: none",
        '\t{1, "front left, facing forward"},',
        '\t{18, "back left, facing left"},',
        "constexpr int TRACKING_COUNT = 0;",
        "constexpr double PUSH_IN = 96.0;",
        "constexpr int MENU_COUNT = 10;",
        '\t{"straight", "Straight (3 runs)", 3},',
    ):
        assert line in header
    straight = next(t for t in plan.drive if t.key == "straight")
    rows = schedule(CONFIG, straight.steps)
    for (start, step, mv), (end, _, _) in zip(rows, rows[1:], strict=False):
        volts = ", ".join(str(mv.get(p, 0)) for p in (10, 9, 19, 17))
        brake = int(step.brake == "brake")
        assert f'\t{{"{step.name}", {end - start}, {brake}, {{{volts}}}}},' in header
    assert "{-22.2, -20.45, 0.0, {" in header  # the straight test's spot


def test_tracking_wheels_count_the_way_their_config_says():
    omni = load_robot(ROOT / "examples" / "robots" / "full_omni_6m.yaml")
    lines = _devices(omni)
    assert "\t{11, 1, 0}," in lines  # forward-tracking: counts up pushed forward
    assert "\t{12, 0, 1}," in lines  # sideways: counts up pushed left
    reversed_wheel = omni.model_copy(
        update={
            "sensors": tuple(
                s.model_copy(update={"reversed": True}) if s.port == 11 else s for s in omni.sensors
            )
        }
    )
    assert "\t{11, -1, 0}," in _devices(reversed_wheel)


def test_the_program_goes_in_a_project_of_its_own(plan, tmp_path):
    folder = tmp_path / "calibration"
    check_folder(folder)  # nothing there yet
    (folder / "src").mkdir(parents=True)
    main_cpp = folder / "src" / "main.cpp"
    main_cpp.write_text('void initialize() { pros::lcd::set_text(1, "Hello PROS User!"); }')
    check_folder(folder)  # a new PROS project's
    written = write_program(CONFIG, plan, folder)
    assert [(p.relative_to(folder).as_posix(), s) for p, s in written] == [
        ("src/main.cpp", "updated"),
        ("include/vexsim_calibration_tests.hpp", "new"),
        ("include/vexsim_log.hpp", "new"),
        ("src/vexsim_log.cpp", "new"),
        ("include/main.h", "new"),
    ]
    assert main_cpp.read_text() == PROGRAM.read_text()
    assert {s for _, s in write_program(CONFIG, plan, folder)} == {"same"}
    main_cpp.write_text("void opcontrol() { drive(); }")  # the team's own
    with pytest.raises(ProgramError, match="--force"):
        check_folder(folder)
    check_folder(folder, force=True)
    (folder / "src" / "autons.cpp").write_text("")
    with pytest.raises(ProgramError, match=r"code of its own \(src/autons.cpp\)"):
        check_folder(folder, force=True)


# --- the session, in vexsim ---------------------------------------------------------------------


def test_every_test_runs_from_the_menu_and_logs(full):
    student, sim, sd = full
    found = logs(sd)
    tests = [log.info["test"] for log in found]
    assert tests == [key for key, n in RUNS.items() for _ in range(n)]
    for log in found:
        assert log.info["ended"] == "finished"
        assert log.info["robot"] == "1239E 2026-27" and log.info["program"] == "vexsim calibration"
    check = found[0]
    assert check.info["check"] == "passed" and student.problems == []
    assert [s[1] for s in student.screens if s[1].startswith("done")] == ["done passed"]
    by_name = {log.info["name"]: log for log in found}
    assert set(by_name) >= {"imu_turns_left", "imu_turns_right", "push_forward", "push_back"}
    assert by_name["straight"].info["spot"] == "-22.20 -20.45 0.0"
    assert sim.lcd[1].startswith("Battery") and sim.lcd[1].rstrip().endswith(f"{len(found)} saved")


def test_each_driving_test_stays_clear_of_every_element(full):
    student, _, _ = full
    driving = [
        r for r in student.runs if r.test in ("straight", "spin", "arc", "sweep_1", "sweep_2")
    ]
    assert len(driving) == 11
    for run in driving:
        assert clearance(CONFIG, run.poses[::2]) >= MARGIN_IN
    pushed = [r for r in student.runs if r.test == "push"]
    for run in pushed:
        assert clearance(CONFIG, run.poses[::2]) >= PUSH_MARGIN_IN


def test_on_its_side_the_wheels_spin_up_and_the_robot_stays_put(full):
    student, _, sd = full
    spin = next(log for log in logs(sd) if log.info["test"] == "free_spin")
    k = [text for _, text in spin.marks].index("12 V")
    (begin, _), (end, _) = spin.marks[k], spin.marks[k + 1]
    at_12v = (spin.time_ms > begin + 1000) & (spin.time_ms < end)
    for port in (10, 9, 19, 17):
        assert np.abs(spin[f"m{port}_rpm"][at_12v]).min() > 550  # near a blue motor's free speed
    run = next(r for r in student.runs if r.test == "free_spin")
    xs, ys, _ = np.array(run.poses).T
    assert np.ptp(xs) < 1e-6 and np.ptp(ys) < 1e-6


def test_the_imu_turns_show_the_imus_scale(full):
    _, _, sd = full
    for log in logs(sd):
        if log.info["test"] == "imu_turns":
            turned = log["imu16_deg"][-1] - log["imu16_deg"][0]
            way = -1 if log.info["direction"] == "left" else 1  # PROS: clockwise is +
            assert way * turned == pytest.approx(3600 * (1 + 0.002528), abs=4.0)


def test_a_press_stops_the_motors_at_once(plan, program, tmp_path):
    student, _ = run_session(plan, program, ["straight"], tmp_path, press_during={"straight": 0.8})
    stopped, *finished = [r for r in student.runs if r.test == "straight"]
    assert stopped.how == "stopped: a button or stick"
    assert [r.how for r in finished] == ["finished"] * 3  # a stopped run doesn't count
    pressed = next(t for t, b in student.pressed if b == "B" and t > stopped.began)
    log = logs(tmp_path)[0]
    assert log.info["ended"] == "stopped: a button or stick"
    t = log.time_ms - (pressed * 1000 - float(log.info["started_ms"]))  # ms after the press
    for port in (10, 9, 19, 17):
        assert np.all(log[f"m{port}_cmd_mv"][(t > -100) & (t < 0)] != 0)  # driving, pressed
        assert np.all(log[f"m{port}_cmd_mv"][t >= 20] == 0)  # told to stop within 20 ms
        assert np.all(log[f"m{port}_mv"][t >= 30] == 0)  # and stopped
    assert t[-1] > 400  # the log goes on, to see the robot stop


def test_the_device_check_catches_a_reversed_motor_and_swapped_sensors(plan, program, tmp_path):
    student, _ = run_session(plan, program, ["device_check"], tmp_path, real=miswired())
    assert student.problems == ["motor 9 runs backward: make it -9", "ports 1 and 8 are swapped"]
    check = logs(tmp_path)[0]
    assert check.info["check"] == "failed"
    assert check.info["check_left"] == "motor 9 runs backward: make it -9"
    assert check.info["check_right"] == "ok" and check.info["check_imu"] == "ok"
    assert check.info["check_distance"] == "ports 1 and 8 are swapped"


def test_going_further_than_the_plan_stops_the_robot(plan, program, tmp_path):
    rolls = {"wheel.omni.rolling_resistance": 0.015, "motor.natural_free_rpm": 140.0}
    real = CONFIG.model_copy(update={"overrides": rolls})  # far past the plan's spread
    student, _ = run_session(plan, program, ["straight"], tmp_path, real=real)
    runs = [r for r in student.runs if r.test == "straight"]
    assert [r.how for r in runs] == ["stopped: went further than planned"] * 2  # then gives up
    for run in runs:
        assert clearance(real, run.poses) > MARGIN_IN / 2  # stopped before reaching anything


def test_the_cli_writes_the_program_and_its_plan(plan, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(planning, "make_plan", lambda *args, **kwargs: plan)
    folder = tmp_path / "program"
    assert main(["calibration", "program", str(ROBOT), str(FIELD), str(folder)]) == 0
    out = capsys.readouterr().out
    assert f"{folder / 'src' / 'main.cpp'}: new" in out
    assert "6. Straight (3 runs)" in out and "isn't a PROS project yet" in out
    assert (folder / "plan" / "map_6_straight.png").is_file() or "map_" not in out
    (folder / "src" / "autons.cpp").write_text("")
    assert main(["calibration", "program", str(ROBOT), str(FIELD), str(folder)]) == 1
    assert "code of its own" in capsys.readouterr().out

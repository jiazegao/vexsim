"""Team 1239E's six-bar robot (the six-bar branch of its 2026-27 code), ported: the robot has
every device the code uses where the code says, the routines run with RCL and MCL, and each
one's log is written (examples/pros_projects/1239e_six_bar/README.md)."""

import math
import re

import pytest

from tests.conftest import ROOT
from vexsim.algorithms.localization.base import Pose
from vexsim.bridge.program import CppProgram
from vexsim.config import load_field, load_robot, validate_field, validate_robot
from vexsim.runtime.simulation import Simulation

PROJECT = ROOT / "examples" / "pros_projects" / "1239e_six_bar"
ROBOT = ROOT / "examples" / "robots" / "1239e_six_bar.yaml"
FIELD = ROOT / "examples" / "fields" / "1239e_six_bar.yaml"
CONFIGS = PROJECT / "include" / "custom" / "configs.hpp"
SKILLS_ONLY = 20  # the lift's second motor: plugged in for skills only (the team's README)


def _ints(text: str) -> list[int]:
    return [int(v) for v in re.findall(r"-?\d+", text)]


def code_devices() -> dict[str, list[int]]:
    """The devices configs.hpp makes, by kind: motor ports as the code writes them (negative
    is reversed), sensor ports likewise."""
    text = CONFIGS.read_text()
    groups = re.findall(r"pros::MotorGroup (\w+)\(\{([^}]*)\}", text)
    motors = re.findall(r"pros::Motor \w+\((-?\d+)", text)
    return {
        **{name: _ints(ports) for name, ports in groups},
        "motors": [int(p) for p in motors],
        "imu": [int(p) for p in re.findall(r"ScaledIMU imu\((\d+)", text)],
        "rotation": [int(p) for p in re.findall(r"pros::Rotation \w+\((-?\d+)\)", text)],
        "distance": [int(p) for p in re.findall(r"pros::Distance \w+\((\d+)\)", text)],
    }


@pytest.fixture(scope="module")
def port_exe(lemlib_build):
    result = lemlib_build(PROJECT)
    assert any("include/lemlib/pid.hpp" in note for note in result.notes)  # the team's edit
    return str(result.executable)


def test_configs_are_clean():
    for report in (validate_robot(ROBOT), validate_field(FIELD)):
        assert report.ok and report.issues == []
    field = load_field(FIELD)
    assert field.size_in == (140.4, 140.4) and field.pieces == []
    assert sum(not o.solid for o in field.obstacles) == 9 + 12  # the bases; pins and cups
    heights = {o.name: o.height_in for o in field.obstacles if o.height_in is not None}
    assert heights["center base"] == 5 and heights["neutral base 1"] == 5.8
    assert heights["alliance base 1"] == 3.25  # as MclTracking.hpp's notes say


def test_the_robot_has_every_device_the_code_uses():
    """Ports and signs from configs.hpp; the lift's motor 20 left out, as in a match."""
    code, robot = code_devices(), load_robot(ROBOT)
    gearing = robot.drivetrain.gearing
    assert list(gearing["left"].motors) == code["leftMotors"] == [-15, -14, -13]
    assert list(gearing["right"].motors) == code["rightMotors"] == [8, 7, 10]
    mechanisms = robot.mechanisms
    assert code["liftMotors"] == [-19, SKILLS_ONLY] and list(mechanisms["lift"].motors) == [-19]
    singles = sorted(m for m in code["motors"] if abs(m) != SKILLS_ONLY)
    in_config = sorted(p for name, m in mechanisms.items() for p in m.motors)
    assert singles == sorted([-19, 17, 18, -16]) and in_config == singles
    # the 5.5 W motors: every motor the code makes green or red (the team). The claw's two
    # are declared green; the drive's groups are declared blue, and initialize() sets each
    # one's first motor green (set_gearing(green, 0)).
    text = CONFIGS.read_text()
    declared = re.findall(r"pros::Motor \w+\((-?\d+), pros::MotorGearset::(\w+)\)", text)
    green = [int(p) for p, gears in declared if gears in ("green", "red")]
    main = (PROJECT / "src" / "main.cpp").read_text()
    calls = r"(\w+)\.set_gearing\(pros::MotorGears::(\w+), (\d+)\)"
    for group, gears, index in re.findall(calls, main):
        if gears in ("green", "red"):
            green.append(code[group][int(index)])
    assert sorted(green) == [-16, -15, 8, 18]
    small = [p for g in (*gearing.values(), *mechanisms.values()) for p in g.motors
             if g.motor_cartridge(p) == "5.5w"]  # fmt: skip
    assert sorted(small) == sorted(green)
    assert sum(g.power_w for g in (*gearing.values(), *mechanisms.values())) == 88.0
    sensors = {s.port: s for s in robot.sensors}
    assert [s.type for p, s in sensors.items() if p in code["imu"]] == ["imu"]
    (rotation,) = code["rotation"]
    wheel = sensors[abs(rotation)]
    assert wheel.type == "rotation" and wheel.reversed == (rotation < 0)
    assert sorted(p for p, s in sensors.items() if s.type == "distance") == sorted(code["distance"])
    assert len(sensors) == len(robot.sensors)  # no port twice


def test_the_robot_is_where_the_code_says():
    """The drive and tracking wheel from LemLib's settings, and each distance sensor where MCL's
    sensor_mounts puts it (inches forward and left, radians counter-clockwise), in the order
    of DISTANCE_COLLECTION."""
    text = CONFIGS.read_text()
    track, wheel_in, rpm = re.search(
        r"lemlib::Drivetrain drivetrain\([^,]+,\s*[^,]+,\s*([\d.]+),\s*([\d.]+),\s*(\d+)", text
    ).groups()
    robot = load_robot(ROBOT)
    wheels = robot.drivetrain.wheels
    assert {w.diameter_in for w in wheels} == {float(wheel_in)}
    assert {w.type for w in wheels} == {"omni"}  # LemLib's horizontal drift 2
    left, right = (w.pos_in[1] for w in wheels if w.name in ("lm", "rm"))
    assert left - right == pytest.approx(float(track))
    assert robot.drivetrain.gearing["left"].wheel_free_rpm == float(rpm)
    pod = re.search(r"lemlib::TrackingWheel vertPod\(&vertRotation, ([\d.]+), ([-\d.]+)\)", text)
    tracking = next(s for s in robot.sensors if s.type == "rotation").tracking_wheel
    assert tracking.diameter_in == float(pod[1]) and tracking.pos_in[1] == float(pod[2])
    assert tracking.heading_deg == 0  # a vertical wheel

    names = re.search(r"DISTANCE_COLLECTION = \{([^}]*)\}", text)[1]
    ports = [
        int(re.search(rf"pros::Distance {n.strip(' &')}\((\d+)\)", text)[1])
        for n in names.split(",")
    ]
    mounts_text = (PROJECT / "include" / "custom" / "MclTracking.hpp").read_text()
    table = re.search(r"sensor_mounts\[SENSOR_COUNT\] = \{(.*?)\};", mounts_text, re.S)[1]
    mounts = re.findall(r"\{\s*([-\d.]+)f?,\s*([-\d.]+)f?,\s*([^}]+?)\s*\}", table)
    assert len(mounts) == len(ports) == 6
    sensors = {s.port: s for s in robot.sensors}
    for port, (forward, leftward, theta) in zip(ports, mounts, strict=True):
        angle = eval(theta.replace("std::numbers::pi", "math.pi"), {"math": math})  # noqa: S307
        sensor = sensors[port]
        assert sensor.pos_in == pytest.approx((float(forward), float(leftward)), abs=1e-6), port
        turn = (sensor.heading_deg - math.degrees(angle) + 180.0) % 360.0 - 180.0
        assert turn == pytest.approx(0.0, abs=1e-9), port
        assert 2.0 < sensor.height_in < 5.6, port  # configs.hpp's notes: 2.08 to 5.53 in


def test_the_routines_and_where_they_start():
    """The routine list reads auton.hpp; each saved run starts its routine at its setPose, and
    the selector's two routines are the saved match runs."""
    from vexsim.app.launch import read_configurations
    from vexsim.bridge.routines import find_routines

    found = find_routines(PROJECT)
    names = {r.name for r in found.routines}
    assert {"left5pin", "right5pin", "safe_skills", "left3pin", "skills", "testPid"} <= names
    assert found.named("left5pin").start_pose() == pytest.approx((57, 6.75, 0))
    assert found.named("right5pin").start_pose() == pytest.approx((6.75, 57, 90))
    assert found.named("safe_skills").start_pose() == pytest.approx((57, 0, 0))
    selector = (PROJECT / "include" / "custom" / "auton_selector.hpp").read_text()
    assert dict(re.findall(r'\{"([^"]+)",\s*(\w+)\}', selector)) == {
        "LEFT 5-PIN": "left5pin",
        "RIGHT 5-PIN": "right5pin",
    }
    saved = {c.name: c for c in read_configurations(ROOT) if c.name.startswith("1239E six-bar")}
    assert len(saved) == 4  # the three routines and driver control
    for configuration in saved.values():
        assert configuration.program == "examples/pros_projects/1239e_six_bar"
        if configuration.routine is not None:
            start = found.named(configuration.routine).start_pose()
            assert tuple(configuration.start) == pytest.approx(start), configuration.name


def test_the_sweep_runs_every_routine_both_ways():
    from vexsim.app.launch import read_configurations
    from vexsim.app.sweeps import expand, read_sweeps

    sweep = next(s for s in read_sweeps(ROOT) if s.name == "1239E six-bar: RCL + MCL vs odometry")
    trials = expand(sweep, read_configurations(ROOT))
    assert len(trials) == 3 * 2 * 6
    assert {t.spec.routine for t in trials} == {"left5pin", "right5pin", "safe_skills"}
    assert {t.variation["VEXSIM_TRACKING"] for t in trials} == {"rcl+mcl", "odom"}


LOGGING_GONE = ("initLog", "logMcl", "mclLog", "MCL_Log_Format", "LogData", "log_queue",
                "AsyncLogger", "DATA.1239e", "mcl_log", "VEXSIM_SD_DIR")  # fmt: skip


def test_the_mcl_log_is_gone():
    """As in the first port: vexsim's logger logs each routine, the team's MCL log is out."""
    for path in sorted((PROJECT / "src").rglob("*")) + sorted((PROJECT / "include").rglob("*")):
        if path.suffix in (".c", ".cpp", ".h", ".hpp"):
            text = path.read_text(errors="replace")
            left = [name for name in LOGGING_GONE if name in text]
            assert not left, f"{path.relative_to(PROJECT)} still has {left}"


def _run(executable, env, start, seconds=None, seed=1):
    program = CppProgram(executable, env=env)
    sim = Simulation(load_robot(ROBOT), program=program, field=load_field(FIELD), seed=seed,
                     start=Pose(*start), echo=None)  # fmt: skip
    try:
        sim.start("autonomous")
        if seconds is None:
            assert sim.run_until_finished(30.0)
        else:
            sim.run_for(seconds)
    finally:
        sim.close()
    return sim


def test_routines_are_picked_by_name(port_exe):
    """VEXSIM_AUTON names a routine as the selector does, or Skills for its Skills button; each
    routine's startMcl() says where the simulated robot should start."""
    start = "start the simulated robot with --start="
    picks = {
        "RIGHT 5-PIN": f"startMcl: pose (6.75, 57, 0); {start}6.75,57,90",
        "Skills": f"startMcl: pose (57, 0, 90); {start}57,0,0",
        "LEFT 99": 'VEXSIM_AUTON: no routine named "LEFT 99"',
    }
    for name, said in picks.items():
        sim = _run(port_exe, {"VEXSIM_AUTON": name}, (57, 6.75, 0), seconds=2.5)
        assert any(line.endswith(said) for line in sim.console), name


def test_left_5_pin_runs_localizes_and_logs_itself(port_exe, tmp_path):
    """LEFT 5-PIN runs to the end with RCL and MCL keeping LemLib's pose near the truth, its
    lift and claw move as the code says, and it logs itself to the card (here, the folder
    standing in for one) with vexsim's logger."""
    from vexsim.calibration.log import RobotLog

    card = tmp_path / "card"
    sim = _run(port_exe, {"VEXSIM_AUTON": "LEFT 5-PIN", "VEXSIM_SD_DIR": str(card)}, (57, 6.75, 0))
    rows = [r for r in sim.recorder.rows if r[1] == "autonomous"]
    assert 13 < rows[-1][0] - rows[0][0] < 16  # the routine takes 14.6 s
    error = sim.recorder.pose_error("autonomous")
    assert error.mean_in < 4.0 and error.max_in < 10.0 and error.final_in < 6.0
    # What the simulated robot can't be as the code has it, said on the console: the drive's
    # groups declare their 5.5 W motors blue (until initialize() sets them green), and the
    # skills-only lift motor. Every motor the code sets green is a 5.5 W one.
    console = "\n".join(sim.console)
    for port in (15, 8):
        assert f"port {port}: a 5.5W motor, which is green (200 rpm) only" in console
    assert "the code declares the green" not in console
    assert f"port {SKILLS_ONLY}: the code uses a motor here" in console
    columns = sim.recorder.columns
    lift = [r[columns.index("lift_deg")] for r in rows]
    claw = [r[columns.index("claw_deg")] for r in rows]
    assert 400 < max(lift) < 714  # toward THIRD_STACK + 20 (448.6), below the top
    assert min(claw) == pytest.approx(-13, abs=0.5)  # closed against its stop

    log = RobotLog.read(card / "vexsim_0001_left_5_pin.csv")
    assert (log.info["name"], log.info["mode"]) == ("LEFT 5-PIN", "autonomous")
    assert log.ports("m") == [7, 8, 10, 13, 14, 15, 16, 17, 18, 19]  # the drive's and mechanisms'
    assert log.ports("d") == [2, 3, 4, 5, 11, 21] and log.ports("imu") == [6]
    assert log.poses() == ["lemlib", "mcl"] and len(log) > 1000
    assert 0 < log["val_mcl_spread_x"][-1] < 10 and 0 < log["val_mcl_spread_y"][-1] < 10
    x, y, _ = log.pose("lemlib")
    believed = sim.reported_pose
    assert math.dist((x[-1], y[-1]), (believed.x, believed.y)) < 0.5

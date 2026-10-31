"""Phase 14.4: collecting a calibration session, and the pieces of fitting it.

The fits are tested here on data made to a known answer (fast); fitting whole sessions of
simulated "real" robots, as a student records them, is test_calibration_sessions.py.
"""

import math
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import yaml

from tests.conftest import EXAMPLE_ROBOT, ROOT
from vexsim.app.configs import parse_location
from vexsim.app.yamledit import Change, apply
from vexsim.calibration import feedforward
from vexsim.calibration import session as sessions
from vexsim.calibration import session_fit as fits
from vexsim.calibration.log import BEGIN, END, RobotLog
from vexsim.calibration.replay import simulate
from vexsim.calibration.report import (
    STAMP,
    Write,
    apply_changes,
    changes,
    report_text,
    why_not,
)
from vexsim.calibration.routine import run_routine, standard_routine
from vexsim.calibration.session import Session, check, collect
from vexsim.calibration.session_fit import (
    Calibration,
    Readings,
    SessionError,
    Step,
    Value,
    calibrate,
    imu_noise,
    voltage_cap,
)
from vexsim.cli import main
from vexsim.config import load_field, load_robot
from vexsim.config.loader import validate_robot
from vexsim.devices.devices import DistanceDevice
from vexsim.devices.specs import sensor_spec
from vexsim.physics.params import resolve_params
from vexsim.physics.robot import Robot
from vexsim.physics.world import World

CONFIG = load_robot(EXAMPLE_ROBOT)
ROBOT_1239E = ROOT / "examples" / "robots" / "1239e_2026-27.yaml"


def program_log(test: str, *, run=1, started=0, ended="finished", robot=None, **info) -> RobotLog:
    """A short log as the calibration program writes one."""
    names = ["time_ms", "m1_deg", "m1_rpm", "imu10_deg"]
    rows = [[t * 10.0, t * 3.0, 50.0, -0.1 * t] for t in range(30)]
    head = {
        "robot": robot or CONFIG.name,
        "field": "Practice field",
        "program": "vexsim calibration",
        "test": test,
        "run": str(run),
        "name": test,
        "started_ms": str(started),
        "ended": ended,
        **{k: str(v) for k, v in info.items()},
    }
    return RobotLog.from_rows(names, rows, head)


def card(folder: Path, logs: list[tuple[str, RobotLog]]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, log in logs:
        (folder / name).write_text(log.to_csv(), encoding="utf-8")
    return folder


# --- collecting -------------------------------------------------------------------------------


def test_collect_copies_each_new_log_once_and_checks_it(tmp_path):
    other = program_log("free_spin", robot="Someone else's robot")
    plain = RobotLog.from_rows(["time_ms", "m1_rpm"], [[0.0, 1.0], [10.0, 2.0]], {"name": "x"})
    sd = card(
        tmp_path / "card",
        [
            ("vexsim_0001_device_check.csv", program_log("device_check", check="passed")),
            ("vexsim_0002_free_spin.csv", program_log("free_spin", started=1000)),
            (
                "vexsim_0003_straight.csv",
                program_log("straight", started=2000, ended="stopped: a button"),
            ),
            ("vexsim_0004_free_spin.csv", other),
            ("vexsim_0005_auton.csv", plain),
        ],
    )
    said = []
    session = Session.open(tmp_path / "session")
    added = collect(session, sessions.card_logs(sd), say=said.append)
    assert [r.test for r in added] == ["device_check", "free_spin", "straight"]
    assert session.robot == CONFIG.name and session.field_name == "Practice field"
    assert any("Someone else's robot" in s for s in said)
    assert any("not the calibration program's" in s for s in said)
    stopped = next(r for r in added if r.test == "straight")
    assert not stopped.use and stopped.quality == "stopped: a button"

    again = Session.open(tmp_path / "session")  # session.yaml, read back
    assert [(r.file, r.use) for r in again.runs] == [(r.file, r.use) for r in session.runs]
    assert collect(again, sessions.card_logs(sd)) == []  # nothing new the second time
    assert [run.test for run, _ in again.logs()] == ["device_check", "free_spin"]
    assert len(again.logs(used=False)) == 3
    assert "use: false" in again.file.read_text()


def test_a_log_of_the_same_name_is_kept_beside_the_first(tmp_path):
    session = Session.open(tmp_path / "session")
    collect(
        session,
        [
            card(tmp_path / "a", [("vexsim_0001_spin.csv", program_log("spin"))])
            / "vexsim_0001_spin.csv"
        ],
    )
    later = card(tmp_path / "b", [("vexsim_0001_spin.csv", program_log("spin", run=2, started=5))])
    (run,) = collect(session, [later / "vexsim_0001_spin.csv"])
    assert run.file == "vexsim_0001_spin.2.csv" and run.run == 2
    assert {r.file for r in session.runs} == {"vexsim_0001_spin.csv", "vexsim_0001_spin.2.csv"}


@pytest.mark.parametrize(
    ("log", "quality"),
    [
        (program_log("imu_turns", turns=10), "not 10 turns"),  # it turned 2.9 degrees
        (program_log("device_check", check="failed"), "the device check failed"),
        (program_log("spin", ended="?"), "it didn't finish"),
    ],
)
def test_check_leaves_out_runs_the_fit_cant_use(log, quality):
    found, use, _ = check(log)
    assert found.startswith(quality) and not use


def test_a_run_that_slowed_suddenly_is_left_out():
    log = program_log("straight")
    log.marks.append((100.0, "slowed suddenly"))
    quality, use, warnings = check(log)
    assert not use and "hit something" in quality and warnings == ["slowed suddenly"]


def test_logs_framed_in_a_terminal_are_collected_over_usb(tmp_path):
    texts = [program_log("free_spin").to_csv(), program_log("spin", started=9).to_csv()]
    printed = "".join(f"noise\n{BEGIN}\n{t}{END}\n" for t in texts)
    script = tmp_path / "terminal.py"
    script.write_text(f"print({printed!r})\n", encoding="utf-8")
    session = Session.open(tmp_path / "session")
    added = sessions.from_usb(session, [sys.executable, "-I", str(script)])
    assert [r.test for r in added] == ["free_spin", "spin"]
    assert all((session.runs_dir / r.file).is_file() for r in added)


def test_the_card_is_the_mounted_drive_with_vexsims_logs(tmp_path, monkeypatch):
    empty, with_logs = tmp_path / "USB", tmp_path / "V5 card"
    empty.mkdir()
    card(with_logs, [("vexsim_0001_free_spin.csv", program_log("free_spin"))])
    monkeypatch.setattr(sessions.sys, "platform", "linux")
    monkeypatch.setattr(sessions, "_children", lambda folder: [empty, with_logs])
    assert sessions.find_card() == with_logs
    monkeypatch.setattr(sessions, "_children", lambda folder: [empty])
    assert sessions.find_card() is None


def test_collect_command(tmp_path, capsys):
    sd = card(
        tmp_path / "card",
        [("vexsim_0001_device_check.csv", program_log("device_check", check="passed"))],
    )
    assert main(["calibration", "collect", str(tmp_path / "s"), "--from", str(sd)]) == 0
    out = capsys.readouterr().out
    assert "1 new run(s)" in out and "device_check: 1 used" in out
    assert (
        main(["calibration", "collect", str(tmp_path / "s"), "--from", str(tmp_path / "none")]) != 0
    )


# --- what the replays and the models learned --------------------------------------------------


def free_speed(cap: float) -> float:
    """A lifted robot's drive motors at 12 V (rpm, as a fraction of rated)."""
    world = World(seed=0)
    robot = world.add_system(Robot(CONFIG, params=resolve_params({"motor.voltage_cap": cap})))
    robot.lifted = True
    for motor in robot.motors.values():
        motor.set_voltage(12.0)
    world.run_for(1.5)
    motor = robot.motors[abs(CONFIG.drivetrain.gearing["left"].motors[0])]
    return abs(motor.velocity) / motor.rated_speed


def test_a_motor_whose_voltage_commands_are_capped_runs_no_faster_than_rated():
    assert free_speed(0.0) > 1.1  # a V5 motor runs past its rated speed at 12 V
    assert free_speed(1.0) == pytest.approx(1.0, abs=0.01)


def beam(spec_overrides: dict, angle_deg: float, mm: float) -> DistanceDevice:
    """A distance sensor at the robot's center, its beam meeting the +x wall ``mm`` away at
    ``angle_deg`` off square."""
    sensor = next(s for s in CONFIG.sensors if s.type == "distance").model_copy(
        update={"pos_in": (0.0, 0.0), "heading_deg": 0.0}
    )
    field = load_field(ROOT / "examples" / "fields" / "v5rc_empty.yaml")
    half = field.size_in[0] / 2 * 0.0254
    a = math.radians(angle_deg)
    robot = types.SimpleNamespace(pose=(half - mm / 1000 * math.cos(a), 0.0, a))
    spec = sensor_spec("distance", "default", spec_overrides)
    return DistanceDevice(sensor, robot, field, spec, np.random.default_rng(1))


def readings(device: DistanceDevice, n: int = 400) -> tuple[list, list]:
    values, confidences = [], []
    for k in range(n):
        device.sample(k * 33_000)
        device.publish(k * 33_000 + 100_000)
        values.append(device.value)
        confidences.append(device.confidence)
    return values, confidences


def test_distance_sensors_by_default_never_miss_and_are_sure():
    values, confidences = readings(beam({}, 60.0, 1800.0))
    assert all(v is not None for v in values) and set(confidences) == {63}


def test_distance_sensors_miss_glancing_beams_far_away_and_say_how_sure():
    shaped = {
        "glancing_miss": 0.9,
        "glancing_deg": 45.0,
        "glancing_mm": 1500.0,
        "confidence_per_m": 8.0,
        "confidence_per_deg": 0.25,
    }
    values, _ = readings(beam(shaped, 60.0, 1800.0))
    assert np.mean([v is None for v in values]) == pytest.approx(0.9, abs=0.05)
    values, confidences = readings(beam(shaped, 30.0, 1800.0))
    assert all(v is not None for v in values)  # not glancing enough to miss
    assert set(confidences) == {round(63 - 8 * 1.6 - 0.25 * 30)}


def test_replays_start_with_the_imu_calibrated_and_can_leave_out_distance_sensors():
    config = load_robot(ROBOT_1239E)
    log = run_routine(config, standard_routine(config)[:4], seed=2)
    whole = simulate(config, log)
    bare = simulate(config, log, distance=False)
    assert not bare.ports("d") and whole.ports("d")
    for name in bare.columns:
        np.testing.assert_array_equal(bare[name], whole[name])


def test_replays_read_ideal_sensors_whatever_noise_the_config_gives_them():
    log = run_routine(CONFIG, standard_routine(CONFIG)[:4], seed=2)
    noisy = CONFIG.model_copy(
        update={
            "overrides": {
                "sensor.motor.velocity_noise": 0.01,
                "sensor.imu.heading_noise_deg": 0.05,
                "sensor.rotation.noise_deg": 0.1,
            }
        }
    )
    plain, replayed = simulate(CONFIG, log), simulate(noisy, log)
    for name in plain.columns:
        np.testing.assert_array_equal(plain[name], replayed[name])


def test_the_drive_model_fits_several_logs_at_once():
    log = run_routine(CONFIG, standard_routine(CONFIG), seed=3)
    one, both = feedforward.fit(CONFIG, log), feedforward.fit_logs(CONFIG, [log, log])
    assert both.samples == 2 * one.samples
    assert (both.kS, both.kV, both.kA, both.kT) == pytest.approx((one.kS, one.kV, one.kA, one.kT))


def test_override_keys_are_written_as_quoted_locations():
    assert parse_location('overrides["wheel.omni.lateral_mu"]') == [
        "overrides",
        "wheel.omni.lateral_mu",
    ]
    text = "name: r  # the robot\nversion: 1\noverrides:\n  motor.free_current_a: 0.2\n"
    text = apply(text, [Change("set", 'overrides["motor.voltage_cap"]', 1.0)])
    assert "# the robot" in text
    assert yaml.safe_load(text)["overrides"] == {
        "motor.free_current_a": 0.2,
        "motor.voltage_cap": 1.0,
    }


# --- the fits, on data made to a known answer -------------------------------------------------


def test_imu_noise_comes_from_the_allan_variance_of_a_still_imu():
    rng = np.random.default_rng(4)
    n, dt = 60_000, 0.01  # 10 minutes, for a sharp answer
    heading, rate, walk = 0.01, 0.05, 0.0005
    bias = np.cumsum(rng.normal(0.0, walk * math.sqrt(dt), n))
    theta = np.cumsum((bias + rng.normal(0.0, rate, n)) * dt) + rng.normal(0.0, heading, n)
    found = imu_noise(theta, dt, 0.01)
    assert found["sensor.imu.heading_noise_deg"][0] == pytest.approx(heading, rel=0.05)
    assert found["sensor.imu.rate_noise_deg_s"][0] == pytest.approx(rate, rel=0.3)
    assert found["sensor.imu.bias_walk_deg_s"][0] == pytest.approx(walk, rel=0.5)


def free_spin_log(speeds: dict[str, float]) -> RobotLog:
    """A free spin's steady stretches, each motor at a fraction of its rated 600 rpm."""
    ports = [abs(p) for g in CONFIG.drivetrain.gearing.values() for p in g.motors]
    names = ["time_ms", *[f"m{p}_rpm" for p in ports]]
    rows, marks = [], []
    for k, (mark, fraction) in enumerate(speeds.items()):
        marks.append((k * 1500.0, mark))
        for t in range(k * 1500, (k + 1) * 1500, 10):
            rows.append([float(t)] + [fraction * 600.0] * len(ports))
    return RobotLog.from_rows(names, rows, {}, marks)


def test_a_free_spin_tells_whether_voltage_commands_are_capped():
    free = {"3 V": 0.27, "6 V": 0.56, "9 V": 0.85, "12 V": 1.13}
    capped = {**free, "12 V": 1.0}
    assert voltage_cap(CONFIG, free_spin_log(free))[0] == 0.0
    cap, why = voltage_cap(CONFIG, free_spin_log(capped))
    assert cap == 1.0 and "held to rated speed" in why
    assert voltage_cap(CONFIG, free_spin_log({"3 V": 0.27}))[0] is None


def made_readings(rng, n=6000) -> Readings:
    """A sensor's sweep readings, made by the sensor model with known values."""
    true = rng.uniform(150.0, 3000.0, n)
    angle = rng.uniform(0.0, 89.0, n)
    reading = true + rng.normal(0.0, 1.0, n) * np.where(true < 200, 1.5, 0.003 * true)
    glancing = (angle > 45.0) & (true > 1500.0) & (rng.random(n) < 0.9)
    gone = (true > 2300.0) | glancing
    reading = np.where(gone, np.nan, np.round(reading))
    lost = 8.0 * np.maximum(true / 1000.0 - 0.2, 0.0) + 0.25 * angle
    confidence = np.where(gone, 0.0, np.clip(np.round(63 - lost), 0, 63))
    order = np.argsort(angle)  # a slow sweep: neighbouring readings meet the same surface
    true, angle, reading, confidence = true[order], angle[order], reading[order], confidence[order]
    return Readings(
        port=1,
        time_ms=np.arange(n) * 33.0,
        reading=reading,
        confidence=confidence,
        true_mm=true,
        angle=angle,
        new=np.ones(n, dtype=bool),
        sweep=np.zeros(n, dtype=int),
    )


def test_the_distance_fits_find_the_noise_range_misses_and_confidence():
    r = made_readings(np.random.default_rng(5))
    spec = sensor_spec("distance")
    reach, _ = fits._range([r], spec)
    assert reach == pytest.approx(2300.0, abs=50)
    glancing = fits._glancing([r], reach)
    assert glancing["miss"] == pytest.approx(0.9, abs=0.05)
    assert glancing["deg"] == pytest.approx(45.0, abs=2.5)
    assert glancing["mm"] == pytest.approx(1500.0, abs=100)
    confidence = fits._confidence([r])
    assert confidence["sensor.distance.confidence_per_m"][0] == pytest.approx(8.0, rel=0.05)
    assert confidence["sensor.distance.confidence_per_deg"][0] == pytest.approx(0.25, rel=0.05)


def test_the_noise_comes_from_neighbouring_readings():
    rng = np.random.default_rng(6)
    n = 3000
    true = 1000.0 + 300.0 * np.sin(np.arange(n) / 200.0)  # a wall, slowly nearer and farther
    r = Readings(
        port=1,
        time_ms=np.arange(n) * 33.0,
        reading=np.round(true + rng.normal(0.0, 0.004 * true)),
        confidence=np.full(n, 60.0),
        true_mm=true,
        angle=np.full(n, 10.0),
        new=np.ones(n, dtype=bool),
        sweep=np.zeros(n, dtype=int),
    )
    found = fits._noise([r])
    assert found["sensor.distance.long_noise_fraction"][0] == pytest.approx(0.004, rel=0.1)


# --- the session's fit: what stops it --------------------------------------------------------


def session_of(tmp_path: Path, logs: list[RobotLog]) -> Session:
    session = Session.open(tmp_path / "session")
    for k, log in enumerate(logs, 1):
        sessions.add(session, log, log.to_csv().encode(), f"vexsim_{k:04d}_{log.info['test']}.csv")
    session.save()
    return session


def test_a_failed_device_check_stops_the_fit_saying_what_to_fix(tmp_path):
    failed = program_log("device_check", check="failed")
    failed.marks += [
        (0.0, "to fix: motor 9 runs backward: make it -9"),
        (0.0, "to fix: ports 1 and 8 are swapped"),
    ]
    session = session_of(tmp_path, [failed, program_log("free_spin", started=10)])
    with pytest.raises(SessionError) as caught:
        calibrate(CONFIG, session)
    assert "motor 9 runs backward" in str(caught.value) and "ports 1 and 8" in str(caught.value)


def test_a_session_without_a_device_check_or_a_test_it_needs_says_so(tmp_path):
    with pytest.raises(SessionError, match="no device check"):
        calibrate(CONFIG, session_of(tmp_path / "a", [program_log("free_spin")]))
    passed = program_log("device_check", check="passed")
    with pytest.raises(SessionError, match="no free spin"):
        calibrate(CONFIG, session_of(tmp_path / "b", [passed]))


def test_a_session_of_another_robot_isnt_fitted_to_this_one(tmp_path):
    passed = program_log("device_check", check="passed", robot="Another robot")
    with pytest.raises(SessionError, match="Another robot"):
        calibrate(CONFIG, session_of(tmp_path, [passed]))


def test_calibrate_command_stops_at_a_failed_device_check(tmp_path, capsys):
    failed = program_log("device_check", check="failed")
    failed.marks.append((0.0, "to fix: IMU: it reads turns backward"))
    session = session_of(tmp_path, [failed])
    assert main(["calibrate", str(EXAMPLE_ROBOT), str(session.folder)]) != 0
    assert "IMU: it reads turns backward" in capsys.readouterr().out


# --- the report and --apply -------------------------------------------------------------------


def a_calibration(config) -> Calibration:
    imu = next(s for s in config.sensors if s.type == "imu")
    steps = [
        Step(
            "Free spin: the motors",
            values=[
                Value("motor.voltage_cap", 0.0, 1.0, 0.0, 0.02),
                Value("motor.natural_free_rpm", 121.0, 121.05, 0.05, 1.21),  # the same
            ],
        ),
        Step(
            "IMU: scale error, noise and drift",
            values=[
                Value(f"sensors.{imu.port}.scale_error", math.nan, 0.004, 0.0002, 0.0005),
                Value("sensor.imu.bias_walk_deg_s", 0.0005, 0.0001, 0.005, 0.00005),  # not pinned
            ],
        ),
        Step(
            "Push: wheel diameters",
            values=[Value("wheels.left.diameter_in", 3.25, 3.21, 0.002, 0.016)],
            warnings=["the left wheels look worn"],
        ),
    ]
    return Calibration(
        robot=config.name,
        session=Path("sessions/first"),
        steps=steps,
        config=config,
        overrides={"motor.voltage_cap": 1.0},
        diameters={"left": 3.21},
        tracking={},
        imu_scales={imu.port: 0.004},
    )


def test_apply_writes_only_what_the_logs_pin_down_and_changed():
    calibration = a_calibration(CONFIG)
    writes = changes(CONFIG, calibration)
    where = {w.location: w.value for w in writes}
    imu = next(i for i, s in enumerate(CONFIG.sensors) if s.type == "imu")
    left = [
        i
        for i, w in enumerate(CONFIG.drivetrain.wheels)
        if w.name in CONFIG.drivetrain.gearing["left"].wheels
    ]
    assert where == {
        'overrides["motor.voltage_cap"]': 1.0,
        f"sensors[{imu}].scale_error": 0.004,
        **{f"drivetrain.wheels[{i}].diameter_in": 3.21 for i in left},
    }
    notes = {v.key: why_not(v) for s in calibration.steps for v in s.values}
    assert "the same" in notes["motor.natural_free_rpm"]
    assert "don't pin it down" in notes["sensor.imu.bias_walk_deg_s"]


def test_apply_keeps_every_comment_and_names_the_session(tmp_path):
    text = EXAMPLE_ROBOT.read_text(encoding="utf-8")
    writes = changes(CONFIG, a_calibration(CONFIG))
    once = apply_changes(text, writes, "first", "2026-11-01")
    comments = [line.strip() for line in text.splitlines() if line.strip().startswith("#")]
    for comment in comments:
        assert comment in once
    assert f"{STAMP}first on 2026-11-01" in once
    path = tmp_path / "robot.yaml"
    path.write_text(once, encoding="utf-8")
    report = validate_robot(str(path))
    assert report.ok, report.issues
    assert report.config.overrides["motor.voltage_cap"] == 1.0
    assert {
        w.diameter_in for w in report.config.drivetrain.wheels if w.name in ("lf", "lm", "lb")
    } == {3.21}
    twice = apply_changes(once, writes, "second", "2026-11-02")
    assert twice.count(STAMP) == 1 and "second on 2026-11-02" in twice


def test_the_report_says_what_was_found_and_why_some_isnt_written():
    calibration = a_calibration(CONFIG)
    writes = changes(CONFIG, calibration)
    text = report_text(CONFIG, calibration, writes, {}, when="2026-11-01")
    assert text.startswith(f"# Calibration of {CONFIG.name}")
    assert "the left wheels look worn" in text
    assert 'overrides["motor.voltage_cap"]' in text
    assert "don't pin it down" in text and "the same as the config's" in text
    assert [w for w in writes if isinstance(w, Write)]


def test_calibrate_finds_the_sessions_field_by_the_name_its_logs_give(tmp_path, capsys):
    from vexsim.cli import _session_field

    session = Session(
        tmp_path, field_name=load_field(ROOT / "examples" / "fields" / "1239e_2026-27.yaml").name
    )
    field = _session_field(session, str(ROBOT_1239E), None)
    assert field is not None and field.name == session.field_name
    assert "1239e_2026-27.yaml" in capsys.readouterr().out
    assert (
        _session_field(Session(tmp_path, field_name="No such field"), str(ROBOT_1239E), None)
        is None
    )

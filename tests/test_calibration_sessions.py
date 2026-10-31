"""Phases 14.4 and 14.5: whole calibration sessions of simulated "real" robots, fitted, and
the team's autonomous checked against the calibrated simulator.

Each "real" robot is a robot config with changes the fit isn't told about (PLAN.md section
16): wheels 3.20 in, an IMU 0.25% further off than its config says, omni friction 0.75,
voltage commands capped at rated speed, and the real distance sensors' noise, range, misses
at glancing angles and confidence. The calibration program runs on it in vexsim, a
simulated student working through its menu with the logs going to a stand-in SD card;
``vexsim calibration collect`` takes them, ``calibrate`` fits them, and every changed value
must come back within its tolerance, the held-out run must match within the sensors'
noise, and ``--apply`` must write the robot config with its comments kept. The same for
``full_omni_6m`` with its two tracking wheels. A robot wired other than its config says
stops at the device check.

Then the autonomous check (14.5): the real 1239E runs Left 40 twice, from 1239E's own code
with its logger and a card, its end measured with tape as a team would; ``vexsim
calibration check-auton`` passes the calibrated config and fails the default one, at the
marks the team sets in its .vexsim/calibration.yaml.

These take minutes (each session is about 5 minutes of the robot's time, then the fit):
they're marked ``session``, which pytest leaves out unless asked (pytest -m session); CI
runs them in a job of their own.
"""

import math
import shutil
from pathlib import Path
from typing import NamedTuple

import pytest

from tests.conftest import ROOT
from vexsim.bridge.program import CppProgram
from vexsim.calibration import session_fit
from vexsim.calibration.plan import make_plan
from vexsim.calibration.program import write_program
from vexsim.calibration.report import STAMP
from vexsim.calibration.session import Session
from vexsim.calibration.session_fit import SessionError, calibrate
from vexsim.calibration.student import Student
from vexsim.cli import main
from vexsim.config import load_field, load_robot
from vexsim.config.loader import validate_robot
from vexsim.runtime.simulation import Simulation

pytestmark = pytest.mark.session

ROBOTS = ROOT / "examples" / "robots"
FIELDS = ROOT / "examples" / "fields"
REAL = {  # what the real robots are like, and the fit isn't told
    "wheel.omni.longitudinal_mu": 0.75,
    "wheel.omni.lateral_mu": 0.25,
    "wheel.omni.rolling_resistance": 0.13,
    "motor.voltage_cap": 1.0,
    # the real distance sensors (docs/1239e_real_vs_sim.md): quieter than vexsim's default,
    # further, and missing beams that glance off far away, less sure with distance and angle
    "sensor.distance.long_noise_fraction": 0.003,
    "sensor.distance.short_noise_mm": 1.5,
    "sensor.distance.max_range_mm": 2300.0,
    "sensor.distance.glancing_miss": 0.9,
    "sensor.distance.glancing_deg": 45.0,
    "sensor.distance.glancing_mm": 1500.0,
    "sensor.distance.confidence_per_m": 8.0,
    "sensor.distance.confidence_per_deg": 0.25,
}
UNCHANGED = {  # vexsim's own values, which the real robots share: the fit must keep them
    "motor.natural_free_rpm": 121.0,
    "motor.free_current_a": 0.15,
    "motor.coulomb_fraction": 0.3,
    "motor.velocity_kp": 2.0,
    "battery.internal_resistance_ohm": 0.10,
    "sensor.imu.heading_noise_deg": 0.01,
    "sensor.motor.velocity_noise": 0.005,
}


class Recorded(NamedTuple):
    config: object  # the robot config the team has
    real: object  # the robot as it is
    field: object
    field_path: Path
    session: Path
    truth: dict  # the real devices' tracking wheels, as built (with their own small errors)


def real_robot(config, diameter: float, imu_scale: float, tracking: dict | None = None):
    """``config`` as the robot really is: its wheels ``diameter``, its IMU this far off, its
    tracking wheels where ``tracking`` says, and REAL."""
    wheels = tuple(w.model_copy(update={"diameter_in": diameter}) for w in config.drivetrain.wheels)
    sensors = []
    for s in config.sensors:
        if s.type == "imu":
            s = s.model_copy(update={"scale_error": imu_scale})
        if s.type == "rotation" and tracking and s.port in tracking:
            s = s.model_copy(
                update={"tracking_wheel": s.tracking_wheel.model_copy(update=tracking[s.port])}
            )
        sensors.append(s)
    return config.model_copy(
        update={
            "drivetrain": config.drivetrain.model_copy(update={"wheels": wheels}),
            "sensors": tuple(sensors),
            "overrides": {**config.overrides, **REAL},
        }
    )


def without_pieces(field):
    """The field as the session runs on it: the plan says to clear the game pieces off."""
    return field.model_copy(
        update={"elements": tuple(e for e in field.elements if e.type != "piece")}
    )


def record(build, folder: Path, config, real, field, tests=None, problems=()) -> tuple[Path, dict]:
    """The calibration program on the real robot, a student running ``tests`` (all of the
    session's, by default) and finding the ``problems`` it should; the card's folder, and
    the real tracking wheels as built."""
    plan = make_plan(config, field, workers=4)
    program = folder / "program"
    write_program(config, plan, program)
    executable = build(program).executable
    sd = folder / "card"
    student = Student(plan, config, tests or [k for k, _, _ in plan.session()])
    sim = Simulation(
        real,
        program=CppProgram(executable, env={"VEXSIM_SD_DIR": str(sd)}),
        field=field,
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
    assert student.error is None and student.problems == list(problems)
    truth = {}
    for port, device in sim.sensors.devices.items():
        if device.kind == "rotation" and device.tracking:
            mount = (device.rel + sim.robot.cg_offset) / 0.0254
            truth[port] = {"diameter_in": 2 * device.radius / 0.0254, "pos_in": tuple(mount)}
    return sd, truth


def recorded(
    build, tmp_path_factory, name, robot_file, field_file, diameter, imu_scale, tracking=None
):
    folder = tmp_path_factory.mktemp(name)
    config = load_robot(ROBOTS / robot_file)
    field = without_pieces(load_field(FIELDS / field_file))
    real = real_robot(config, diameter, imu_scale, tracking)
    sd, truth = record(build, folder, config, real, field)
    session = folder / "session"
    assert main(["calibration", "collect", str(session), "--from", str(sd)]) == 0
    return Recorded(config, real, field, FIELDS / field_file, session, truth)


@pytest.fixture(scope="module")
def robot_1239e(build, tmp_path_factory):
    return recorded(
        build, tmp_path_factory, "1239e", "1239e_2026-27.yaml", "1239e_2026-27.yaml", 3.20, 0.005
    )


@pytest.fixture(scope="module")
def omni(build, tmp_path_factory):
    tracking = {11: {"diameter_in": 2.03, "pos_in": (0.0, -1.75)}, 12: {"pos_in": (-3.3, 0.0)}}
    return recorded(
        build,
        tmp_path_factory,
        "omni",
        "full_omni_6m.yaml",
        "practice_elements.yaml",
        3.21,
        0.004,
        tracking,
    )


def fitted(robot: Recorded):
    return calibrate(robot.config, Session.open(robot.session), robot.field, workers=4)


@pytest.fixture(scope="module")
def fit_1239e(robot_1239e):
    return fitted(robot_1239e)


@pytest.fixture(scope="module")
def fit_omni(omni):
    return fitted(omni)


def found(calibration) -> dict:
    return {v.key: v for v in calibration.values()}


def check_values(calibration, expected: dict) -> None:
    values = found(calibration)
    wrong = []
    for key, truth in expected.items():
        v = values[key]
        if not (v.pinned and abs(v.after - truth) <= v.tolerance):
            wrong.append(
                f"{key}: {v.after:g} +/- {v.uncertainty:.3g} for {truth:g} (tol {v.tolerance:.3g})"
            )
    assert not wrong, "\n".join(wrong)


def common(config, diameter: float, imu_scale: float) -> dict:
    imu = next(s.port for s in config.sensors if s.type == "imu")
    return {
        **{f"wheels.{g}.diameter_in": diameter for g in config.drivetrain.gearing},
        f"sensors.{imu}.scale_error": imu_scale,
        "wheel.omni.longitudinal_mu": 0.75,
        "wheel.omni.lateral_mu": 0.25,
        "wheel.omni.rolling_resistance": 0.13,
        "motor.voltage_cap": 1.0,
        **UNCHANGED,
    }


DISTANCE = {
    key: REAL[key]
    for key in (
        "sensor.distance.long_noise_fraction",
        "sensor.distance.max_range_mm",
        "sensor.distance.glancing_miss",
        "sensor.distance.glancing_deg",
        "sensor.distance.glancing_mm",
        "sensor.distance.confidence_per_m",
        "sensor.distance.confidence_per_deg",
    )
}


# --- 1239E -------------------------------------------------------------------------------------


def test_1239e_session_recovers_each_hidden_value(fit_1239e, robot_1239e):
    check_values(fit_1239e, {**common(robot_1239e.config, 3.20, 0.005), **DISTANCE})
    assert not fit_1239e.warnings


def test_1239e_held_out_run_matches_within_the_sensors_noise(fit_1239e):
    held = fit_1239e.held_out
    assert held is not None and held.run.endswith("arc.csv")
    assert held.matches, (held.rms, held.noise)


def test_1239e_apply_writes_the_config_with_its_comments(
    fit_1239e, robot_1239e, tmp_path, monkeypatch, capsys
):
    robot = tmp_path / "1239e.yaml"
    shutil.copy(ROBOTS / "1239e_2026-27.yaml", robot)
    before = robot.read_text(encoding="utf-8")
    monkeypatch.setattr(session_fit, "calibrate", lambda *args, **kwargs: fit_1239e)
    args = [
        "calibrate",
        str(robot),
        str(robot_1239e.session),
        "--field",
        str(robot_1239e.field_path),
    ]
    assert main([*args, "--apply"]) == 0
    out = capsys.readouterr().out
    assert "matches within the sensors' noise" in out and "drive: {kS:" in out
    after = robot.read_text(encoding="utf-8")
    for line in before.splitlines():
        if line.strip().startswith("#"):
            assert line.strip() in after
    assert f"{STAMP}session on" in after
    report = validate_robot(str(robot))
    assert report.ok, report.issues
    config = report.config
    assert {w.diameter_in for w in config.drivetrain.wheels} == {
        found(fit_1239e)["wheels.left.diameter_in"].after
    }
    assert config.overrides["motor.voltage_cap"] == 1.0
    assert config.overrides["wheel.omni.longitudinal_mu"] == pytest.approx(0.75, rel=0.05)
    imu = next(s for s in config.sensors if s.type == "imu")
    assert imu.scale_error == pytest.approx(0.005, abs=0.0005)
    folder = robot_1239e.session / "report"
    assert {"report.md", "changes.yaml"} <= {p.name for p in folder.iterdir()}
    assert "matches" in (folder / "report.md").read_text(encoding="utf-8")


# --- full_omni_6m, with two tracking wheels -------------------------------------------------


def test_omni_session_recovers_each_hidden_value(fit_omni, omni):
    forward, sideways = omni.truth[11], omni.truth[12]
    check_values(
        fit_omni,
        {
            **common(omni.config, 3.21, 0.004),
            **DISTANCE,
            "sensors.11.tracking_wheel.diameter_in": forward["diameter_in"],
            "sensors.11.tracking_wheel.pos_in": forward["pos_in"][1],  # across its wheel: y
            "sensors.12.tracking_wheel.pos_in": sideways["pos_in"][0],  # x
        },
    )
    assert fit_omni.tracking[11]["pos_in"][1] == pytest.approx(forward["pos_in"][1], abs=0.1)
    assert fit_omni.tracking[12]["pos_in"][0] == pytest.approx(sideways["pos_in"][0], abs=0.1)


def test_omni_held_out_run_matches_within_the_sensors_noise(fit_omni):
    held = fit_omni.held_out
    assert held is not None and held.matches, (held.rms, held.noise)
    assert "tracking wheels" in held.rms


# --- a robot wired other than its config says ---------------------------------------------------


def test_a_miswired_robot_stops_at_the_device_check(build, tmp_path):
    config = load_robot(ROBOTS / "1239e_2026-27.yaml")
    field = without_pieces(load_field(FIELDS / "1239e_2026-27.yaml"))
    gearing = dict(config.drivetrain.gearing)
    gearing["left"] = gearing["left"].model_copy(update={"motors": (10, -9)})  # 9 the other way
    sensors = tuple(  # the distance sensors on ports 1 and 8 in each other's ports
        s.model_copy(update={"port": {1: 8, 8: 1}[s.port]})
        if s.type == "distance" and s.port in (1, 8)
        else s
        for s in config.sensors
    )
    wired = config.model_copy(
        update={
            "drivetrain": config.drivetrain.model_copy(update={"gearing": gearing}),
            "sensors": sensors,
        }
    )
    found = ["motor 9 runs backward: make it -9", "ports 1 and 8 are swapped"]
    sd, _ = record(build, tmp_path, config, wired, field, tests=["device_check"], problems=found)
    session = tmp_path / "session"
    assert main(["calibration", "collect", str(session), "--from", str(sd)]) == 0
    with pytest.raises(SessionError) as caught:
        calibrate(config, Session.open(session), field)
    problems = str(caught.value)
    assert "motor 9 runs backward" in problems and "ports 1 and 8 are swapped" in problems


def test_tolerances_are_finite_for_every_value(fit_1239e):
    for v in fit_1239e.values():
        assert math.isfinite(v.tolerance), v.key


# --- 14.5: the autonomous check ----------------------------------------------------------------

PROJECT_1239E = ROOT / "examples" / "pros_projects" / "1239e_2026-27"
FIELD_1239E = FIELDS / "1239e_2026-27.yaml"  # pieces and all: the autonomous moves them


def run_left40(real, seed: int, card: Path, in_cache) -> tuple[float, float, float]:
    """1239E's Left 40 on the real robot, logging to ``card``: where it came to rest."""
    from vexsim.app.runspec import (
        RunSpec,
        build,
        check,
        program_factory,
        routine_start,
        simulation_factory,
    )
    from vexsim.calibration.auton import _pose, settle

    spec = RunSpec(
        robot=str(ROBOTS / "1239e_2026-27.yaml"),
        program=str(PROJECT_1239E),
        routine="left40",
        field=str(FIELD_1239E),
        mode="autonomous",
        start=routine_start(str(PROJECT_1239E), "left40"),
        seed=seed,
        sd=str(card),
    )
    prepared = check(spec)
    prepared.config = real  # the robot as it is, not as its config says
    with in_cache():
        executable = build(prepared, log=None)
    make, mode = program_factory(prepared, executable)
    sim = simulation_factory(prepared, make, mode, echo=None)()
    try:
        assert sim.run_until_finished(60.0)
        settle(sim)  # a person measures it once it has stopped
        return _pose(sim)
    finally:
        sim.close()


def test_1239e_left40_passes_with_the_calibrated_config_and_fails_with_the_default(
    fit_1239e, robot_1239e, in_cache, tmp_path, monkeypatch, capsys
):
    from vexsim.calibration.auton import tape_marks
    from vexsim.calibration.report import apply_changes, changes

    team = tmp_path / "team"  # the team's workspace, with its pass marks
    (team / ".vexsim").mkdir(parents=True)
    (team / ".vexsim" / "calibration.yaml").write_text(
        "# Left 40 ends within a few degrees, run to run: our heading mark is 4\n"
        "max_distance_in: 2\nmax_heading_deg: 4\n"
    )
    monkeypatch.chdir(team)
    default = ROBOTS / "1239e_2026-27.yaml"
    calibrated = team / "1239e_calibrated.yaml"
    writes = changes(robot_1239e.config, fit_1239e)
    text = apply_changes(default.read_text(encoding="utf-8"), writes, "session", "2026-11-01")
    calibrated.write_text(text, encoding="utf-8")
    field = load_field(FIELD_1239E)
    logs, ends = [], []
    for seed in (1, 3):  # two runs of the real robot
        card = team / f"card_{seed}"
        end = run_left40(robot_1239e.real, seed, card, in_cache)
        (log,) = card.glob("vexsim_*_left_40.csv")
        logs.append(str(log))
        ends += ["--end", tape_marks(robot_1239e.config, field, end)]  # to the quarter inch
    args = [*logs, "--program", str(PROJECT_1239E), "--field", str(FIELD_1239E), *ends]
    capsys.readouterr()
    with in_cache():
        assert main(["calibration", "check-auton", str(calibrated), *args, "--out", "ok"]) == 0
        passed = capsys.readouterr().out
        assert main(["calibration", "check-auton", str(default), *args, "--out", "not"]) != 0
        failed = capsys.readouterr().out
    assert "Pass marks: 2 in, 4 degrees" in passed and "PASSED" in passed
    # uncalibrated, Left 40 ends where the real one did (its motions and localization see to
    # that), but it gets there differently: the run is what fails
    assert "FAILED" in failed and "through the run" in failed
    assert "ends " not in failed.split("FAILED")[1]
    report = (team / "ok" / "report.md").read_text(encoding="utf-8")
    assert "**passes**" in report and "card_1/vexsim_0001_left_40.csv" in report
    assert {"paths.png", "apart.png", "readings.png"} <= {p.name for p in (team / "ok").iterdir()}

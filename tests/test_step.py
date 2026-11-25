"""Phase 16: the compiled physics step, held to the Python step.

The Python step is the model; step.c copies it. From the same state the two must agree on
every number to ``TOLERANCE`` (one part in 10^9), and whole runs to a nanometre (PLAN.md
section 18). These tests step robots both ways: one step at a time from the same state (the
check mode, which compares after every step), and whole runs side by side. They need a C
compiler (see conftest.py for how the C++ tests skip without one; these do the same).
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from tests.conftest import ROOT, using_cache
from vexsim.algorithms.localization.base import Pose
from vexsim.bridge import build as build_module
from vexsim.bridge.program import CppProgram
from vexsim.calibration.replay import LoggedSupply
from vexsim.config import load_field, load_robot
from vexsim.config.field import FieldConfig
from vexsim.devices.devices import RotationDevice
from vexsim.physics import compiled
from vexsim.physics.compiled import check as check_module
from vexsim.physics.compiled import lib as lib_module
from vexsim.physics.field import Walls
from vexsim.physics.motor import BrakeMode, ControlMode, V5Motor
from vexsim.physics.power import IdealSupply
from vexsim.physics.robot import Robot
from vexsim.physics.thermal import MotorThermal
from vexsim.runtime.program import load_program
from vexsim.runtime.simulation import ScriptedInput, Simulation

ROBOTS = sorted((ROOT / "examples" / "robots").glob("*.yaml"))
FIELDS = ROOT / "examples" / "fields"
INPUT = ROOT / "examples" / "inputs" / "strafe_square.csv"
A_NANOMETRE = 1e-9  # m: how far apart whole runs may end up
A_TURN = math.radians(1e-7)


@pytest.fixture(scope="module")
def library():
    """The compiled step; without one these tests skip (or fail, where CI requires it)."""
    found = compiled.library()
    if found is None:
        if os.environ.get("VEXSIM_REQUIRE_CXX"):
            pytest.fail(f"no compiled step: {compiled.reason()}")
        pytest.skip(f"no compiled step: {compiled.reason()}")
    return found


@pytest.fixture
def fresh():
    """For tests that change what there is to find: looked for again before and after."""
    compiled.forget()
    yield
    compiled.forget()


def robot_of(path: Path, **kwargs) -> Robot:
    walls = Walls.of(FieldConfig())
    return Robot(load_robot(path), walls=walls, pose=(0.3, -0.2, 0.5), **kwargs)


def commands(robot: Robot, rng: np.random.Generator) -> None:
    """Something new for every gear group and mechanism to do, and now and then a hand on
    the robot: every branch of the step gets taken over a few thousand steps."""
    for group in robot.groups:
        group.brake_mode = list(BrakeMode)[rng.integers(3)]
        kind = rng.integers(4)
        if kind == 0:
            group.set_voltage(float(rng.uniform(-12, 12)))
        elif kind == 1:
            group.set_velocity(float(rng.uniform(-1.2, 1.2)) * group.rated_speed)
        elif kind == 2:
            group.stop()
        else:  # full power one way: the current limit, wheels spinning
            group.set_voltage(12.0 if rng.random() < 0.5 else -12.0)
    for mechanism in robot.mechanisms.values():
        for _, sign, motor in mechanism.motors:
            motor.brake_mode = list(BrakeMode)[rng.integers(3)]
            kind = rng.integers(4)
            if kind == 0:
                motor.set_voltage(sign * float(rng.uniform(-12, 12)))
            elif kind == 1:
                motor.set_velocity(sign * float(rng.uniform(-1, 1)) * motor.rated_speed)
            elif kind == 2:
                motor.set_position(sign * float(rng.uniform(-6, 6)), float(rng.uniform(1, 20)))
            else:
                motor.stop()
    roll = rng.random()
    motor = list(robot.motors.values())[rng.integers(len(robot.motors))]
    if roll < 0.15:
        robot.lifted = not robot.lifted
    elif roll < 0.3:
        robot.external_force = rng.uniform(-60, 60, size=2)
        robot.external_torque = float(rng.uniform(-5, 5))
    elif roll < 0.4:
        robot.external_force = np.zeros(2)
        robot.external_torque = 0.0
    elif roll < 0.5:
        x, y, heading = rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-4, 4)
        robot.place((float(x), float(y), float(heading)))
    elif roll < 0.6:
        motor.current_limit_a = float(rng.uniform(0.3, 2.5))
    elif roll < 0.7:  # hot: its current is cut, by more the hotter it is
        motor.thermal.housing_c = float(rng.uniform(50, 80))
    elif roll < 0.75:
        motor.thermal.housing_c = 25.0


# --- one step, both ways, from the same state -----------------------------------------------


def test_the_layout_header_is_the_tables():
    """step_layout.h is written from layout.py's tables (python -m vexsim.physics.compiled)."""
    assert compiled.HEADER.read_text(encoding="utf-8") == compiled.header()


@pytest.mark.parametrize("path", ROBOTS, ids=lambda p: p.stem)
def test_each_step_of_every_example_robot_is_the_python_steps(library, path):
    rng = np.random.default_rng(16)
    with compiled.use("check"):
        robot = robot_of(path)
        for i in range(3000):
            if i % 60 == 0:
                commands(robot, rng)
            robot.advance(0.001)  # raises StepMismatch past the tolerance
    step = robot._compiled
    assert robot.step_name == "compiled" and step.check
    assert 0 < step.worst < 1e-10  # measured: about 1e-13
    assert robot.wall_hits >= 0 and np.isfinite(robot.qdot).all()


def test_the_checks_own_robot_takes_every_branch(library):
    """The robot the library is checked with when it's first built: traction wheels, dropped
    wheels that lift others off, a mechanism at its stops, a hot motor, a lifted robot."""
    assert compiled.self_check(library, steps=1200) < 1e-10


@pytest.mark.parametrize("dt", [0.0005, 0.002, 0.005])
def test_steps_of_other_lengths_agree_too(library, dt):
    rng = np.random.default_rng(3)
    with compiled.use("check"):
        robot = robot_of(ROOT / "examples" / "robots" / "1239e_2026-27.yaml")
        for i in range(1500):
            if i % 50 == 0:
                commands(robot, rng)
            robot.advance(dt)
    assert robot._compiled.worst < 1e-10


def test_a_battery_run_down_sags_the_same(library):
    """Down the whole of the battery's curve, each of its points, to empty."""
    config = load_robot(ROOT / "examples" / "robots" / "full_omni_6m.yaml")
    small = config.model_copy(update={"overrides": {"battery.capacity_mah": 1.0}})
    with compiled.use("check"):
        robot = Robot(small)
        for group in robot.groups:
            group.set_voltage(12.0)
        robot.lifted = True  # wheels in the air: current drawn, nowhere gone
        volts = [robot.power.bus_voltage]
        for _ in range(6000):
            robot.advance(0.001)
            volts.append(robot.power.bus_voltage)
    assert robot.step_name == "compiled" and robot.power.battery.soc == 0.0
    assert volts[0] > 13.4 and volts[-1] < 11.2 and robot.power.battery.charge_used_mah > 1.0


def wheels_off_the_floor(robot: Robot) -> int:
    return int((robot.contacts.normal == 0.0).sum())


def test_wheels_lifting_off_load_the_others_the_same(library):
    """Ground forces that tip the robot onto fewer wheels, down to two and past tipping:
    the active-set solve in C against NumPy's least squares."""
    rng = np.random.default_rng(8)
    lifted = set()
    with compiled.use("check"):
        for path in ROBOTS:
            robot = robot_of(path)
            for _ in range(300):
                size = 10 ** rng.uniform(0, 3.5)  # newtons: a nudge, to far past tipping
                angle = rng.uniform(0, 2 * math.pi)
                robot._ground_force = (size * math.cos(angle), size * math.sin(angle))
                robot.advance(0.001)
                lifted.add(wheels_off_the_floor(robot))
    assert {0, 1, 2} <= lifted and max(lifted) >= 3  # every case came up


# --- whole runs, both ways -------------------------------------------------------------------


def both_ways(make, seconds: float, mode: str) -> tuple[np.ndarray, np.ndarray]:
    """The same run with each step: its pose and velocities every 10 ms."""
    paths = []
    for step in ("python", "compiled"):
        with compiled.use(step):
            sim = make()
            sim.start(mode)
            rows = []
            for _ in range(round(seconds * 100)):
                sim.run_for(0.01)
                rows.append((*sim.robot.pose, *sim.robot.qdot))
            assert sim.robot.step_name == step
            sim.close()
        paths.append(np.array(rows))
    return paths[0], paths[1]


def assert_the_same_run(python: np.ndarray, other: np.ndarray) -> None:
    apart = np.hypot(*(python[:, :2] - other[:, :2]).T).max()
    turned = np.abs(python[:, 2] - other[:, 2]).max()
    assert apart < A_NANOMETRE and turned < A_TURN, (apart, turned)
    assert np.abs(python[:, 3:] - other[:, 3:]).max() < 1e-7  # velocities
    assert np.ptp(python[:, :2], axis=0).max() > 0.2  # (and the robot went somewhere)


def test_a_python_programs_run_is_the_same_run(library):
    """A closed loop on noisy sensors (tracking wheels, an IMU): 15 s of every chassis motion."""
    config = load_robot(ROOT / "examples" / "robots" / "full_omni_6m.yaml")
    program = load_program(ROOT / "examples" / "programs" / "tour.py")
    python, other = both_ways(
        lambda: Simulation(config, program=program, seed=1, echo=None), 15, "autonomous"
    )
    assert_the_same_run(python, other)


@pytest.mark.parametrize(
    ("robot", "field", "start"),
    [
        ("mecanum_4m", None, (-12, 12, 0)),
        ("xdrive_4m", None, (-12, 12, 0)),
        ("hdrive_5m", None, (-12, 12, 0)),  # a dropped center wheel
        ("traction_6m", None, (-12, 12, 0)),  # friction circles
        ("full_omni_6m", "practice_elements", (-48, 24, 0)),  # walls, a goal, pieces
        ("shaped_6m", "practice_elements", (-48, 24, 0)),  # by its shape
    ],
)
def test_a_driven_run_is_the_same_run(library, robot, field, start):
    config = load_robot(ROOT / "examples" / "robots" / f"{robot}.yaml")
    fld = load_field(FIELDS / f"{field}.yaml") if field else None
    python, other = both_ways(
        lambda: Simulation(
            config, field=fld, input_source=ScriptedInput.from_csv(INPUT), start=Pose(*start),
            echo=None,
        ),
        9,
        "driver",
    )  # fmt: skip
    assert_the_same_run(python, other)


def test_a_cpp_projects_run_is_the_same_run(library, build):
    """Robot code in its own process, with its own odometry, in lockstep with each step."""
    config = load_robot(ROOT / "examples" / "robots" / "full_omni_6m.yaml")
    exe = build(ROOT / "examples" / "pros_projects" / "minimal_pros4").executable
    python, other = both_ways(
        lambda: Simulation(config, program=CppProgram(exe), start=Pose(0, 0, 90), echo=None),
        6,
        "autonomous",
    )
    assert_the_same_run(python, other)


# --- the robot's objects, as views of the block ----------------------------------------------


def stepped(path: str = "1239e_2026-27", step: str = "compiled") -> Robot:
    with compiled.use(step):
        robot = robot_of(ROOT / "examples" / "robots" / f"{path}.yaml")
        robot.advance(0.001)
    return robot


def test_a_compiled_robots_objects_read_and_set_as_they_did(library):
    robot = stepped()
    motor = robot.motors[11] if 11 in robot.motors else next(iter(robot.motors.values()))
    assert isinstance(motor, V5Motor) and type(motor) is compiled.SharedMotor
    assert type(motor.position) is float and motor.mode is ControlMode.STOPPED
    motor.set_voltage(7.5)
    assert motor.mode is ControlMode.VOLTAGE and motor.command == 7.5
    motor.brake_mode = BrakeMode.HOLD
    assert motor.brake_mode is BrakeMode.HOLD and motor._hold_target == motor.position
    motor.current_limit_a = 1.0
    assert motor.current_limit_a == motor.effective_current_limit_a == 1.0
    motor.thermal.housing_c = 61.0  # two steps past where its current is first cut
    assert motor.over_temp and motor.effective_current_limit_a == 0.25
    assert robot.power.bus_voltage > 12 and 0.99 < robot.power.battery.soc <= 1.0
    for _ in range(50):
        robot.advance(0.001)
    assert motor.current_limited and abs(motor.current) == 0.25  # the C saw each of those
    assert robot.step_name == "compiled"


def test_a_contact_array_kept_from_one_step_isnt_the_next_steps(library):
    """As with the Python step, which makes new arrays each step."""
    robot = stepped("full_omni_6m")
    robot.group("left").set_voltage(12.0)
    robot.advance(0.001)
    kept = robot.contacts.slip
    before = kept.copy()
    for _ in range(20):
        robot.advance(0.001)
    assert (kept == before).all() and not (robot.contacts.slip == before).all()
    assert len(robot.contacts.normal) == len(robot.wheel_names)


def test_what_a_program_replaces_is_read_again(library):
    """A supply, an array, a thermal model swapped after the robot's first step: the next
    step is still the Python step's, on the new one."""
    rng = np.random.default_rng(5)
    with compiled.use("check"):
        robot = robot_of(ROOT / "examples" / "robots" / "1239e_2026-27.yaml")
        commands(robot, rng)
        robot.advance(0.001)
        step = robot._compiled
        old_power, old_battery = robot.power, robot.power.battery
        assert not step.external and type(old_power) is compiled.SharedPower
        charge = old_battery.soc

        supply = LoggedSupply(np.array([0.0, 1.0, 2.0]), np.array([12.6, 11.9, 12.3]))
        robot.power = supply
        for motor in robot.motors.values():
            motor.supply = supply
        motor = next(iter(robot.motors.values()))
        old_thermal, motor.thermal = motor.thermal, MotorThermal(initial_c=58.0)
        robot.external_force = np.array([30.0, 5.0])
        robot.qdot = robot.qdot.copy()
        for i in range(600):
            if i % 40 == 0:
                commands(robot, rng)
            robot.advance(0.001)
        assert step.external and robot.step_name == "compiled"
        assert supply.time == pytest.approx(0.6) and supply.battery_current_a > 0.3
        # what was replaced is a plain object again, holding its numbers as they were
        assert type(old_power).__name__ == "PowerSystem" and old_battery.soc == charge
        assert type(old_thermal) is MotorThermal and type(motor.thermal) is not MotorThermal
        assert motor.thermal.housing_c != 58.0  # the new one's heat moves with the motor's
    assert step.worst < 1e-10


def test_a_robot_it_cant_take_steps_in_python(library):
    class Bigger(Robot):
        pass

    with compiled.use("compiled"):
        odd = Bigger(load_robot(ROBOTS[0]))
        odd.advance(0.001)
        assert odd.step_name == "python" and "Bigger" in compiled.refused[-1]

        robot = robot_of(ROBOTS[0])
        robot.advance(0.001)
        assert robot.step_name == "compiled"
        motor = next(iter(robot.motors.values()))
        motor.supply = IdealSupply()  # not the robot's: the Python step takes it as it is
        robot.advance(0.001)
        assert robot.step_name == "python" and "supply" in robot._compiled.why
        motor.supply = robot.power
        robot.advance(0.001)
        assert robot.step_name == "compiled"


def test_a_step_that_cant_be_solved_says_so_either_way(library):
    for step in ("python", "compiled"):
        robot = stepped("full_omni_6m", step)
        robot.mass_matrix[:] = 0.0
        robot.contact_matrix[:] = 0.0
        with pytest.raises(np.linalg.LinAlgError, match="Singular"):
            robot.advance(0.001)


# --- which step, and where there's none ------------------------------------------------------


def test_the_step_is_picked_by_its_variable(monkeypatch, library):
    def taken() -> str:
        robot = robot_of(ROBOTS[0])
        robot.advance(0.001)
        return robot.step_name

    monkeypatch.setenv("VEXSIM_STEP", "python")
    assert compiled.mode() == "python" and taken() == "python"
    with compiled.use("compiled"):  # (what a test says wins)
        assert taken() == "compiled"
    monkeypatch.setenv("VEXSIM_STEP", "Compiled ")
    assert compiled.mode() == "compiled" and taken() == "compiled"
    monkeypatch.delenv("VEXSIM_STEP")
    assert compiled.mode() == "auto" and taken() == "compiled"
    monkeypatch.setenv("VEXSIM_STEP", "fast")
    with pytest.raises(ValueError, match="VEXSIM_STEP must be one of python, compiled, check"):
        compiled.mode()
    with pytest.raises(ValueError), compiled.use("fast"):
        pass


def test_without_a_compiler_robots_step_in_python(monkeypatch, tmp_path, fresh):
    monkeypatch.setenv("VEXSIM_CXX", str(tmp_path / "no-such-g++"))
    with using_cache(tmp_path):
        assert compiled.library() is None and "compiler not found" in compiled.reason()
        assert stepped(step="auto").step_name == "python"  # without a word
        with pytest.raises(compiled.StepUnavailable, match="compiler not found"):
            stepped(step="compiled")
        with pytest.raises(compiled.StepUnavailable, match="VEXSIM_STEP=check"):
            stepped(step="check")


def test_a_step_that_doesnt_build_isnt_tried_again(monkeypatch, tmp_path, fresh, library):
    broken = tmp_path / "step.c"
    broken.write_text("this isn't C\n")
    monkeypatch.setattr(lib_module, "SOURCE", broken)
    runs = []
    run = build_module._run
    monkeypatch.setattr(build_module, "_run", lambda cmd, **kw: runs.append(cmd) or run(cmd, **kw))
    with using_cache(tmp_path / "cache"):
        assert compiled.library() is None
        assert "didn't build" in compiled.reason() and "error" in compiled.reason()
        assert len(runs) == 1
        compiled.forget()  # another process, later
        assert compiled.library() is None and "didn't build" in compiled.reason()
        assert len(runs) == 1  # it read why, and didn't compile again
        assert stepped(step="auto").step_name == "python"


def test_a_step_that_fails_its_check_isnt_used(monkeypatch, tmp_path, fresh, library):
    def differs(lib):
        raise compiled.StepMismatch("motor 1 torque: 0.5 in Python, 0.6 compiled")

    monkeypatch.setattr(check_module, "self_check", differs)
    with using_cache(tmp_path):
        assert compiled.library() is None
        assert "failed its check: motor 1 torque" in compiled.reason()
        monkeypatch.undo()
        compiled.forget()
        assert compiled.library() is None  # it's written beside the library: not used later
        assert "failed its check" in compiled.reason()


def test_a_first_build_in_several_processes_at_once(tmp_path, library):
    """Sweep and benchmark workers all start by asking for the step: each builds its own
    and puts it in place, and all of them end up with one that works."""
    code = (
        "from vexsim.physics import compiled\n"
        "lib = compiled.library()\n"
        "print('ok' if lib else compiled.reason())\n"
    )
    env = {**os.environ, "VEXSIM_CACHE_DIR": str(tmp_path), "PYTHONPATH": str(ROOT)}
    started = [
        subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, text=True)
        for _ in range(4)
    ]
    assert [p.communicate(timeout=120)[0].strip() for p in started] == ["ok"] * 4
    folders = list(tmp_path.glob("step-*"))
    assert len(folders) == 1 and (folders[0] / "checked.txt").is_file()
    left = {p.name for p in folders[0].iterdir()}
    assert {compiled.LIB_NAME, "checked.txt"} <= left and "failed.txt" not in left
    if sys.platform != "win32":  # (there, a scanner can hold a file a moment past its use)
        assert len(left) == 2  # no half-built ones lying about


def test_a_library_found_again_isnt_checked_again(monkeypatch, tmp_path, fresh, library):
    with using_cache(tmp_path):
        first = compiled.library()
        assert first.built_s is not None and 0 < first.worst < 1e-10
        compiled.forget()
        monkeypatch.setattr(check_module, "self_check", lambda lib: pytest.fail("checked again"))
        again = compiled.library()
        assert again.path == first.path and again.built_s is None and again.worst is None
        assert again.agreement == first.worst == first.agreement  # kept beside it


# --- the rest of a millisecond (16.2): cheaper, and not a bit different -----------------------


def test_a_tracking_wheel_adds_up_as_it_did(monkeypatch):
    """The wheel's travel each step, by plain floats and one standard normal: the same
    numbers as ``robot.point_velocity`` and ``rng.normal(0.0, sigma)`` give, which is how
    it was written before."""

    def plainly(self, robot, dt):
        vx, vy = robot.point_velocity(self.rel)
        c, s = math.cos(self.heading), math.sin(self.heading)
        along, across = c * vx + s * vy, -s * vx + c * vy
        self.angle += along * dt / self.radius
        self.angle += self.rng.normal(0.0, self.spec.scrub * abs(across) * dt / self.radius)

    def angles(seconds: float) -> list[tuple]:
        config = load_robot(ROOT / "examples" / "robots" / "full_omni_6m.yaml")
        sim = Simulation(config, seed=3, echo=None, input_source=ScriptedInput.from_csv(INPUT))
        sim.start("driver")
        wheels = [d for d in sim.sensors.devices.values() if d.integrates]
        assert len(wheels) == 2 and all(d.spec.scrub > 0 for d in wheels)
        rows = []
        for _ in range(round(seconds * 1000)):
            sim.run_for(0.001)
            read = tuple(d.value and d.value.position_cdeg for d in wheels)  # (None at first)
            rows.append(tuple(d.angle for d in wheels) + read)
        return rows

    now = angles(4)
    monkeypatch.setattr(RotationDevice, "integrate", plainly)
    assert now == angles(4)  # to the last bit, every millisecond
    assert max(abs(a) for a in now[-1][:2]) > 1.0  # (and they turned)


def test_only_devices_with_something_to_do_are_asked_each_millisecond():
    config = load_robot(ROOT / "examples" / "robots" / "full_omni_6m.yaml")
    sim = Simulation(config, seed=3, echo=None)
    suite = sim.sensors
    asked: list[tuple[str, str, bool]] = []  # (what, the device's kind, a reading was waiting)

    def watch(device) -> None:
        if not device.integrates:  # motors, the IMU, a distance sensor: nothing adds up
            device.integrate = lambda robot, dt: asked.append(("integrate", device.kind, False))
        publish = device.publish

        def published(now_us: int) -> None:
            asked.append(("publish", device.kind, bool(device._pending)))
            publish(now_us)

        device.publish = published

    for device in suite.devices.values():
        watch(device)
    sim.start("driver")
    sim.run_for(0.03)  # three samples of everything
    assert not [a for a in asked if a[0] == "integrate"]
    assert all(waiting for _, _, waiting in asked)  # asked to publish only with one waiting
    motors = [d for d in suite.devices.values() if d.kind == "motor"]
    assert len(motors) == 6 and all(d.value is not None for d in motors)
    # and each reading still arrives when its latency is up: the 20 ms sample at 25 ms
    assert {d.published_at_us for d in motors} == {25_000}
    assert sum(d.integrates for d in suite.devices.values()) == 2  # the two tracking wheels


def test_the_noise_a_device_draws_is_numpys_normal():
    """``sigma * rng.standard_normal()`` for ``rng.normal(0.0, sigma)``: the same number
    from the same place in the stream, sigma zero included."""
    a = np.random.Generator(np.random.PCG64(7))
    b = np.random.Generator(np.random.PCG64(7))
    for sigma in [0.0, 1e-9, 3.5e-4, 0.0, 2.0] * 2000:
        assert a.normal(0.0, sigma) == sigma * b.standard_normal()
    assert a.random() == b.random()


# --- where it shows (16.3) ---------------------------------------------------------------------


@pytest.mark.parametrize("step", ["compiled", "python"])
def test_a_recorded_run_says_which_step_made_it(library, step, tmp_path, monkeypatch):
    """A run's worker is a process of its own: it takes the step ``VEXSIM_STEP`` says (the
    compiled one where it's unset), and the run's record says which."""
    from tests.test_ui import Recorder, doing, tour_workspace, wait_for
    from vexsim.app import runs
    from vexsim.app.runspec import RunSpec
    from vexsim.app.session import Session

    monkeypatch.setenv("VEXSIM_RUNS_DIR", str(tmp_path / "recorded-runs"))
    if step == "python":
        monkeypatch.setenv("VEXSIM_STEP", "python")
    else:
        monkeypatch.delenv("VEXSIM_STEP", raising=False)
    workspace = tour_workspace(tmp_path)
    heard = Recorder()
    spec = RunSpec(robot="robot.yaml", program="tour.py")
    session = Session("s-step", spec, base=workspace, listener=heard)
    session.start()
    try:
        session.command({"cmd": "speed", "value": 0})  # as fast as possible
        wait_for(lambda: heard.of("recorded"), timeout=60, about=lambda: doing(session))
    finally:
        session.stop()
    record = heard.of("recorded")[0]["run"]
    assert record["ended"] == "finished" and record["physics"] == step
    kept = runs.read_record(runs.runs_root(workspace), record["id"])
    assert kept.physics == step and kept.duration > 10


def test_a_record_from_before_they_said_still_reads(tmp_path):
    from vexsim.app import runs
    from vexsim.app.runspec import RunSpec

    record = runs.RunRecord(
        id="20261101-120000-ab12", name="An old run", created=1.0, command="vexsim run r.yaml",
        spec=RunSpec(robot="r.yaml"), mode="driver", robot="R", field="F", duration=2.0,
        ended="stopped", message=None, pose_error=None, samples=3,
    )  # fmt: skip
    assert record.physics is None
    old = record.model_dump(mode="json")
    del old["physics"]  # as run.json files were written before
    assert runs.RunRecord.model_validate(old) == record
    with pytest.raises(ValueError):
        runs.RunRecord.model_validate({**old, "physics": "fast"})


def test_vexsim_ui_builds_the_step_off_to_the_side(library, tmp_path, fresh, monkeypatch, capsys):
    """So the first run after installing doesn't wait for a compiler: its worker finds the
    library made."""
    import uvicorn

    from vexsim.ui.server import serving

    with using_cache(tmp_path / "cache"):
        thread = serving.prepare_step()
        thread.join(120)
        assert not thread.is_alive()
        assert list((tmp_path / "cache").glob(f"step-*/{compiled.LIB_NAME}"))
        assert list((tmp_path / "cache").glob("step-*/checked.txt"))  # and checked
    monkeypatch.setenv("VEXSIM_STEP", "python")  # where it's told not to use one, none is built
    with using_cache(tmp_path / "unused"):
        compiled.forget()
        serving.prepare_step().join(120)
        assert not list((tmp_path / "unused").glob("step-*"))

    done = []  # and `vexsim ui` does it as it starts
    monkeypatch.setattr(serving, "prepare_step", lambda: done.append("prepared"))
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, sockets=None: done.append("served"))
    serving.serve(tmp_path, open_browser=False)
    assert done == ["prepared", "served"] and "vexsim UI for" in capsys.readouterr().out

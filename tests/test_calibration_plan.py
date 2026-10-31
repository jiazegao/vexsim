"""Phase 14.3: where each calibration test runs on a field with its elements in place
(calibration/plan.py), and what the simulator gained for the session: lifted robots, robots
put down by hand, a hand over a distance sensor."""

import math
import re

import numpy as np
import pytest
import yaml

from tests.conftest import EXAMPLE_ROBOT, ROOT
from vexsim.calibration import plan as planning
from vexsim.calibration.plan import (
    MARGIN_IN,
    PUSH_MARGIN_IN,
    VARIANTS,
    FieldMap,
    make_plan,
    ray_lengths,
    shape_samples,
    variant_robot,
    write_plan,
)
from vexsim.calibration.routine import REFERENCE_SPEED_M_S, drive_tests, standard_routine
from vexsim.cli import main
from vexsim.config import load_field, load_robot
from vexsim.config.field import FieldConfig, _distance_to
from vexsim.physics.arena import Arena
from vexsim.physics.kinematics import DriveKinematics
from vexsim.physics.params import resolve_params
from vexsim.physics.robot import Robot
from vexsim.runtime.simulation import Simulation
from vexsim.units import in_to_m

ROBOT_1239E = ROOT / "examples" / "robots" / "1239e_2026-27.yaml"
FIELD_1239E = ROOT / "examples" / "fields" / "1239e_2026-27.yaml"
XDRIVE = ROOT / "examples" / "robots" / "xdrive_4m.yaml"
CONFIG = load_robot(ROBOT_1239E)
FIELD = load_field(FIELD_1239E)


@pytest.fixture(scope="module")
def plan():
    return make_plan(CONFIG, FIELD, workers=4)


def moved(points, pose):
    return planning._moved(np.asarray(points, dtype=float), pose)


def covered(config, poses, spot):
    """The robot's edge at every pose of a path (start frame), with the path started at
    spot: what the plan has to keep clear."""
    _, edge = shape_samples(config)
    poses = planning._dense(np.asarray(poses, dtype=float), config.body.outline.reach())
    x, y, heading = spot
    h = math.radians(heading)
    c, s = math.cos(h), math.sin(h)
    field = [(x + c * px - s * py, y + s * px + c * py, heading + ph) for px, py, ph in poses]
    return np.concatenate([moved(edge, p) for p in field])


# --- the simulator ---------------------------------------------------------------------------


def test_a_robot_on_its_side_spins_its_wheels_where_it_is():
    def drive(lifted):
        robot = Robot(CONFIG, params=resolve_params(CONFIG.overrides), pose=(0.0, 0.0, 0.0))
        robot.lifted = lifted
        for gear in CONFIG.drivetrain.gearing.values():
            for port in gear.motors:
                robot.motors[abs(port)].set_voltage(12.0 if port > 0 else -12.0)
        for _ in range(1000):
            robot.advance(0.001)
        rpm = robot.group_speed("left") * 60 / math.tau
        return robot.pose, rpm

    (x, y, heading), free = drive(lifted=True)
    assert (x, y, heading) == (0.0, 0.0, 0.0)  # nothing moves it
    (x, _, _), loaded = drive(lifted=False)
    assert x > 1.0  # on the floor it drives off
    assert free > loaded > 0.8 * free  # and its wheels turn a little slower


def test_a_robot_put_down_by_hand_stands_still_where_it_was_put():
    robot = Robot(CONFIG, params=resolve_params(CONFIG.overrides), pose=(0.0, 0.0, 0.0))
    robot.qdot[:3] = (1.0, 0.0, 2.0)
    robot.place((1.0, -0.5, math.radians(350)))
    x, y, heading = robot.pose
    assert (x, y) == pytest.approx((1.0, -0.5))
    assert heading == pytest.approx(math.radians(-10))  # turned the short way, as carried
    assert robot.body_velocity == (0.0, 0.0, 0.0)


def test_a_hand_over_a_distance_sensor_reads_close():
    config = load_robot(EXAMPLE_ROBOT)
    sim = Simulation(config, record=False, echo=None)
    sensor = sim.sensors.devices[13]
    far = sensor.true_distance_mm()
    sensor.blocked_mm = 30.0
    assert sensor.true_distance_mm() == 30.0
    sensor.blocked_mm = None
    assert sensor.true_distance_mm() == far > 500


# --- the field ---------------------------------------------------------------------------------


def test_rays_go_as_far_as_the_arenas():
    arena = Arena.of(FIELD)
    rng = np.random.default_rng(3)
    origins = rng.uniform(-60, 60, (300, 2))
    origins = origins[FieldMap(FIELD).distances(origins) > 0.5]
    angles = rng.uniform(-math.pi, math.pi, len(origins))
    for height in (None, 4.19, 9.12):
        heights = None if height is None else np.full(len(origins), height)
        ours = ray_lengths(FIELD, origins, angles, heights)
        for o, a, inches in zip(origins, angles, ours, strict=True):
            meters = arena.ray(
                in_to_m(1) * o, a, pieces=False, height=None if height is None else in_to_m(height)
            )
            assert inches == pytest.approx(meters / in_to_m(1), abs=1e-6)


def test_the_field_map_knows_how_far_everything_is():
    fmap = FieldMap(FIELD)
    rng = np.random.default_rng(4)
    points = rng.uniform(-75, 75, (500, 2))
    half = FIELD.size_in[0] / 2
    for p, d in zip(points, fmap.distances(points), strict=True):
        walls = half - max(abs(p[0]), abs(p[1]))
        assert d == pytest.approx(min(walls, *(_distance_to(o, tuple(p)) for o in FIELD.obstacles)))
    assert fmap.near(np.array([[0.0, 4.0]]), 2.0) == ["center base"]
    assert "the +x wall (right on the map)" in fmap.near(np.array([[69.5, 0.0]]), 1.0)


# --- the tests and their spread ------------------------------------------------------------------


def test_the_driving_tests_are_the_routines_maneuvers_each_from_rest():
    tests = drive_tests(CONFIG)
    assert list(tests) == ["straight", "spin", "arc"]
    assert list(drive_tests(load_robot(XDRIVE))) == ["straight", "strafe", "spin", "arc"]
    routine = {s.name: s for s in standard_routine(CONFIG)}
    for steps in tests.values():
        assert steps[0].name == "settle" and steps[0].still
        assert steps[-1].brake == "brake" and steps[-1].still
        for step in steps:
            if not step.still:
                assert step == routine[step.name]  # the routine's own speeds and times
    slow = drive_tests(CONFIG, 0.55)["straight"]
    f = REFERENCE_SPEED_M_S / DriveKinematics.from_config(CONFIG).top_speeds()[0]
    assert slow[1].forward == pytest.approx(0.55 * f)
    assert slow[1].seconds == pytest.approx(0.55 * 0.5, abs=0.01)
    assert [s.seconds for s in slow if s.still] == [0.5, 0.8, 0.5]


def test_the_variants_spread_the_parameters_each_test_measures():
    names = [v.name for v in VARIANTS]
    assert names[0] == "as configured"
    config, overrides = variant_robot(CONFIG, VARIANTS[0])
    assert config is CONFIG and overrides == {}
    further = VARIANTS[names.index("rolls further")]
    config, overrides = variant_robot(CONFIG, further)
    assert overrides == pytest.approx(
        {
            "wheel.omni.longitudinal_mu": 0.9 * 1.2,
            "wheel.omni.lateral_mu": 0.2 * 0.7,
            "wheel.omni.rolling_resistance": 0.1 * 0.6,
            "motor.natural_free_rpm": 121.0 * 1.1,
        }
    )
    assert config.body.mass_kg == pytest.approx(7.0 * 0.85)


# --- 1239E's plan --------------------------------------------------------------------------------


def test_every_test_fits_on_1239es_field_clear_of_every_element(plan):
    fmap = plan.fmap
    assert [t.key for t in plan.tests] == ["push", "straight", "spin", "arc", "sweep_1", "sweep_2"]
    assert plan.missing == []
    for test in plan.drive:
        assert test.scale == 1.0 and test.spot.pose[2] % 90 == 0  # full speed, square
        # what every variant's path covers, from the spot, by the shape's edge
        edge = np.concatenate([covered(CONFIG, p.poses, test.spot.pose) for p in test.paths])
        room = fmap.distances(edge).min()
        assert room >= MARGIN_IN
        assert room == pytest.approx(test.spot.clearance_in, abs=0.4)
        far = max(p.motor_deg for p in test.paths)
        assert far < test.max_motor_deg < 1.3 * far
        assert max(p.turn_deg for p in test.paths) < test.max_turn_deg
    assert plan.push.length_in == 96
    assert fmap.distances(moved(plan.push.points, plan.push.spot.pose)).min() >= PUSH_MARGIN_IN
    for test in plan.sweeps:
        assert fmap.distances(moved(test.points, test.spot.pose)).min() >= MARGIN_IN


def test_the_session_numbers_its_tests_as_the_maps_do(plan):
    keys = [key for key, _, _ in plan.session()]
    assert keys == [
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
    ]
    assert [plan.number(t) for t in plan.tests] == [5, 6, 7, 8, 9, 10]


def test_a_tape_measure_is_enough_to_put_the_robot_on_its_spot(plan):
    x0, y0, x1, y1 = CONFIG.body.outline.bounds
    for test in plan.tests:
        spot = test.spot
        assert len(spot.short) == 3 and all(len(line) <= 46 for line in spot.short)
        for a, b, label in spot.measures:
            inches = float(label.removesuffix(" in"))
            assert math.dist(a, b) == pytest.approx(inches, abs=0.051)
            assert any(abs(abs(v) - FIELD.size_in[0] / 2) < 1e-9 for v in a)  # from a wall
            if test.key != "push":  # to the robot's side (the push lane's are its tape lines)
                bx, by = moved([b], (0, 0, 0))[0] - spot.pose[:2]
                h = math.radians(-spot.pose[2])
                rx, ry = bx * math.cos(h) - by * math.sin(h), bx * math.sin(h) + by * math.cos(h)
                assert min(abs(rx - x0), abs(rx - x1), abs(ry - y0), abs(ry - y1)) < 1e-6
                assert inches * 2 == pytest.approx(round(inches * 2))  # to the half inch
        numbers = [float(n) for line in spot.short for n in re.findall(r"([\d.]+) in", line)]
        measured = [float(m[2].removesuffix(" in")) for m in spot.measures]
        if test.key == "push":  # its side, then where the start line goes, and how far
            assert numbers == [measured[1], measured[2], test.length_in]
        else:
            assert numbers == measured


def test_the_plan_is_written_with_a_map_of_each_spot(plan, tmp_path):
    pytest.importorskip("matplotlib")
    paths = write_plan(plan, tmp_path)
    names = sorted(p.name for p in paths)
    assert names == [
        "map_10_sweep_2.png",
        "map_5_push.png",
        "map_6_straight.png",
        "map_7_spin.png",
        "map_8_arc.png",
        "map_9_sweep_1.png",
        "plan.txt",
        "plan.yaml",
    ]
    text = (tmp_path / "plan.txt").read_text()
    assert "6. Straight (3 runs)" in text and "Its back 41 in from the -x wall" in text
    data = yaml.safe_load((tmp_path / "plan.yaml").read_text())
    straight = data["tests"][1]
    assert straight["key"] == "straight" and straight["spot"]["x_in"] == -22.2
    assert [s["name"] for s in straight["steps"]] == [
        "settle",
        "launch",
        "coast",
        "reverse",
        "brake",
    ]


def test_a_test_with_less_room_is_slowed_down(monkeypatch):
    monkeypatch.setattr(planning, "SCALES", (1.0, 0.85))
    small = make_plan(CONFIG, FieldConfig(size_in=(60, 60)), workers=4)
    scales = {t.key: t.scale for t in small.drive}
    assert scales == {"straight": 0.85, "spin": 1.0, "arc": 0.85}
    for test in small.drive:
        assert test.spot.clearance_in >= MARGIN_IN
    assert small.push.spot is None and "the +x wall (right on the map)" in small.push.blocked_by
    assert "5. Straight (3 runs) (at 85% speed: there's less room)" in small.text()


def test_without_room_the_plan_says_whats_in_the_way(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(planning, "SCALES", (1.0,))
    field = tmp_path / "tiny.yaml"
    field.write_text("version: 1\nname: a box\nsize_in: [30, 30]\n")
    out = tmp_path / "plan"
    code = main(["calibration", "plan", str(ROBOT_1239E), str(field), "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 1
    assert "No room for it, even at the slowest." in text
    assert "In the way: the +x wall (right on the map)" in text
    assert (out / "plan.txt").is_file() and not list(out.glob("map_*.png"))

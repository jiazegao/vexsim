"""Phase 10: game elements on the field: fixed obstacles and movable pieces."""

import math

import numpy as np
import pytest

from tests.conftest import EXAMPLE_ROBOT, ROOT
from vexsim.algorithms.localization.base import Pose
from vexsim.config import load_field, load_robot, validate_field
from vexsim.config.yaml_io import load_yaml_file
from vexsim.physics.arena import Shape
from vexsim.runtime.simulation import Simulation
from vexsim.units import in_to_m, m_to_in

CONFIG = load_robot(EXAMPLE_ROBOT)  # 15 x 15 in
PRACTICE = ROOT / "examples" / "fields" / "practice_elements.yaml"
BALL = {"type": "piece", "diameter_in": 7, "mass_kg": 0.25}


def field(*elements):
    return load_field({"elements": list(elements)})


def sim_on(fld, pose, **kw) -> Simulation:
    return Simulation(CONFIG, field=fld, start=pose, echo=None, **kw)


def drive(sim, left=0.5, right=0.5):
    for name, f in (("left", left), ("right", right)):
        group = sim.robot.group(name)
        group.set_velocity(f * group.rated_speed)


def pose_in(sim):
    x, y, h = sim.robot.pose
    return m_to_in(x), m_to_in(y), math.degrees(h)


def piece_in(sim, i=0):
    x, y = sim.arena.pieces.position[i]
    return m_to_in(x), m_to_in(y)


# --- config ----------------------------------------------------------------------------------


def test_example_field_is_clean():
    report = validate_field(PRACTICE)
    assert report.ok and report.issues == []
    cfg = report.config
    assert len(cfg.obstacles) == 3 and len(cfg.pieces) == 6


def test_element_errors_and_warnings():
    bad = validate_field({"elements": [{"type": "obstacle", "shape": "rect", "pos_in": [0, 0]}]})
    assert not bad.ok and "needs size_in" in str(bad.issues)
    bad = validate_field({"elements": [{"type": "obstacle", "shape": "circle", "pos_in": [0, 0]}]})
    assert not bad.ok and "needs diameter_in" in str(bad.issues)
    outside = validate_field({"elements": [{**BALL, "pos_in": [80, 0]}]})
    assert not outside.ok and "outside the walls" in str(outside.issues)
    overlapping = validate_field(
        {
            "elements": [
                {"type": "obstacle", "shape": "rect", "pos_in": [0, 0], "size_in": [20, 4]},
                {**BALL, "pos_in": [8, 4]},
                {**BALL, "pos_in": [30, 0]},
                {**BALL, "pos_in": [34, 0]},
            ]
        }
    )
    assert overlapping.ok
    messages = [i.message for i in overlapping.warnings]
    assert messages == [
        "the piece starts overlapping obstacle elements[0]",
        "the piece starts overlapping piece elements[3]",
    ]


# --- geometry --------------------------------------------------------------------------------


def test_shapes_measure_distances_and_rays():
    rect = Shape(False, np.array([0.0, 0.0]), math.pi / 2, (1.0, 0.25))  # long along y
    d, n, _ = rect.signed_distance(np.array([0.5, 0.0]))
    assert d == pytest.approx(0.25) and n == pytest.approx([1.0, 0.0])
    d, n, _ = rect.signed_distance(np.array([0.0, 0.9]))
    assert d == pytest.approx(-0.1) and n == pytest.approx([0.0, 1.0])  # inside, near an end
    assert rect.ray(np.array([-2.0, 0.0]), np.array([1.0, 0.0])) == pytest.approx(1.75)
    assert rect.ray(np.array([-2.0, 2.0]), np.array([1.0, 0.0])) is None
    circle = Shape(True, np.array([1.0, 1.0]), 0.0, (0.5, 0.5))
    assert circle.signed_distance(np.array([1.0, 2.0]))[0] == pytest.approx(0.5)
    assert circle.ray(np.array([1.0, -1.0]), np.array([0.0, 1.0])) == pytest.approx(1.5)


# --- the robot against obstacles ------------------------------------------------------------


def test_robot_stops_at_a_barrier_and_squares_up():
    barrier = {"type": "obstacle", "shape": "rect", "pos_in": [0, 0], "size_in": [48, 3]}
    sim = sim_on(field(barrier), Pose(-6, -30, 80))  # approaching at an angle
    drive(sim)
    sim.run_for(3.0)
    x, y, heading = pose_in(sim)
    assert y == pytest.approx(-1.5 - 7.5, abs=0.05)  # flush against the barrier's face
    assert heading == pytest.approx(90.0, abs=0.5)
    assert sim.robot.wall_contacts  # obstacle contacts count with the walls'


def test_robot_stops_at_a_round_goal():
    goal = {"type": "obstacle", "shape": "circle", "pos_in": [0, 0], "diameter_in": 10}
    sim = sim_on(field(goal), Pose(-40, 0, 0))
    drive(sim)
    sim.run_for(3.0)
    assert pose_in(sim)[0] == pytest.approx(-5 - 7.5, abs=0.05)


def test_robot_meeting_a_corner_turns_flat_against_a_face():
    # A diamond's corner, met 2 in off center: the robot pivots onto the nearer face.
    post = {"type": "obstacle", "shape": "rect", "pos_in": [0, 0], "size_in": [6, 6]}
    sim = sim_on(field({**post, "heading_deg": 45}), Pose(-30, 2, 0))
    drive(sim)
    sim.run_for(3.0)
    assert pose_in(sim)[2] == pytest.approx(-45.0, abs=0.5)
    footprint = Shape(False, np.array(sim.robot.pose[:2]), sim.robot.heading, (0.1905, 0.1905))
    diamond = sim.arena.obstacles[0]
    deepest = min(
        [footprint.signed_distance(c)[0] for c in diamond.corners()]
        + [diamond.signed_distance(c)[0] for c in footprint.corners()]
    )
    assert deepest > -0.002  # m: never more than a step's travel inside


# --- pieces ----------------------------------------------------------------------------------


def test_robot_pushes_a_piece_into_the_wall_and_stalls():
    sim = sim_on(field({**BALL, "pos_in": [24, 0]}), Pose(0, 0, 0))
    drive(sim)
    sim.run_for(1.0)
    bx, by = piece_in(sim)
    assert bx == pytest.approx(pose_in(sim)[0] + 7.5 + 3.5, abs=0.2)  # ahead, touching
    assert abs(by) < 0.1
    sim.run_for(2.5)
    bx, _ = piece_in(sim)
    assert bx == pytest.approx(72 - 3.5, abs=0.05)  # against the wall...
    assert pose_in(sim)[0] == pytest.approx(72 - 7 - 7.5, abs=0.05)  # ...and the robot behind it
    assert abs(sim.robot.body_velocity[0]) < 0.02  # stalled, not creeping through


def test_pushed_piece_slides_to_a_stop():
    sim = sim_on(field({**BALL, "pos_in": [0, 30], "friction": 0.4}), Pose(-40, -40, 0))
    sim.arena.pieces.velocity[0] = [1.5, 0.0]
    sim.run_for(1.0)
    expected = 1.5**2 / (2 * 0.4 * 9.81)  # v^2 / (2 mu g)
    assert in_to_m(piece_in(sim)[0]) == pytest.approx(expected, rel=0.02)
    assert np.abs(sim.arena.pieces.velocity).max() == 0.0


def test_piece_bounces_off_a_wall():
    ball = {**BALL, "pos_in": [60, 0], "friction": 0.0, "restitution": 0.5}
    sim = sim_on(field(ball), Pose(-40, -40, 0))
    sim.arena.pieces.velocity[0] = [2.0, 0.0]
    sim.run_for(0.2)
    assert sim.arena.pieces.velocity[0] == pytest.approx([-1.0, 0.0])


def test_pieces_trade_momentum():
    a = {**BALL, "pos_in": [0, 0], "friction": 0.0, "restitution": 1.0}
    b = {**BALL, "pos_in": [20, 0], "friction": 0.0, "restitution": 1.0}
    sim = sim_on(field(a, b), Pose(-40, -40, 0))
    sim.arena.pieces.velocity[0] = [1.0, 0.0]
    sim.run_for(0.6)
    v = sim.arena.pieces.velocity
    assert v[0] == pytest.approx([0.0, 0.0], abs=1e-6)  # equal masses, elastic: they swap
    assert v[1] == pytest.approx([1.0, 0.0], abs=1e-6)


def test_still_field_matches_an_empty_one():
    def run(fld):
        sim = sim_on(fld, Pose(-40, -40, 0))
        drive(sim, 0.5, 0.25)
        sim.run_for(2.0)
        return sim.robot.pose

    far = field({**BALL, "pos_in": [60, 60]})
    assert run(far) == run(None)
    assert sim_on(None, Pose(0, 0, 0)).arena is None  # an empty field just has walls


# --- sensing ---------------------------------------------------------------------------------


def test_distance_sensor_sees_elements():
    barrier = {"type": "obstacle", "shape": "rect", "pos_in": [0, 0], "size_in": [48, 3]}
    sim = sim_on(field(barrier), Pose(-10, -40, 90), noise="ideal")
    sim.run_for(0.1)
    assert sim.sensors.devices[13].value == round((40 - 7 - 1.5) * 25.4)  # sensor 7 in ahead
    sim = sim_on(field({**BALL, "pos_in": [-10, -10]}), Pose(-10, -40, 90), noise="ideal")
    sim.run_for(0.1)
    assert sim.sensors.devices[13].value == round((30 - 7 - 3.5) * 25.4)


def test_obstacles_hide_the_gps_code_strip():
    data = load_yaml_file(EXAMPLE_ROBOT)
    data["sensors"].append({"type": "gps", "port": 15, "pos_in": [0, 0], "mount_yaw_deg": 0})
    cfg = load_robot(data)
    wall = {"type": "obstacle", "shape": "rect", "pos_in": [0, 0], "size_in": [4, 140]}
    open_sim = Simulation(cfg, start=Pose(-30, 0, 0), echo=None)
    blocked = Simulation(cfg, field=field(wall), start=Pose(-30, 0, 0), echo=None)
    for sim in (open_sim, blocked):
        sim.run_for(0.2)
    assert open_sim.sensors.devices[15].value.fix
    assert blocked.sensors.devices[15].value is None  # never saw the strip


def test_viewer_draws_elements(tmp_path):
    pytest.importorskip("pygame")
    from vexsim.viz.viewer import LiveSource, Viewer

    sim = sim_on(load_field(PRACTICE), Pose(-48, 24, 0))
    snap = LiveSource(lambda: sim).snapshot()
    assert len(snap.obstacles) == 3 and len(snap.pieces) == 6
    assert snap.obstacles[1][0] == "circle" and snap.obstacles[0][0] == "polygon"
    viewer = Viewer(LiveSource(lambda: sim), headless=True)
    viewer.draw(snap)
    viewer.save(str(tmp_path / "field.png"))
    assert (tmp_path / "field.png").stat().st_size > 5000

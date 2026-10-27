"""Phase 12.2: robots whose body is a shape (``body.shape``: rectangles, circles and
outlines) instead of a footprint rectangle: the config, and collisions by the shape's outside
edge with the walls, field elements and pieces."""

import copy
import math

import numpy as np
import pytest

from tests.conftest import EXAMPLE_ROBOT, ROOT
from vexsim.algorithms.localization.base import Pose
from vexsim.app.frames import robot_scene
from vexsim.app.runspec import start_blocked
from vexsim.cli import main
from vexsim.config import load_field, load_robot, validate_robot
from vexsim.config.summary import robot_summary
from vexsim.config.yaml_io import load_yaml_file
from vexsim.runtime.simulation import Simulation
from vexsim.units import m_to_in

SHAPED = ROOT / "examples" / "robots" / "shaped_6m.yaml"
CONFIG = load_robot(SHAPED)  # a 12 x 14 in base, a 6 in round bumper at the back, a clamp
PRACTICE = ROOT / "examples" / "fields" / "practice_elements.yaml"
# The clamp's notch: from (7, 0) its sides go out to (9, +-2.5). A circle of radius r sits in
# it with its center this far ahead of the robot's origin:
NOTCH_SIDE = math.hypot(2, 2.5) / 2.5


def seat(radius: float) -> float:
    return 7 + radius * NOTCH_SIDE


def errors(report) -> dict[str, str]:
    return {i.location: i.message for i in report.issues if i.severity == "error"}


def warnings(report) -> dict[str, str]:
    return {i.location: i.message for i in report.issues if i.severity == "warning"}


def with_shape(shape, robot=EXAMPLE_ROBOT) -> dict:
    data = copy.deepcopy(load_yaml_file(robot))
    data["body"].pop("footprint_in", None)
    data["body"]["shape"] = shape
    return data


def sim_on(elements, pose: Pose, config=CONFIG) -> Simulation:
    return Simulation(config, field=load_field({"elements": elements}), start=pose, echo=None)


def drive(sim, speed=0.4):
    for name in ("left", "right"):
        group = sim.robot.group(name)
        group.set_velocity(speed * group.rated_speed)


def pose_in(sim):
    x, y, h = sim.robot.pose
    return m_to_in(x), m_to_in(y), math.degrees(h)


def robot_frame(sim, point) -> tuple[float, float]:
    """A field point (m) in the robot's frame (in)."""
    x, y, h = sim.robot.pose
    dx, dy = point[0] - x, point[1] - y
    c, s = math.cos(h), math.sin(h)
    return m_to_in(c * dx + s * dy), m_to_in(-s * dx + c * dy)


# --- the config ------------------------------------------------------------------------------


def test_the_example_shaped_robot_is_clean():
    report = validate_robot(SHAPED)
    assert report.ok and report.warnings == []
    assert CONFIG.body.size_in == pytest.approx((18, 14))
    assert "shape 18.0 x 14.0 in (3 parts, 219 sq in)" in robot_summary(CONFIG)[1]
    assert "(auto: uniform over the shape)" in robot_summary(CONFIG)[2]


def test_a_body_is_a_footprint_or_a_shape():
    both = with_shape([{"type": "rect", "size_in": [15, 15]}])
    both["body"]["footprint_in"] = [15, 15]
    assert errors(validate_robot(both)) == {
        "body": "the body has both footprint_in and shape; keep one"
    }
    neither = with_shape(None)
    del neither["body"]["shape"]
    assert "needs footprint_in: [length, width]" in errors(validate_robot(neither))["body"]
    assert "needs a part" in errors(validate_robot(with_shape([])))["body"]


def test_a_shapes_parts_are_checked_where_they_are_written():
    report = validate_robot(
        with_shape([
            {"type": "rect", "size_in": [15, 15]},
            {"type": "outline", "points_in": [[7, 7], [9, -7], [9, 7], [7, -7]]},
            {"type": "circle", "diameter_in": 0},
            {"type": "blob"},
        ])
    )  # fmt: skip
    found = errors(report)
    assert found["body.shape[1]"] == (
        "the outline's points (numbered from 0) don't make a shape: it crosses itself: the edge "
        "from point 0 to 1 meets the edge from point 2 to 3"
    )
    assert found["body.shape[2].diameter_in"] == "Input should be greater than 0"
    assert (
        "does not match any of the expected tags: 'rect', 'circle', 'outline'"
        in found["body.shape[3]"]
    )


def test_what_must_be_inside_the_shape_and_how_big_it_may_be():
    small = validate_robot(with_shape([{"type": "rect", "size_in": [15, 9]}]))
    assert errors(small)["drivetrain.wheels[0].pos_in"] == (
        "wheel 'lf' at (5.5, 6) is outside the robot's shape"
    )
    wide = with_shape([
        {"type": "rect", "size_in": [15, 15]},
        {"type": "circle", "pos_in": [-11, 0], "diameter_in": 2},  # not touching the rest
        {"type": "outline", "points_in": [[7.5, 7.5], [9.5, 7.5], [7.5, 5]]},
    ])  # fmt: skip
    report = validate_robot(wide)
    assert report.ok
    assert warnings(report) == {
        "body.shape": "21.5 x 15 in shape exceeds the 18 in starting size limit",
        "body.shape[1]": "this part doesn't touch the rest of the shape (it moves with the robot "
        "all the same)",
    }
    # on the edge is inside: the IMU on the circle's rim, in its own corner of the shape
    wide["sensors"][0]["pos_in"] = [-12, 0]
    assert validate_robot(wide).ok


def test_inertia_comes_from_the_shapes_area():
    box = load_robot(with_shape([{"type": "rect", "size_in": [15, 15]}]))
    assert box.body.yaw_inertia_kgm2() == pytest.approx(
        load_robot(EXAMPLE_ROBOT).body.yaw_inertia_kgm2()
    )
    # the example: a plate of its area and spread; the round bumper and clamp add to the box's
    area, (cx, cy), polar = CONFIG.body.outline.moments
    assert CONFIG.body.yaw_inertia_kgm2() == pytest.approx(6.5 * polar / area * 0.0254**2)
    assert 0.15 < CONFIG.body.yaw_inertia_kgm2() < 0.16


# --- collisions by the shape -----------------------------------------------------------------


def test_a_round_bumper_touches_the_wall_where_it_bulges():
    # backing into the -x wall, turned 15 degrees: only the bumper reaches it
    sim = Simulation(CONFIG, start=Pose(-55, 0, 15), echo=None)
    drive(sim, -0.5)
    deepest = 0.0
    for _ in range(30):
        sim.run_for(0.1)
        deepest = max([deepest, *(c.depth_m for c in sim.robot.wall_contacts)])
    x, _, heading = pose_in(sim)
    outline = CONFIG.body.outline
    back = outline.extreme((-math.cos(math.radians(heading)), math.sin(math.radians(heading))))
    assert x - back == pytest.approx(-72, abs=0.02)  # its furthest point back is at the wall
    [contact] = sim.robot.wall_contacts
    on_robot = robot_frame(sim, contact.point)
    assert math.dist(on_robot, (-6, 0)) == pytest.approx(3, abs=0.01)  # on the bumper's rim
    assert abs(on_robot[1]) > 0.5  # not its axis-aligned back point: wherever it bulges most
    assert deepest < 0.002  # m


def test_a_goal_post_settles_into_the_notch():
    post = {
        "type": "obstacle",
        "name": "post",
        "shape": "circle",
        "pos_in": [20, 0],
        "diameter_in": 3,
    }
    sim = sim_on([post], Pose(0, 0, 0))
    drive(sim)
    sim.run_for(3.0)
    x, y, _ = pose_in(sim)
    assert 20 - x == pytest.approx(seat(1.5), abs=0.02)  # in the notch, against both sides
    assert abs(y) < 0.01
    sides = sorted((robot_frame(sim, c.point) for c in sim.robot.wall_contacts), key=lambda p: p[1])
    assert len(sides) == 2 and sides[0][1] == pytest.approx(-sides[1][1], abs=0.01)
    assert sides[1][1] > 0.5
    # a rectangle the shape's size would have stopped with the post ahead of its front
    assert 20 - x < 9 + 1.5 - 1


def test_a_barrier_meets_the_clamps_jaws_first():
    barrier = {"type": "obstacle", "shape": "rect", "pos_in": [20, 0], "size_in": [3, 48]}
    sim = sim_on([barrier], Pose(0, 0, 0))
    drive(sim)
    sim.run_for(3.0)
    assert pose_in(sim)[0] == pytest.approx(20 - 1.5 - 9, abs=0.02)  # the jaws reach 9 in
    assert len(sim.robot.wall_contacts) >= 2


def test_the_notch_centers_a_ball_and_pushes_it():
    ball = {"type": "piece", "pos_in": [16, 1.0], "diameter_in": 3.0, "mass_kg": 0.1}
    sim = sim_on([ball], Pose(0, 0, 0))
    drive(sim)
    sim.run_for(2.0)
    x, y, _ = pose_in(sim)
    bx, by = (m_to_in(v) for v in sim.arena.pieces.position[0])
    assert bx - x == pytest.approx(seat(1.5), abs=0.05)
    assert abs(by - y) < 0.05  # centered: it was an inch off
    assert len(sim.arena.piece_contacts) == 2  # both sides of the notch push it


def test_a_ball_beside_the_clamp_is_pushed_by_its_jaw():
    ball = {"type": "piece", "pos_in": [16, 5.0], "diameter_in": 3.0, "mass_kg": 0.1}
    sim = sim_on([ball], Pose(0, 0, 0))
    drive(sim)
    sim.run_for(1.5)
    x, _, _ = pose_in(sim)
    bx, _ = (m_to_in(v) for v in sim.arena.pieces.position[0])
    assert bx - x == pytest.approx(9 + 1.5, abs=0.1)  # ahead of the jaw's front edge


def test_a_shape_of_one_rectangle_moves_as_its_footprint():
    """The shape's code and the footprint's agree where they can: on a rectangle."""
    rect = load_robot(with_shape([{"type": "rect", "size_in": [15, 15]}]))
    footprint = load_robot(EXAMPLE_ROBOT)
    elements = [
        {"type": "obstacle", "shape": "rect", "pos_in": [24, 6], "size_in": [6, 6],
         "heading_deg": 30},
        {"type": "obstacle", "shape": "circle", "pos_in": [10, -30], "diameter_in": 8},
        {"type": "piece", "pos_in": [12, 1], "diameter_in": 5, "mass_kg": 0.2},
    ]  # fmt: skip
    ends = []
    for config in (footprint, rect):
        sim = sim_on(elements, Pose(-10, 0, 10), config)
        drive(sim, 0.6)
        sim.run_for(1.5)
        drive(sim, -0.3)
        sim.robot.group("right").set_velocity(0.5 * sim.robot.group("right").rated_speed)
        sim.run_for(1.5)
        ends.append((*pose_in(sim), *map(m_to_in, sim.arena.pieces.position[0])))
    assert ends[1] == pytest.approx(ends[0], abs=1e-6)
    assert ends[0][0] > -10 + 5  # it went somewhere


# --- where it can start, and how it's drawn --------------------------------------------------


@pytest.mark.parametrize(
    ("start", "blocked"),
    [
        ((0, 0, 0), ["barrier"]),
        ((0, 8.5, 0), []),  # 7 in half width + the barrier's 1.5: touching
        ((0, 8.49, 0), ["barrier"]),
        # the goal's too wide for the notch: it meets the jaws' inside corners, (9, +-2.5)
        ((-48 + 9 + math.sqrt(5**2 - 2.5**2) - 0.01, 48, 180), ["red goal"]),
        ((-48 + 9 + math.sqrt(5**2 - 2.5**2) + 0.01, 48, 180), []),
        ((63, 0, 0), []),  # the jaws against the wall
        ((-63, 0, 0), []),  # the bumper against the wall
        ((-63.01, 0, 0), ["the walls"]),
    ],
)
def test_where_a_shaped_robot_cant_start(start, blocked):
    assert start_blocked(CONFIG, load_field(PRACTICE), start) == blocked


def test_the_ui_draws_its_outline():
    scene = robot_scene(CONFIG)
    assert scene["footprint"] == [18.0, 14.0]
    [loop] = scene["outline"]
    assert [7.0, 0.0] in loop and [9.0, 2.5] in loop  # the notch
    assert min(x for x, _ in loop) == -9.0  # the bumper's back
    assert "outline" not in robot_scene(load_robot(EXAMPLE_ROBOT))
    from vexsim.ui.protocol import RobotScene

    assert RobotScene.model_validate(scene).outline[0][0] == tuple(loop[0])


def test_the_server_previews_a_shaped_robot():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    app = create_app(
        ROOT, token="t", port=8643, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as client:
        assert client.get("/api/info?token=t").status_code == 200
        robot = "examples/robots/shaped_6m.yaml"
        preview = client.post("/api/preview", json={"robot": robot}).json()
        assert len(preview["robot"]["outline"][0]) > 40  # the bumper's arc, every 3 degrees
        checked = client.post(
            "/api/config/check", json={"kind": "robot", "text": SHAPED.read_text()}
        )
        assert {"body.shape[0]", "body.shape[1]", "body.shape[2]"} <= set(checked.json()["places"])


def test_validate_config_summarizes_the_shape(capsys):
    assert main(["validate-config", str(SHAPED)]) == 0
    assert "shape 18.0 x 14.0 in (3 parts, 219 sq in)" in capsys.readouterr().out


def test_the_viewer_draws_the_shape(tmp_path):
    pytest.importorskip("pygame")
    from vexsim.viz.viewer import LiveSource, Viewer

    sim = Simulation(CONFIG, start=Pose(0, 0, 90), echo=None)
    snap = LiveSource(lambda: sim).snapshot()
    assert snap.front == pytest.approx(7) and len(snap.outline) == 1
    viewer = Viewer(LiveSource(lambda: sim), headless=True)
    viewer.draw(snap)
    viewer.save(str(tmp_path / "shape.png"))
    # the round bumper is drawn behind the robot (it faces +y): robot color at 8 in back
    pixel = viewer.screen.get_at(viewer._to_px(0, -8))
    assert pixel[:3] != viewer.screen.get_at(viewer._to_px(5, -8))[:3]  # vs bare field beside it
    np.testing.assert_array_less(0, (tmp_path / "shape.png").stat().st_size)

"""Phase 9: the robot's footprint against the field perimeter."""

import copy
import math

import numpy as np
import pytest

from tests.conftest import EXAMPLE_ROBOT, ROOT
from vexsim.algorithms.localization.base import Pose
from vexsim.bench.scenario import LoadedScenario, validate_scenario
from vexsim.bench.trial import run_trial
from vexsim.config import load_robot
from vexsim.config.field import FieldConfig
from vexsim.config.yaml_io import load_yaml_file
from vexsim.physics import BrakeMode
from vexsim.physics.field import FieldSpec, Walls
from vexsim.physics.params import resolve_params
from vexsim.physics.robot import Robot
from vexsim.runtime.simulation import Simulation
from vexsim.units import in_to_m, m_to_in

CONFIG = load_robot(EXAMPLE_ROBOT)  # 15 x 15 in footprint
HALF_FIELD = 72.0
HALF_ROBOT = 7.5


def robot_at(x, y, heading, overrides=None, config=CONFIG) -> Robot:
    params = resolve_params(overrides or {})
    return Robot(
        config,
        params=params,
        pose=(in_to_m(x), in_to_m(y), math.radians(heading)),
        walls=Walls.of(FieldConfig(), params.field),
    )


def drive(r: Robot, left=1.0, right=1.0) -> None:
    for name, f in (("left", left), ("right", right)):
        group = r.group(name)
        group.set_velocity(f * group.rated_speed)


def corner_extent_in(r: Robot) -> float:
    """How far the footprint reaches from the field center along x or y (inches)."""
    h = r.heading
    rot = np.array([[math.cos(h), math.sin(h)], [-math.sin(h), math.cos(h)]])
    return m_to_in(np.abs(r.cg_position + r.footprint_corners @ rot).max())


def run_watching(r: Robot, seconds: float) -> tuple[float, float]:
    """Run, returning the furthest reach (in) and the deepest contact (mm) along the way."""
    reach = depth = 0.0
    for _ in range(round(seconds / 0.001)):
        r.advance(0.001)
        reach = max(reach, corner_extent_in(r))
        depth = max([depth, *(c.depth_m * 1000 for c in r.wall_contacts)])
    return reach, depth


def test_head_on_stops_flush_against_the_wall():
    r = robot_at(55, 0, 0)
    drive(r)
    reach, depth = run_watching(r, 3.0)
    assert reach <= HALF_FIELD + 1e-6  # corrected every step: never ends a step inside
    assert 0 < depth < 2.0  # at most one step of travel (~1 mm) before the correction
    x, y, heading = r.pose
    assert m_to_in(x) == pytest.approx(HALF_FIELD - HALF_ROBOT, abs=0.05)
    assert abs(y) < 1e-6 and abs(heading) < 1e-6
    assert abs(r.body_velocity[0]) < 0.01  # stalled...
    assert (r.contacts.slip > 0.5).all()  # ...with the wheels spinning on the tiles
    assert r.wall_hits >= 1 and r.wall_contacts  # still pressed against the wall


@pytest.mark.parametrize("approach_deg", [5, 15, 30, -20])
def test_angled_approach_squares_up(approach_deg):
    # Driving into a wall at an angle rotates the robot flat against it (a wall reset).
    r = robot_at(45, 0, approach_deg)
    drive(r)
    r.run(3.0)
    assert math.degrees(r.pose[2]) == pytest.approx(0.0, abs=0.5)
    assert m_to_in(r.pose[0]) == pytest.approx(HALF_FIELD - HALF_ROBOT, abs=0.05)


def test_corner_contains_the_robot():
    r = robot_at(50, 50, 45)
    drive(r)
    reach, _ = run_watching(r, 3.0)
    assert reach <= HALF_FIELD + 1e-6
    x, y, _ = r.pose
    assert m_to_in(x) > 55 and m_to_in(y) > 55  # wedged into the corner


def test_every_wall_works():
    for heading, axis, sign in ((0, 0, 1), (90, 1, 1), (180, 0, -1), (270, 1, -1)):
        r = robot_at(0, 0, heading)
        drive(r)
        r.run(3.0)
        assert sign * m_to_in(r.pose[axis]) == pytest.approx(HALF_FIELD - HALF_ROBOT, abs=0.05)


def coast_into_wall(restitution: float, speed: float = 1.5) -> tuple[float, float]:
    """(speed just before, speed just after) the first wall contact, coasting head-on."""
    gap_in = 0.01  # close enough that rolling resistance can't stop a slow robot first
    r = robot_at(HALF_FIELD - HALF_ROBOT - gap_in, 0, 0, {"field.wall_restitution": restitution})
    r.qdot[0] = speed
    for group in r.groups:  # wheels rolling with the robot
        group.brake_mode = BrakeMode.COAST
        group.stop()
        r.qdot[group.index] = speed / (group.ratio * r.wheel_radius[group.wheels[0]])
    before = r.body_velocity[0]
    for _ in range(1000):
        before = r.body_velocity[0]
        r.advance(0.001)
        if r.wall_contacts:
            return before, r.body_velocity[0]
    raise AssertionError("never reached the wall")


def test_bounce_follows_restitution():
    before, after = coast_into_wall(0.2)
    assert after == pytest.approx(-0.2 * before, rel=0.02)
    before, after = coast_into_wall(0.0)
    assert abs(after) < 0.01 * before
    before, after = coast_into_wall(0.5, speed=0.04)  # slow touches don't bounce
    assert abs(after) < 1e-6


def test_wall_friction_resists_sliding_along_the_wall():
    def slid(friction):
        r = robot_at(HALF_FIELD - HALF_ROBOT, 0, 0, {"field.wall_friction": friction})
        r.external_force = np.array([60.0, 0.0])  # held against the wall...
        r.qdot[1] = 1.0  # ...while sliding along it (on the omni rollers)
        r.run(0.3)
        return r.pose[1]

    assert slid(0.6) < 0.8 * slid(0.0)


def test_field_spec_is_checked():
    with pytest.raises(ValueError, match="0..1"):
        FieldSpec(wall_restitution=-0.1)
    with pytest.raises(ValueError):
        FieldSpec(wall_friction=-1)


def test_simulation_uses_the_field_size():
    small = FieldConfig(size_in=(100.0, 120.0))
    sim = Simulation(CONFIG, field=small, start=Pose(30, 0, 0), echo=None)
    assert sim.robot.walls.half_size == pytest.approx((in_to_m(50), in_to_m(60)))
    for group in sim.robot.groups:
        group.set_velocity(group.rated_speed)
    sim.run_for(2.0)
    assert m_to_in(sim.robot.pose[0]) == pytest.approx(50 - HALF_ROBOT, abs=0.05)

    free = Simulation(CONFIG, walls=False, echo=None)
    assert free.robot.walls is None


def test_robots_off_the_walls_are_untouched():
    # Driving around the middle of the field is exactly the wall-free physics.
    def path(walls):
        r = robot_at(0, 0, 0) if walls else Robot(CONFIG)
        drive(r, 0.5, 0.25)  # a slow circle, 18 in radius
        r.run(2.0)
        assert corner_extent_in(r) < 50
        return r.pose

    assert path(True) == path(False)


def test_bench_counts_wall_contacts():
    data = copy.deepcopy(load_yaml_file(ROOT / "examples" / "scenarios" / "s_curve.yaml"))
    data.update(
        start={"x": 30, "y": -20, "heading": 0},
        task={"type": "follow", "waypoints": [[30, -20], [90, -20]], "tolerance_in": 2.0},
        disturbances=[],
        randomize={},
        time_limit_s=3,
    )
    loaded = LoadedScenario(
        validate_scenario(data).raise_for_errors(), ROOT / "examples" / "scenarios"
    )
    trial = run_trial(loaded, 0, "tracking wheels + IMU", loaded.controllers[0])
    assert trial.metrics.wall_contacts >= 1
    assert not trial.metrics.success  # the end of that path is beyond the wall


def test_traction_robot_against_the_wall():
    traction = load_robot(ROOT / "examples" / "robots" / "traction_6m.yaml")
    r = robot_at(50, 0, 10, config=traction)
    drive(r)
    r.run(3.0)
    assert m_to_in(r.pose[0]) == pytest.approx(HALF_FIELD - HALF_ROBOT, abs=0.05)
    assert math.degrees(r.pose[2]) == pytest.approx(0.0, abs=0.5)

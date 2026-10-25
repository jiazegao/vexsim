"""Phase 3: drivetrain and chassis behavior of a full-omni robot."""

import copy
import math

import numpy as np
import pytest

from tests.conftest import EXAMPLE_ROBOT
from vexsim.config import load_robot
from vexsim.config.yaml_io import load_yaml_file
from vexsim.physics import BrakeMode, World
from vexsim.physics.params import resolve_params
from vexsim.physics.robot import Robot
from vexsim.units import in_to_m, m_to_in

EXAMPLE = load_robot(EXAMPLE_ROBOT)
G = 9.81
WHEEL_R = in_to_m(3.25) / 2
HALF_TRACK = in_to_m(6.0)
KINEMATIC_TOP_SPEED_IN_S = 450 / 60 * math.pi * 3.25  # 76.6


def robot(overrides=None, **kw):
    params = resolve_params(overrides) if overrides else None
    return Robot(EXAMPLE, params=params, **kw)


def drive(r, left, right, mode="velocity"):
    """Command both sides as a fraction of rated speed (velocity) or in volts."""
    for name, value in (("left", left), ("right", right)):
        group = r.group(name)
        if mode == "velocity":
            group.set_velocity(value * group.rated_speed)
        else:
            group.set_voltage(value)


def kinematic_radius(left, right):
    return HALF_TRACK * (left + right) / (left - right)


def arc(r, left=1.0, right=0.4, seconds=3.0):
    drive(r, left, right)
    r.run(seconds)
    u, v, w = r.body_velocity
    return math.hypot(u, v) / abs(w), u, v, w


# --- construction ---------------------------------------------------------------


def test_robot_is_built_from_config():
    r = robot()
    assert sorted(r.motors) == [1, 2, 3, 4, 5, 6]
    assert [sign for _, sign, _ in r.group("right").motors] == [-1, -1, -1]
    assert r.group("left").ratio == pytest.approx(0.75)
    assert r.contact_matrix.shape == (18, 5)
    assert len(r.power.motors) == 6
    assert r.pose == (0.0, 0.0, 0.0)


def test_initial_pose_and_cg_offset():
    data = copy.deepcopy(load_yaml_file(EXAMPLE_ROBOT))
    data["body"]["cg_in"] = [2.0, 0.0, 3.5]
    r = Robot(load_robot(data), pose=(1.0, -0.5, math.pi / 2))
    assert r.pose == pytest.approx((1.0, -0.5, math.pi / 2))
    # The CG is 2 in ahead of the center; facing +y, that's 2 in further along +y.
    assert r.cg_position == pytest.approx([1.0, -0.5 + in_to_m(2.0)])


def test_unsupported_wheels_are_refused():
    data = copy.deepcopy(load_yaml_file(EXAMPLE_ROBOT))
    data["drivetrain"]["wheels"][1]["type"] = "traction"
    with pytest.raises(NotImplementedError):
        Robot(load_robot(data))


# --- normal loads -------------------------------------------------------------------


def test_static_loads_carry_the_weight():
    r = robot()
    assert r.contacts.normal.sum() == pytest.approx(6.5 * G)
    assert np.ptp(r.contacts.normal) == pytest.approx(0.0, abs=1e-9)


def test_cg_offset_shifts_static_load_forward():
    data = copy.deepcopy(load_yaml_file(EXAMPLE_ROBOT))
    data["body"]["cg_in"] = [2.0, 0.0, 3.5]
    r = Robot(load_robot(data))
    loads = r.contacts.normal
    front, rear = loads[[0, 3]].mean(), loads[[2, 5]].mean()
    assert front > rear
    assert (loads * r.wheel_pos[:, 0]).sum() == pytest.approx(0.0, abs=1e-9)  # no pitch moment


def test_weight_shifts_rearward_under_acceleration():
    r = robot()
    drive(r, 1.0, 1.0)
    r.run(0.05)
    loads = r.contacts.normal
    assert loads[[2, 5]].mean() > 1.2 * loads[[0, 3]].mean()  # rear vs. front
    ground_fx = r.contacts.traction_force.sum()
    pitch_moment = (loads * r.wheel_pos[:, 0]).sum()
    assert pitch_moment == pytest.approx(-r.cg_height * ground_fx, rel=0.05)


def test_drop_center_wheels_carry_more_load():
    data = copy.deepcopy(load_yaml_file(EXAMPLE_ROBOT))
    for i in (1, 4):  # middle wheels
        data["drivetrain"]["wheels"][i]["drop_in"] = 0.0625
    r = Robot(load_robot(data))
    loads = r.contacts.normal
    assert loads[[1, 4]].min() > 2 * loads[[0, 2, 3, 5]].max()
    assert loads.sum() == pytest.approx(6.5 * G)


# --- straight-line driving ---------------------------------------------------------


def test_velocity_mode_top_speed_matches_gearing():
    r = robot()
    drive(r, 1.0, 1.0)
    r.run(2.0)
    u, v, w = r.body_velocity
    assert m_to_in(u) == pytest.approx(KINEMATIC_TOP_SPEED_IN_S, rel=0.01)
    assert abs(v) < 1e-9 and abs(w) < 1e-9
    x, y, heading = r.pose
    assert abs(y) < 1e-9 and abs(heading) < 1e-9


def test_voltage_mode_top_speed_is_above_rated_but_below_no_load():
    r = robot()
    drive(r, 12.0, 12.0, mode="voltage")
    r.run(3.0)
    speed = m_to_in(r.body_velocity[0])
    assert KINEMATIC_TOP_SPEED_IN_S < speed < 1.134 * KINEMATIC_TOP_SPEED_IN_S


def launch_accel(r, seconds=0.04):
    drive(r, 1.0, 1.0)
    r.run(seconds)
    return r.body_velocity[0] / seconds


def test_launch_is_traction_limited():
    # Six blue motors could push ~10 m/s^2; omni wheels on tiles give out at mu*g first.
    r = robot()
    accel = launch_accel(r)
    mu = r.params.omni_wheel.longitudinal_mu
    assert 0.85 * mu * G < accel <= mu * G
    assert (r.contacts.slip > r.params.omni_wheel.slip_velocity_m_s).all()  # wheels spin


def test_lower_traction_lowers_launch_acceleration():
    slippery = launch_accel(robot({"wheel.omni.longitudinal_mu": 0.4}))
    assert slippery == pytest.approx(0.4 * G, rel=0.1)


def test_coast_rolls_further_than_brake():
    distances = {}
    for mode in (BrakeMode.COAST, BrakeMode.BRAKE):
        r = robot()
        drive(r, 1.0, 1.0)
        r.run(1.0)
        start = r.pose[0]
        for name in ("left", "right"):
            r.group(name).brake_mode = mode
            r.group(name).stop()
        r.run(3.0)
        assert abs(r.body_velocity[0]) < 0.01
        distances[mode] = r.pose[0] - start
    assert distances[BrakeMode.COAST] > 2 * distances[BrakeMode.BRAKE] > 0


# --- turning and drift ---------------------------------------------------------------


def test_turn_in_place_matches_kinematics():
    r = robot()
    drive(r, -1.0, 1.0)
    r.run(2.0)
    expected = r.group("left").rated_speed * 0.75 * WHEEL_R / HALF_TRACK
    assert r.body_velocity[2] == pytest.approx(expected, rel=0.01)
    assert math.hypot(*r.pose[:2]) < 1e-3  # omni rollers let it spin about its center


def test_slow_arc_follows_kinematics():
    radius, u, v, w = arc(robot(), 0.2, 0.1)
    assert radius == pytest.approx(kinematic_radius(0.2, 0.1), rel=0.05)
    assert abs(v) < 0.05 * u


def test_fast_arc_drifts_outward():
    radius, u, v, w = arc(robot())
    assert w < 0  # left side faster: turning right
    assert v > 0  # sliding outward, to the robot's left
    assert radius > 2 * kinematic_radius(1.0, 0.4)


def test_drift_grows_as_roller_friction_drops():
    radii = [arc(robot({"wheel.omni.lateral_mu": mu}))[0] for mu in (0.6, 0.3, 0.2, 0.1, 0.05)]
    assert radii == sorted(radii)
    assert radii[-1] > 2 * radii[0]


def test_sideways_push_breaks_away_at_roller_friction():
    def slide(force_fraction):
        r = robot()
        mu = r.params.omni_wheel.lateral_mu
        r.external_force = np.array([0.0, force_fraction * mu * 6.5 * G])
        r.run(1.0)
        return r.pose[1]

    assert slide(1.5) > 20 * slide(0.5) > 0  # creeps below breakaway, slides above it


def test_forward_push_is_much_easier_than_sideways():
    # 10 N is above the forward rolling losses (~6 N) but below roller breakaway (~13 N).
    def moved(direction):
        r = robot()
        r.external_force = 10.0 * np.array(direction)
        r.run(1.0)
        return math.hypot(*r.pose[:2])

    assert moved((1.0, 0.0)) > 3 * moved((0.0, 1.0))


# --- robustness ------------------------------------------------------------------------


def test_rest_is_stable():
    r = robot()
    r.run(5.0)
    assert np.abs(r.qdot).max() < 1e-9
    assert r.pose == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


def test_random_driving_never_creates_energy():
    r = robot()
    rng = np.random.default_rng(7)
    work = 0.0
    for _ in range(25):
        drive(r, *rng.uniform(-1, 1, size=2))
        for _ in range(200):
            r.advance(0.001)
            work += 0.001 * sum(m.torque * m.velocity for m in r.motors.values())
        assert np.isfinite(r.qdot).all()
    kinetic = 0.5 * r.qdot @ r.mass_matrix @ r.qdot
    assert kinetic <= work
    assert m_to_in(np.hypot(*r.qdot[:2])) < 2.5 * KINEMATIC_TOP_SPEED_IN_S


def test_driving_drains_battery_and_heats_motors():
    r = robot()
    for k in range(10):
        drive(r, (-1) ** k, (-1) ** k)
        r.run(1.0)
    assert r.power.battery.soc < 1.0
    assert all(m.temperature_c > 25.0 for m in r.motors.values())


def test_runs_inside_world_deterministically():
    def run():
        world = World(seed=3)
        r = world.add_system(robot())
        world.every(10, lambda w: drive(r, 1.0, 0.5 + 0.5 * math.sin(w.time)))
        world.run_for(2.0)
        return r.pose

    assert run() == run()


def test_xdrive_strafes_on_the_generic_wheel_model():
    corners = {"fl": (5, 5, -45), "fr": (5, -5, 45), "bl": (-5, 5, 45), "br": (-5, -5, -45)}
    data = {
        "body": {"mass_kg": 6.0, "footprint_in": [15, 15], "cg_in": [0, 0, 3]},
        "drivetrain": {
            "type": "xdrive",
            "wheels": [
                {"name": n, "pos_in": [x, y], "heading_deg": h, "type": "omni", "diameter_in": 3.25}
                for n, (x, y, h) in corners.items()
            ],
            "gearing": {
                n: {"motors": [i + 1], "cartridge": "blue", "ratio": "1:1", "wheels": [n]}
                for i, n in enumerate(corners)
            },
        },
    }
    r = Robot(load_robot(data))
    # Strafe left (+y): each wheel's surface speed is the projection of +y on its heading.
    for n, (_, _, h) in corners.items():
        group = r.group(n)
        group.set_velocity(math.sin(math.radians(h)) * group.rated_speed)
    r.run(2.0)
    u, v, w = r.body_velocity
    assert v > 1.0 and abs(u) < 0.02 * v and abs(w) < 0.01
    assert abs(r.pose[2]) < 0.01

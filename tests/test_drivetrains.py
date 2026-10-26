"""Phase 9: traction and mecanum wheels; X-drive, mecanum and H-drive layouts."""

import copy
import math

import numpy as np
import pytest

from tests.conftest import EXAMPLE_ROBOT, ROOT
from vexsim.algorithms.localization.base import Pose
from vexsim.config import load_robot
from vexsim.config.yaml_io import load_yaml_file
from vexsim.physics.kinematics import DriveKinematics
from vexsim.physics.robot import Robot
from vexsim.physics.wheel import friction_circle
from vexsim.runtime.simulation import ScriptedInput, Simulation
from vexsim.units import in_to_m, m_to_in, rpm_to_rad_s

ROBOTS = ROOT / "examples" / "robots"
OMNI = load_robot(EXAMPLE_ROBOT)
TRACTION = load_robot(ROBOTS / "traction_6m.yaml")
XDRIVE = load_robot(ROBOTS / "xdrive_4m.yaml")
MECANUM = load_robot(ROBOTS / "mecanum_4m.yaml")
HDRIVE = load_robot(ROBOTS / "hdrive_5m.yaml")
G = 9.81


def command(r: Robot, forward=0.0, left=0.0, ccw=0.0, mode="velocity") -> dict[str, float]:
    """Drive with stick-style fractions of the top speed in each direction."""
    fractions = DriveKinematics.from_config(r.config).fractions(forward, left, ccw)
    for name, f in fractions.items():
        group = r.group(name)
        if mode == "velocity":
            group.set_velocity(f * group.rated_speed)
        else:
            group.set_voltage(12.0 * f)
    return fractions


def settle(config, seconds=2.0, **cmd) -> tuple[float, float, float]:
    r = Robot(config)
    command(r, **cmd)
    r.run(seconds)
    u, v, w = r.body_velocity
    return m_to_in(u), m_to_in(v), w


def surface_speed_in_s(config, group: str) -> float:
    """Wheel surface speed at rated motor speed."""
    gear = config.drivetrain.gearing[group]
    wheel = config.drivetrain.wheel(gear.wheels[0])
    return gear.wheel_free_rpm / 60 * math.pi * wheel.diameter_in


# --- kinematics -------------------------------------------------------------------------------


def test_kinematics_rank_and_top_speeds():
    assert DriveKinematics.from_config(OMNI).rank == 2  # no strafing
    for config in (XDRIVE, MECANUM, HDRIVE):
        assert DriveKinematics.from_config(config).holonomic
    forward, sideways, _ = DriveKinematics.from_config(XDRIVE).top_speeds()
    assert m_to_in(forward) == pytest.approx(math.sqrt(2) * surface_speed_in_s(XDRIVE, "back_left"))
    assert sideways == pytest.approx(forward)
    assert DriveKinematics.from_config(OMNI).top_speeds()[1] == 0.0


def test_strafe_right_spins_the_usual_wheels():
    # The textbook pattern for both X-drive and mecanum: FL and BR forward, FR and BL back.
    for config in (XDRIVE, MECANUM):
        f = DriveKinematics.from_config(config).fractions(0.0, -1.0, 0.0)
        assert f == pytest.approx(
            {"front_left": 1, "front_right": -1, "back_left": -1, "back_right": 1}
        )


def test_combined_commands_keep_their_direction():
    f = DriveKinematics.from_config(XDRIVE).fractions(1.0, 1.0, 0.0)  # forward-left, diagonal
    assert f == pytest.approx({"front_left": 0, "front_right": 1, "back_left": 1, "back_right": 0})
    f = DriveKinematics.from_config(OMNI).fractions(1.0, 0.0, -1.0)  # like arcade(127, 127)
    assert f == pytest.approx({"left": 1.0, "right": 0.0})


# --- X-drive ----------------------------------------------------------------------------------


def test_xdrive_is_root_two_faster_than_its_wheels():
    u, v, w = settle(XDRIVE, forward=1.0)
    assert u == pytest.approx(math.sqrt(2) * surface_speed_in_s(XDRIVE, "front_left"), rel=0.01)
    assert abs(v) < 0.1 and abs(w) < 1e-3


def test_xdrive_strafes_turns_and_drives_diagonally():
    u, v, w = settle(XDRIVE, left=-1.0)
    assert v < -80 and abs(u) < 0.5 and abs(w) < 1e-3
    u, v, w = settle(XDRIVE, ccw=1.0)
    assert w > 5 and math.hypot(u, v) < 0.5
    u, v, w = settle(XDRIVE, forward=1.0, left=1.0)
    assert u == pytest.approx(v, rel=0.02) and u > 40 and abs(w) < 1e-3


# --- mecanum ----------------------------------------------------------------------------------


def test_mecanum_drives_forward_like_a_tank():
    u, v, w = settle(MECANUM, forward=1.0)
    assert u == pytest.approx(surface_speed_in_s(MECANUM, "front_left"), rel=0.01)
    assert abs(v) < 0.1 and abs(w) < 1e-3


def test_mecanum_strafes_slower_than_it_drives():
    forward, _, _ = settle(MECANUM, forward=1.0, mode="voltage")
    u, strafe, w = settle(MECANUM, left=-1.0, mode="voltage")
    assert strafe < 0 and abs(u) < 0.5 and abs(w) < 1e-3  # right, straight, no rotation
    # Kinematically as fast; the dragging rollers load the motors.
    assert 0.5 * forward < -strafe < 0.95 * forward


def test_mecanum_roller_angles_set_the_strafe_direction():
    data = copy.deepcopy(load_yaml_file(ROBOTS / "mecanum_4m.yaml"))
    for wheel in data["drivetrain"]["wheels"]:
        wheel["roller_angle_deg"] = -wheel["roller_angle_deg"]  # mirrored rollers
    r = Robot(load_robot(data))
    strafe_right = {"front_left": 1, "front_right": -1, "back_left": -1, "back_right": 1}
    for name, fraction in strafe_right.items():
        group = r.group(name)
        group.set_velocity(fraction * group.rated_speed)
    r.run(1.0)
    assert m_to_in(r.body_velocity[1]) > 40  # same spins, now strafing left


# --- H-drive ----------------------------------------------------------------------------------


def test_hdrive_strafes_with_its_center_wheel():
    r = Robot(HDRIVE)
    strafe = r.group("strafe")
    strafe.set_voltage(12.0)
    r.run(2.0)
    u, v, w = r.body_velocity
    assert m_to_in(v) > 30 and abs(u) < 0.01 and abs(w) < 0.01
    # One motor against four sets of rollers: slower than driving forward.
    forward, _, _ = settle(HDRIVE, forward=1.0, mode="voltage")
    assert m_to_in(v) < 0.7 * forward


def test_hdrive_center_wheel_needs_load():
    data = copy.deepcopy(load_yaml_file(ROBOTS / "hdrive_5m.yaml"))
    data["drivetrain"]["wheels"][4]["drop_in"] = 0.0  # level with the corner wheels

    def strafe_speed(config):
        r = Robot(config)
        r.group("strafe").set_voltage(12.0)
        r.run(2.0)
        return r.body_velocity[1]

    assert strafe_speed(load_robot(data)) < 0.5 * strafe_speed(HDRIVE)


# --- traction wheels --------------------------------------------------------------------------


def arc_radius(config, left=1.0, right=0.4, seconds=3.0) -> tuple[float, float]:
    r = Robot(config)
    for name, f in (("left", left), ("right", right)):
        group = r.group(name)
        group.set_velocity(f * group.rated_speed)
    r.run(seconds)
    u, v, w = r.body_velocity
    return math.hypot(u, v) / abs(w), v


def test_traction_center_drifts_less_in_fast_arcs():
    kinematic = in_to_m(6.0) * 1.4 / 0.6
    omni_radius, omni_slide = arc_radius(OMNI)
    traction_radius, traction_slide = arc_radius(TRACTION)
    assert traction_radius < 0.4 * omni_radius
    assert traction_radius < 1.3 * kinematic
    assert 0 < traction_slide < 0.4 * omni_slide


def test_traction_center_turns_in_place_freely():
    # The traction wheels sit on the turning center line, so nothing scrubs.
    r = Robot(TRACTION)
    for name, f in (("left", -1.0), ("right", 1.0)):
        r.group(name).set_velocity(f * r.group(name).rated_speed)
    r.run(2.0)
    expected = r.group("left").rated_speed * 0.75 * in_to_m(3.25) / 2 / in_to_m(6.0)
    assert r.body_velocity[2] == pytest.approx(expected, rel=0.01)


def test_traction_wheels_resist_sideways_pushes():
    def slide(config):
        r = Robot(config)
        r.external_force = np.array([0.0, 20.0])  # 1.5x the omni robot's roller breakaway
        r.run(1.0)
        return r.pose[1]

    assert slide(OMNI) > 0.2
    assert slide(TRACTION) < 0.1 * slide(OMNI)  # creeps (smoothed friction), doesn't break away


def all_traction_corners():
    data = copy.deepcopy(load_yaml_file(EXAMPLE_ROBOT))
    data["drivetrain"]["wheels"] = [
        w for w in data["drivetrain"]["wheels"] if w["name"] not in ("lm", "rm")
    ]
    data["drivetrain"]["gearing"]["left"]["wheels"] = ["lf", "lb"]
    data["drivetrain"]["gearing"]["right"]["wheels"] = ["rf", "rb"]
    omni = load_robot(data)
    for w in data["drivetrain"]["wheels"]:
        w["type"] = "traction"
    return omni, load_robot(data)


def test_traction_corners_scrub_when_turning():
    def turn(config):
        r = Robot(config)
        for name, f in (("left", -12.0), ("right", 12.0)):
            r.group(name).set_voltage(f)
        r.run(2.0)
        current = sum(abs(m.current) for m in r.motors.values())
        return r.body_velocity[2], current

    omni_rate, omni_current = turn(all_traction_corners()[0])
    traction_rate, traction_current = turn(all_traction_corners()[1])
    assert traction_rate < 0.8 * omni_rate  # corner wheels must slide sideways to turn
    assert traction_current > 1.5 * omni_current


def test_friction_circle():
    limit, scale = 10.0, 0.03
    # Pure slip: same as one tanh channel.
    fs, ff, *_ = friction_circle(0.06, 0.0, limit, scale)
    assert fs == pytest.approx(limit * math.tanh(2.0)) and ff == 0.0
    # Never more than the limit in total, in any direction.
    for slip, free in ((1.0, 1.0), (-0.3, 2.0), (0.01, -0.02)):
        fs, ff, *_ = friction_circle(slip, free, limit, scale)
        assert math.hypot(fs, ff) <= limit
    # A spinning wheel loses its sideways grip: the same sideways velocity meets far less
    # resistance while the wheel slips hard.
    _, gripping, *_ = friction_circle(0.0, 0.02, limit, scale)
    _, spinning, *_ = friction_circle(1.0, 0.02, limit, scale)
    assert spinning < 0.1 * gripping


@pytest.mark.parametrize("c", [(0.0, 0.0), (0.05, -0.01), (-0.4, 0.3), (0.001, 0.5)])
def test_friction_circle_jacobian_is_exact_and_dissipative(c):
    limit, scale, h = 7.0, 0.03, 1e-7
    _, _, d_ss, d_ff, d_sf = friction_circle(*c, limit, scale)
    jac = np.array([[d_ss, d_sf], [d_sf, d_ff]])
    numeric = np.zeros((2, 2))
    for k in range(2):
        step = np.zeros(2)
        step[k] = h
        hi = friction_circle(*(np.array(c) + step), limit, scale)[:2]
        lo = friction_circle(*(np.array(c) - step), limit, scale)[:2]
        numeric[:, k] = (np.array(hi) - np.array(lo)) / (2 * h)
    assert jac == pytest.approx(numeric, rel=1e-4, abs=1e-3)
    assert np.linalg.eigvalsh(jac).min() > 0


# --- every drivetrain ----------------------------------------------------------------------


@pytest.mark.parametrize("config", [TRACTION, XDRIVE, MECANUM, HDRIVE], ids=lambda c: c.name)
def test_random_driving_never_creates_energy(config):
    r = Robot(config)
    rng = np.random.default_rng(11)
    work = 0.0
    for _ in range(15):
        for group in r.groups:
            group.set_voltage(rng.uniform(-12, 12))
        for _ in range(200):
            r.advance(0.001)
            work += 0.001 * sum(m.torque * m.velocity for m in r.motors.values())
        assert np.isfinite(r.qdot).all()
    assert 0.5 * r.qdot @ r.mass_matrix @ r.qdot <= work


@pytest.mark.parametrize("config", [TRACTION, XDRIVE, MECANUM, HDRIVE], ids=lambda c: c.name)
def test_rest_is_stable(config):
    r = Robot(config)
    r.run(3.0)
    assert np.abs(r.qdot).max() < 1e-9


def test_default_driver_control_strafes_holonomic_robots():
    sticks = ScriptedInput([(0.0, {"LEFT_X": 127}, set())])  # left stick to the right
    sim = Simulation(MECANUM, input_source=sticks, noise="ideal", start=Pose(0, 0, 90), echo=None)
    assert sim.bot.chassis is None and sim.bot.drive.holonomic
    sim.start("driver")
    sim.run_for(3.0)  # calibration, then strafing
    true = Pose.from_si(sim.robot.pose)
    assert true.x > 20 and abs(true.y) < 1 and abs(true.heading - 90) < 1  # facing +y: right is +x


def test_hdrive_keeps_chassis_motions():
    sim = Simulation(HDRIVE, noise="ideal", echo=None)
    assert sim.bot.chassis is not None and sim.bot.drive.holonomic


def test_rated_speed_matches_cartridge():
    assert DriveKinematics.from_config(XDRIVE).rated_rad_s == pytest.approx([rpm_to_rad_s(600)] * 4)

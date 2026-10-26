"""Phase 5: control algorithms, alone and driving the simulated robot."""

import math
import types

import numpy as np
import pytest

from tests.conftest import EXAMPLE_ROBOT
from vexsim.algorithms.control.base import (
    ChassisGeometry,
    DriveCommand,
    scale_to_limit,
    wrap_degrees,
)
from vexsim.algorithms.control.paths import generate_trajectory, spline
from vexsim.algorithms.control.pid import PID, ExitCondition
from vexsim.algorithms.control.profiles import SCurveProfile, TrapezoidProfile
from vexsim.algorithms.localization.base import Pose
from vexsim.config import load_robot
from vexsim.runtime.simulation import ORIGIN, Simulation

CONFIG = load_robot(EXAMPLE_ROBOT)
GEOMETRY = ChassisGeometry.from_config(CONFIG)


# --- building blocks -------------------------------------------------------------------------


def test_geometry_from_config():
    assert GEOMETRY.track_width_in == pytest.approx(12.0)
    assert GEOMETRY.wheel_diameter_in == pytest.approx(3.25)
    assert GEOMETRY.max_speed_in_s == pytest.approx(450 / 60 * math.pi * 3.25)
    assert GEOMETRY.wheel_speeds(10.0, 1.0) == pytest.approx((4.0, 16.0))


def test_helpers():
    assert wrap_degrees(190) == pytest.approx(-170)
    assert wrap_degrees(-180) == pytest.approx(180)
    assert scale_to_limit(24, 12, 12) == pytest.approx((12, 6))
    assert scale_to_limit(3, -4, 12) == (3, -4)
    assert DriveCommand.stop() == DriveCommand(0.0, 0.0)


def test_pid_terms_and_integral_zone():
    pid = PID(kp=2.0, ki=1.0, kd=0.5, integral_zone=5.0)
    assert pid.update(10.0, 0.1) == pytest.approx(20.0)  # outside the zone: no integral
    assert pid.update(4.0, 0.1) == pytest.approx(8.0 + 0.4 + 0.5 * (4.0 - 10.0) / 0.1)
    pid.update(-1.0, 0.1)  # sign change resets the integral
    assert pid._integral == 0.0


def test_exit_condition_needs_a_hold():
    exit_ = ExitCondition(tolerance=1.0, hold_s=0.05)
    assert not any(exit_.update(0.5, 0.01) for _ in range(4))
    assert exit_.update(0.5, 0.01)
    assert not exit_.update(2.0, 0.01)


@pytest.mark.parametrize("distance", [48.0, 4.0, -30.0])
def test_trapezoid_profile(distance):
    prof = TrapezoidProfile(distance, max_velocity=60.0, max_accel=120.0)
    t = np.linspace(0, prof.duration, 2001)
    states = [prof.sample(x) for x in t]
    v = np.array([s.velocity for s in states])
    assert prof.sample(prof.duration).position == pytest.approx(distance)
    assert np.abs(v).max() <= 60.0 + 1e-9
    assert np.abs(np.diff(v) / np.diff(t)).max() <= 120.0 * 1.001
    # Velocity integrates to position.
    assert np.trapezoid(v, t) == pytest.approx(distance, rel=1e-3)


@pytest.mark.parametrize("distance", [48.0, 6.0, -24.0])
def test_scurve_profile(distance):
    prof = SCurveProfile(distance, max_velocity=60.0, max_accel=120.0, max_jerk=1200.0)
    t = np.arange(0, prof.duration, 0.001)
    acc = np.array([prof.sample(x).acceleration for x in t])
    vel = np.array([prof.sample(x).velocity for x in t])
    assert prof.sample(prof.duration).position == pytest.approx(distance, rel=1e-3)
    assert np.abs(vel).max() <= 60.0 * 1.001
    assert np.abs(acc).max() <= 120.0 * 1.01
    assert np.abs(np.diff(acc) / 0.001).max() <= 1200.0 * 1.05  # jerk-limited
    trap = TrapezoidProfile(distance, 60.0, 120.0)
    assert prof.duration > trap.duration  # smoothness costs a little time


def test_spline_passes_through_waypoints_and_is_smooth():
    waypoints = [(0, 0), (30, 0), (40, 30), (10, 40)]
    path = spline(waypoints)
    for w in waypoints:
        assert np.hypot(*(path - w).T).min() < 1e-6
    turning = np.abs(np.diff(np.unwrap(np.arctan2(*np.diff(path, axis=0)[:, ::-1].T))))
    assert np.degrees(turning).max() < 15  # no corners


def test_trajectory_respects_limits():
    traj = generate_trajectory([(0, 0), (40, 0), (40, 40)], GEOMETRY, max_lateral_accel_in_s2=40)
    x, y, h, v, w = traj.states.T
    assert (x[-1], y[-1]) == pytest.approx((40, 40), abs=0.1)
    assert v[0] == 0 and v[-1] == pytest.approx(0)
    assert v.max() <= 0.7 * GEOMETRY.max_speed_in_s + 1e-6
    assert np.abs(v * w).max() <= 40 * 1.05
    outer = np.abs(v) + np.abs(w) * GEOMETRY.track_width_in / 2
    assert outer.max() <= GEOMETRY.max_speed_in_s * 1.01


# --- motions on the simulated robot -------------------------------------------------------------


def run_motion(make, noise="ideal", start=ORIGIN, timeout_s=10.0):
    result = {}

    def autonomous(bot):
        t0 = bot.millis()
        yield from make(bot.chassis)
        result["ms"] = bot.millis() - t0

    sim = Simulation(
        CONFIG,
        program=types.SimpleNamespace(autonomous=autonomous),
        seed=0,
        noise=noise,
        start=start,
        echo=None,
    )
    sim.start("autonomous")
    assert sim.run_until_finished(timeout_s + 3)
    return Pose.from_si(sim.robot.pose), result["ms"]


@pytest.mark.parametrize("target", [90, -170, 30])
def test_turn_to_heading(target):
    pose, ms = run_motion(lambda c: c.turn_to_heading(target))
    assert abs(wrap_degrees(pose.heading - target)) < 1.5
    assert ms < 1000
    assert math.hypot(pose.x, pose.y) < 0.5  # turns in place


@pytest.mark.parametrize("target", [(30, 0), (0, 30), (-20, -20)])
def test_move_to_point(target):
    pose, ms = run_motion(lambda c: c.move_to_point(*target))
    assert math.hypot(pose.x - target[0], pose.y - target[1]) < 1.5
    assert ms < 2500


def test_move_to_point_backwards():
    pose, _ = run_motion(lambda c: c.move_to_point(-30, 0, forwards=False))
    assert pose.x == pytest.approx(-30, abs=1.0) and abs(wrap_degrees(pose.heading)) < 2


@pytest.mark.parametrize("target", [(30, 30, 90), (0, 40, 180), (36, -12, -45)])
def test_move_to_pose(target):
    pose, ms = run_motion(lambda c: c.move_to_pose(*target))
    assert math.hypot(pose.x - target[0], pose.y - target[1]) < 2.0
    assert abs(wrap_degrees(pose.heading - target[2])) < 3.0
    assert ms < 4000


@pytest.mark.parametrize("profile", ["trapezoid", "scurve"])
def test_profiled_drive(profile):
    pose, ms = run_motion(lambda c: c.drive(24, profile=profile))
    assert pose.x == pytest.approx(24, abs=0.4) and abs(pose.y) < 0.2
    assert ms < 2000


@pytest.mark.parametrize("method", ["pure_pursuit", "ramsete"])
def test_follow_path(method):
    waypoints = [(0, 0), (30, 0), (40, 30), (10, 40)]
    pose, ms = run_motion(lambda c: c.follow(waypoints, method=method))
    assert math.hypot(pose.x - 10, pose.y - 40) < 2.0
    assert ms < 6000


def test_motions_work_with_realistic_sensor_noise():
    pose, _ = run_motion(lambda c: c.move_to_pose(30, 30, 90), noise="default")
    assert math.hypot(pose.x - 30, pose.y - 30) < 3.0


def test_motion_timeout_stops_the_robot():
    pose, ms = run_motion(lambda c: c.move_to_point(200, 0, timeout_ms=500))
    assert ms == pytest.approx(500, abs=20)
    assert pose.x < 60

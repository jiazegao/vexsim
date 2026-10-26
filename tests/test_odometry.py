"""Phase 4: odometry baselines, on synthetic readings and on the full simulation."""

import copy
import math

import numpy as np
import pytest

from tests.conftest import EXAMPLE_ROBOT
from vexsim.algorithms.localization import (
    ArcOdometry,
    MotorTracker,
    Pose,
    RotationTracker,
    baseline_localizers,
    run_odometry,
)
from vexsim.cli import main
from vexsim.config import load_robot
from vexsim.config.yaml_io import load_yaml_file
from vexsim.devices.frame import ImuReading, MotorReading, RotationReading, SensorFrame

ROBOT_DATA = load_yaml_file(EXAMPLE_ROBOT)
EXAMPLE = load_robot(ROBOT_DATA)
D = 2.0  # tracking wheel diameter, in

LEFT, RIGHT, BACK, IMU = 1, 2, 3, 10
VERTICALS = [RotationTracker(LEFT, D, 4.0), RotationTracker(RIGHT, D, -4.0)]
HORIZONTAL = [RotationTracker(BACK, D, -3.0)]


def three_wheel_robot():
    """The example robot with a second vertical tracking wheel and no IMU."""
    data = copy.deepcopy(ROBOT_DATA)
    data["sensors"] = [s for s in data["sensors"] if s["type"] != "imu"] + [
        {
            "type": "rotation",
            "port": 14,
            "tracking_wheel": {"pos_in": [0, 1.5], "heading_deg": 0, "diameter_in": 2.0},
        }
    ]
    return load_robot(data)


def wheel_frame(travel: dict[int, float], heading_ccw_deg: float = 0.0) -> SensorFrame:
    """A frame where each rotation port has rolled ``travel`` inches."""
    rotation = {
        port: RotationReading(round(inches / (math.pi * D) * 36000), 0.0)
        for port, inches in travel.items()
    }
    imu = {IMU: ImuReading(rotation_deg=-heading_ccw_deg, gyro_z_deg_s=0.0)}
    return SensorFrame(time=0.0, rotation=rotation, imu=imu)


def arc_frames(radius: float, total_deg: float, steps: int):
    """Readings along a counter-clockwise arc of the given radius (in) about a point to the left."""
    for k in range(steps + 1):
        theta = math.radians(total_deg) * k / steps
        travel = {
            LEFT: (radius - 4.0) * theta,  # vertical wheel at y=+4 rolls (R - y) * theta
            RIGHT: (radius + 4.0) * theta,
            BACK: -3.0 * theta,  # horizontal wheel at x=-3 rolls x * theta
        }
        yield wheel_frame(travel, math.degrees(theta)), theta


def expected_on_arc(radius: float, theta: float) -> Pose:
    return Pose(radius * math.sin(theta), radius * (1 - math.cos(theta)), math.degrees(theta))


# --- arc math on synthetic readings -------------------------------------------------------------


@pytest.mark.parametrize("steps", [1, 7, 400])
@pytest.mark.parametrize("use_imu", [False, True])
def test_arc_is_exact_for_constant_curvature(steps, use_imu):
    odom = ArcOdometry("test", VERTICALS, HORIZONTAL, imu_port=IMU if use_imu else None)
    frames = list(arc_frames(30.0, 120.0, steps))
    odom.reset(Pose(0, 0, 0), frames[0][0])
    for frame, _ in frames[1:]:
        pose = odom.update(frame)
    want = expected_on_arc(30.0, frames[-1][1])
    # Readings are quantized to 0.01 degree of wheel rotation.
    assert pose.distance_to(want) < 0.01
    assert abs(pose.heading_error(want)) < 0.02


def test_turn_in_place_and_straight_line():
    odom = ArcOdometry("test", VERTICALS, HORIZONTAL)
    odom.reset(Pose(10, -5, 90), wheel_frame({LEFT: 0, RIGHT: 0, BACK: 0}))
    spin = math.radians(90)
    pose = odom.update(wheel_frame({LEFT: -4 * spin, RIGHT: 4 * spin, BACK: -3 * spin}))
    assert pose == pytest.approx(Pose(10, -5, 180), abs=0.01)
    pose = odom.update(wheel_frame({LEFT: -4 * spin + 12, RIGHT: 4 * spin + 12, BACK: -3 * spin}))
    assert (pose.x, pose.y) == pytest.approx((-2, -5), abs=0.01)  # 12 in along heading 180


def test_reversed_and_motor_trackers():
    frame = SensorFrame(
        time=0.0,
        rotation={LEFT: RotationReading(-36000, 0.0)},
        motors={
            p: MotorReading(sign * 360.0, 0, 0, 0, 25.0, 0, 0, False, False)
            for p, sign in ((1, 1), (2, 1), (4, -1))
        },
    )
    assert RotationTracker(LEFT, D, 0, reversed=True).distance_in(frame) == pytest.approx(
        math.pi * D
    )
    side = MotorTracker(ports=(1, 2), wheel_diameter_in=3.25, ratio=0.75, offset_in=6)
    assert side.distance_in(frame) == pytest.approx(0.75 * math.pi * 3.25)
    assert MotorTracker((-4,), 3.25, 0.75, -6).distance_in(frame) == pytest.approx(
        0.75 * math.pi * 3.25
    )


def test_missing_readings_hold_the_estimate():
    odom = ArcOdometry("test", VERTICALS, imu_port=IMU)
    odom.reset(Pose(1, 2, 3), wheel_frame({LEFT: 0, RIGHT: 0}))
    calibrating = SensorFrame(
        time=0.0, rotation=wheel_frame({LEFT: 5, RIGHT: 5}).rotation, imu={IMU: None}
    )
    assert odom.update(calibrating) == Pose(1, 2, 3)
    with pytest.raises(ValueError, match="not ready"):
        odom.reset(Pose(0, 0, 0), calibrating)


def test_construction_checks():
    with pytest.raises(ValueError):
        ArcOdometry("none", [])
    with pytest.raises(ValueError):
        ArcOdometry("one wheel, no imu", VERTICALS[:1])
    with pytest.raises(ValueError):
        ArcOdometry("same offsets", [RotationTracker(1, D, 2), RotationTracker(2, D, 2)])


# --- baselines built from robot configs ----


def test_baselines_for_the_example_robot():
    names = [loc.name for loc in baseline_localizers(EXAMPLE)]
    assert names == ["drive encoders", "drive encoders + IMU", "tracking wheels + IMU"]
    tracking = baseline_localizers(EXAMPLE)[2]
    assert [(t.port, t.offset_in) for t in tracking.vertical] == [(11, -1.5)]
    assert [(t.port, t.offset_in) for t in tracking.horizontal] == [(12, -3.0)]
    drive = baseline_localizers(EXAMPLE)[0]
    assert drive.vertical[1].ports == (-4, -5, -6) and drive.vertical[1].offset_in == -6.0


def test_backwards_mounted_tracking_wheel_is_folded_into_reversed():
    data = copy.deepcopy(ROBOT_DATA)
    data["sensors"][1]["tracking_wheel"]["heading_deg"] = 180
    vertical = baseline_localizers(load_robot(data))[2].vertical[0]
    assert vertical.reversed


def test_three_wheel_robot_gets_imu_free_odometry():
    names = [loc.name for loc in baseline_localizers(three_wheel_robot())]
    assert names == ["drive encoders", "tracking wheels (no IMU)"]


# --- full simulation ----


def final_errors(config, script, noise, seed=0):
    run = run_odometry(config, script, seed=seed, noise=noise)
    return {name: run.final_error(name) for name in run.estimates}


def test_ideal_tracking_wheels_are_nearly_exact():
    errors = final_errors(EXAMPLE, "aggressive", "ideal")
    position, heading = errors["tracking wheels + IMU"]
    assert position < 0.1 and heading < 0.01
    position, heading = final_errors(three_wheel_robot(), "aggressive", "ideal")[
        "tracking wheels (no IMU)"
    ]
    assert position < 0.5 and heading < 0.2


def test_drive_encoders_lose_the_robot_when_it_slides():
    for seed in range(2):
        errors = final_errors(EXAMPLE, "aggressive", "default", seed)
        assert errors["drive encoders"][0] > 30
        assert errors["drive encoders + IMU"][0] > 30  # heading isn't the problem: the slide is
        assert errors["tracking wheels + IMU"][0] < 5


def test_drive_encoders_are_fine_when_driving_gently():
    errors = final_errors(EXAMPLE, "gentle", "default")
    assert errors["drive encoders + IMU"][0] < 8
    assert errors["tracking wheels + IMU"][0] < 2


def test_noisier_sensors_mean_larger_errors():
    tracking = [
        final_errors(EXAMPLE, "aggressive", noise, seed=1)["tracking wheels + IMU"][0]
        for noise in ("ideal", "default", "harsh")
    ]
    assert tracking == sorted(tracking)


def test_runs_are_reproducible():
    a = run_odometry(EXAMPLE, "gentle", seed=3, noise="harsh")
    b = run_odometry(EXAMPLE, "gentle", seed=3, noise="harsh")
    for name in a.estimates:
        np.testing.assert_array_equal(a.estimates[name], b.estimates[name])


def test_odometry_command(capsys):
    assert main(["odometry", str(EXAMPLE_ROBOT), "--script", "gentle", "--noise", "ideal"]) == 0
    out = capsys.readouterr().out
    assert "tracking wheels + IMU" in out and "final error" in out

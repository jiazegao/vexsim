"""Build the baseline localizers a robot config supports."""

from __future__ import annotations

import math

from vexsim.algorithms.localization.gps import GpsCorrected
from vexsim.algorithms.localization.odometry import ArcOdometry, MotorTracker, RotationTracker
from vexsim.config.robot import RobotConfig


def drive_trackers(config: RobotConfig) -> list[MotorTracker]:
    """Left and right drive sides as motor-encoder trackers (differential drives only)."""
    dt = config.drivetrain
    if dt.type != "differential":
        return []
    trackers = []
    for side in ("left", "right"):
        group = dt.gearing[side]
        wheels = [dt.wheel(name) for name in group.wheels]
        trackers.append(
            MotorTracker(
                ports=tuple(group.motors),
                wheel_diameter_in=sum(w.diameter_in for w in wheels) / len(wheels),
                ratio=group.speed_ratio,
                offset_in=sum(w.pos_in[1] for w in wheels) / len(wheels),
            )
        )
    return trackers


def tracking_wheels(config: RobotConfig) -> tuple[list[RotationTracker], list[RotationTracker]]:
    """(vertical, horizontal) rotation-sensor tracking wheels from the config.

    Wheels at 0/180 degrees are vertical, 90/270 horizontal; 180 and 270 count
    backwards, which is folded into the ``reversed`` flag. Others are skipped.
    """
    vertical, horizontal = [], []
    for s in config.sensors:
        if s.type != "rotation" or s.tracking_wheel is None:
            continue
        tw = s.tracking_wheel
        quarter = round(tw.heading_deg / 90.0) % 4
        if not math.isclose(tw.heading_deg / 90.0, round(tw.heading_deg / 90.0), abs_tol=1e-6):
            continue
        backwards = quarter in (2, 3)
        is_vertical = quarter in (0, 2)
        tracker = RotationTracker(
            port=s.port,
            diameter_in=tw.diameter_in,
            offset_in=tw.pos_in[1] if is_vertical else tw.pos_in[0],
            reversed=s.reversed != backwards,
        )
        (vertical if is_vertical else horizontal).append(tracker)
    return vertical, horizontal


def baseline_localizers(config: RobotConfig) -> list[ArcOdometry | GpsCorrected]:
    """Every baseline the robot's sensors allow, from simplest to best equipped."""
    imu = next((s.port for s in config.sensors if s.type == "imu"), None)
    out: list[ArcOdometry] = []
    drive = drive_trackers(config)
    if drive:
        out.append(ArcOdometry("drive encoders", drive))
        if imu is not None:
            out.append(ArcOdometry("drive encoders + IMU", drive, imu_port=imu))
    vertical, horizontal = tracking_wheels(config)
    if vertical and imu is not None:
        out.append(ArcOdometry("tracking wheels + IMU", vertical, horizontal, imu_port=imu))
    if len(vertical) >= 2 and vertical[0].offset_in != vertical[1].offset_in:
        out.append(ArcOdometry("tracking wheels (no IMU)", vertical, horizontal))
    gps = next((s for s in config.sensors if s.type == "gps"), None)
    if gps is not None and vertical and imu is not None:
        odometry = ArcOdometry("tracking wheels + IMU", vertical, horizontal, imu_port=imu)
        out.append(GpsCorrected("tracking wheels + IMU + GPS", odometry, gps.port, gps.pos_in))
    return out

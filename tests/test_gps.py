"""Phase 10: the V5 GPS sensor, its PROS API in Python and C++, and GPS-corrected odometry."""

import copy
import dataclasses
import math

import numpy as np
import pytest

from tests.conftest import EXAMPLE_ROBOT
from vexsim.algorithms.localization.base import Pose
from vexsim.algorithms.localization.runner import run_odometry
from vexsim.api.devices import PROS_ERR_F
from vexsim.bridge.program import CppProgram
from vexsim.calibration.log import columns_for
from vexsim.config import load_robot, validate_robot
from vexsim.config.yaml_io import load_yaml_file
from vexsim.physics import BrakeMode
from vexsim.runtime.simulation import Simulation

BASE = load_yaml_file(EXAMPLE_ROBOT)
METER_IN = 39.37007874


def robot_with_gps(noise="default", pos=(-6.0, 0.0), yaw=180.0):
    data = copy.deepcopy(BASE)
    data["sensors"].append(
        {"type": "gps", "port": 15, "pos_in": list(pos), "mount_yaw_deg": yaw, "noise": noise}
    )
    return load_robot(data)


def sim_at(pose: Pose, **kw) -> Simulation:
    return Simulation(robot_with_gps(**kw), start=pose, echo=None)


def test_config_and_log_columns():
    cfg = robot_with_gps()
    assert cfg.sensors[-1].type == "gps"
    assert columns_for(cfg)[-4:] == ["gps15_x_m", "gps15_y_m", "gps15_heading_deg", "gps15_error_m"]
    data = copy.deepcopy(BASE)
    data["sensors"].append({"type": "gps", "port": 15, "pos_in": [20, 0]})
    assert "sensors[4].pos_in" in {i.location for i in validate_robot(data).errors}


def test_reading_is_the_sensor_in_gps_units():
    sim = sim_at(Pose(-24, 12, 30), noise="ideal")
    sim.run_for(0.1)
    r = sim.sensors.devices[15].value
    # The sensor is 6 in behind the center; the robot faces 30 deg CCW from +x.
    h = math.radians(30)
    assert r.x_m * METER_IN == pytest.approx(-24 - 6 * math.cos(h), abs=1e-6)
    assert r.y_m * METER_IN == pytest.approx(12 - 6 * math.sin(h), abs=1e-6)
    assert r.heading_deg == pytest.approx((90 - (30 + 180)) % 360)  # camera, clockwise from +y
    assert r.fix and r.error_m == 0.0


def test_offset_gives_the_robot_center():
    sim = sim_at(Pose(-24, 12, 30), noise="ideal")
    gps = sim.bot.Gps(15)
    assert gps.get_position() == (PROS_ERR_F, PROS_ERR_F)  # before its first sample
    sim.run_for(0.1)
    gps.set_offset(0.0, 6 / METER_IN)  # 6 in from the center, along the backward camera
    x, y = gps.get_position()
    assert (x * METER_IN, y * METER_IN) == pytest.approx((-24, 12), abs=1e-6)
    assert sim.bot.Gps(15).get_offset() == gps.get_offset()  # the sensor holds the offset
    assert gps.get_yaw() == pytest.approx(-120.0)
    assert gps.get_position_and_orientation()[2:4] == (0.0, 0.0)


def test_noise_grows_with_distance_to_the_strip():
    def spread(pose):
        sim = sim_at(pose)
        xs = []
        for _ in range(100):
            sim.run_for(0.02)
            xs.append(sim.sensors.devices[15].value.x_m)
        return np.std(xs), sim.sensors.devices[15].value.error_m

    near, near_error = spread(Pose(0, 0, 0))  # camera faces backward: 1.7 m to the -x wall
    far, far_error = spread(Pose(60, 0, 0))  # 3.2 m
    assert 0.003 < near < far < 0.03
    assert near_error < far_error


def test_no_fix_close_to_the_wall_until_it_backs_away():
    # Camera facing the -x wall from 4 in away: too close to read the strip.
    sim = sim_at(Pose(-72 + 7.5 + 0.5, 0, 0), pos=(-6.0, 0.0), yaw=180.0)
    sim.run_for(0.5)
    gps = sim.bot.Gps(15)
    assert sim.sensors.devices[15].value is None and gps.get_heading() == PROS_ERR_F
    gps.set_position(-1.5, 0.0, 90.0)
    assert gps.get_heading() == 90.0  # the code's initial pose stands in
    for group in sim.robot.groups:
        group.set_voltage(6.0)
    sim.run_for(0.6)
    r = sim.sensors.devices[15].value
    assert r is not None and r.fix


def test_dead_reckons_heading_and_reports_growing_error_without_a_fix():
    sim = sim_at(Pose(0, 0, 0), noise="ideal", pos=(6.0, 0.0), yaw=0.0)
    sim.run_for(0.2)
    device = sim.sensors.devices[15]
    device.spec = dataclasses.replace(device.spec, max_range_m=1.0)  # nothing in range now
    before = device.value
    sim.robot.group("left").set_voltage(-6.0)
    sim.robot.group("right").set_voltage(6.0)
    sim.run_for(0.4)
    for group in sim.robot.groups:
        group.brake_mode = BrakeMode.BRAKE
        group.stop()
    sim.run_for(0.4)  # stopped, so the reading's age doesn't matter
    r = device.value
    assert not r.fix and (r.x_m, r.y_m) == (before.x_m, before.y_m)  # held
    true_heading = (90 - math.degrees(sim.robot.heading)) % 360
    assert abs(true_heading - 90) > 30  # it really turned
    assert r.heading_deg == pytest.approx(true_heading, abs=0.5)  # the gyro kept up
    assert r.error_m > before.error_m + 0.02


def test_gps_corrected_odometry_beats_plain_odometry():
    cfg = robot_with_gps()
    errors = {"tracking wheels + IMU": [], "tracking wheels + IMU + GPS": []}
    for seed in (0, 1, 2):
        run = run_odometry(cfg, "aggressive", seed=seed)
        for name in errors:
            errors[name].append(run.final_error(name)[0])
    assert np.mean(errors["tracking wheels + IMU + GPS"]) < 0.8 * np.mean(
        errors["tracking wheels + IMU"]
    )
    sim = Simulation(cfg, echo=None)
    assert sim.localizer.name == "tracking wheels + IMU + GPS"  # the best-equipped baseline


GPS_PROGRAM = """\
#include "main.h"

void initialize() {}
void disabled() {}
void competition_initialize() {}
void opcontrol() {}

void autonomous() {
\tpros::Gps gps(15, 0.0, 0.1524);
\tpros::delay(100);
\tpros::gps_position_s_t p = gps.get_position();
\tprintf("%.4f %.4f %.3f %.4f %d\\n", p.x, p.y, gps.get_heading(), gps.get_error(),
\t       (int)pros::Device::get_plugged_type(15));
\tpros::Gps none(16);
\tprintf("%d\\n", none.get_heading() == PROS_ERR_F);
}
"""


def test_pros_gps_in_cpp(build, tmp_path):
    project = tmp_path / "gps"
    (project / "src").mkdir(parents=True)
    (project / "include").mkdir()
    (project / "include" / "main.h").write_text(
        '#include "api.h"\nextern "C" {\nvoid autonomous(void);\nvoid initialize(void);\n'
        "void disabled(void);\nvoid competition_initialize(void);\nvoid opcontrol(void);\n}\n"
    )
    (project / "src" / "main.cpp").write_text(GPS_PROGRAM)
    exe = build(project).executable
    lines = []
    cfg = robot_with_gps(noise="ideal")
    sim = Simulation(cfg, program=CppProgram(exe), start=Pose(-24, 12, 30), echo=lines.append)
    sim.start("autonomous")
    try:
        sim.run_for(0.3)
    finally:
        sim.close()
    out = [line.split("] ", 1)[1] for line in lines]
    x, y, heading, error, kind = (float(v) for v in out[0].split())
    assert (x * METER_IN, y * METER_IN) == pytest.approx((-24, 12), abs=1e-3)
    assert heading == pytest.approx(240.0) and error == 0.0 and kind == 20  # E_DEVICE_GPS
    assert "port 16: the code uses a GPS sensor here" in out[1]  # nothing on port 16...
    assert out[2] == "1"  # ...so it reads PROS_ERR_F

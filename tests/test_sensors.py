"""Phase 4: simulated V5 sensors."""

import copy
import math

import numpy as np
import pytest

from tests.conftest import EXAMPLE_ROBOT
from vexsim.config import load_robot
from vexsim.config.yaml_io import load_yaml_file
from vexsim.devices.devices import ray_to_walls
from vexsim.devices.specs import PRESETS, ImuSpec, sensor_spec
from vexsim.devices.suite import SensorSuite
from vexsim.physics.robot import Robot
from vexsim.physics.world import PRIORITY_SENSOR, World
from vexsim.units import in_to_m

ROBOT_DATA = load_yaml_file(EXAMPLE_ROBOT)
IMU, VERTICAL, HORIZONTAL, DISTANCE = 10, 11, 12, 13


def setup(noise="ideal", seed=0, data=None, pose=(0.0, 0.0, 0.0)):
    world = World(seed=seed)
    robot = world.add_system(Robot(load_robot(data or ROBOT_DATA), pose=pose))
    sensors = SensorSuite(robot, world.rng, noise=noise).attach(world)
    return world, robot, sensors


def truth_at_samples(world, robot):
    """Ground truth captured right after each 10 ms sensor sample, so it lines up with
    ideal (zero-latency) readings: a reading is up to one period older than "now"."""
    log = {}

    def capture(w):
        log["pose"] = robot.pose
        log["motor_position"] = {p: m.position for p, m in robot.motors.items()}

    world.every(10, capture, priority=PRIORITY_SENSOR + 1)
    return log


def drive(robot, left, right):
    for name, fraction in (("left", left), ("right", right)):
        group = robot.group(name)
        group.set_velocity(fraction * group.rated_speed)


# --- specs and presets --------------------------------------------------------------------


def test_presets_cover_every_sensor_type():
    assert set(PRESETS) == {"ideal", "default", "harsh", "replay"}  # replay: calibration's
    for preset in PRESETS.values():
        assert set(preset) == {"motor", "rotation", "imu", "distance", "gps"}
    ideal = PRESETS["ideal"]
    assert ideal["imu"].scale_error == 0 and ideal["rotation"].diameter_error == 0
    assert PRESETS["harsh"]["imu"].scale_error > PRESETS["default"]["imu"].scale_error


def test_spec_overrides_and_validation():
    assert sensor_spec("imu", "ideal", {"scale_error": 0.02}).scale_error == 0.02
    with pytest.raises(ValueError):
        ImuSpec(period_ms=2.5)
    with pytest.raises(ValueError):
        ImuSpec(scale_error=-0.1)


def test_suite_builds_one_device_per_port():
    _, _, sensors = setup()
    kinds = {port: d.kind for port, d in sensors.devices.items()}
    assert kinds == {
        1: "motor", 2: "motor", 3: "motor", 4: "motor", 5: "motor", 6: "motor",
        IMU: "imu", VERTICAL: "rotation", HORIZONTAL: "rotation", DISTANCE: "distance",
    }  # fmt: skip


def test_robot_config_overrides_reach_the_devices():
    data = copy.deepcopy(ROBOT_DATA)
    data["overrides"] = {"sensor.imu.calibration_s": 3.0, "sensor.rotation.period_ms": 5}
    _, _, sensors = setup("default", data=data)
    assert sensors.device(IMU).spec.calibration_s == 3.0
    assert sensors.device(VERTICAL).period_ms == 5


# --- timing ----------------------------------------------------------------------------------


def test_readings_appear_after_period_and_latency():
    world, _, sensors = setup("default")
    motor = sensors.device(1)  # 10 ms period, 5 ms latency
    assert motor.value is None
    world.run_for(0.004)
    assert motor.value is None  # sampled at t=0, not yet published
    world.run_for(0.002)
    assert motor.value is not None and motor.published_at_us == 5_000


def test_frame_lists_every_device():
    world, _, sensors = setup()
    world.run_for(2.1)
    frame = sensors.frame(world.time)
    assert sorted(frame.motors) == [1, 2, 3, 4, 5, 6]
    assert set(frame.rotation) == {VERTICAL, HORIZONTAL}
    assert frame.imu[IMU] is not None and isinstance(frame.distance[DISTANCE], int)


# --- motor encoders --------------------------------------------------------------------------


def test_motor_encoder_quantization_and_raw_direction():
    world, robot, sensors = setup("default")
    drive(robot, 0.5, 0.5)
    world.run_for(1.0)
    left, right = sensors.device(1).value, sensors.device(4).value
    step = 360 / 300  # blue cartridge: 300 counts per output revolution
    assert left.position_deg / step == pytest.approx(round(left.position_deg / step))
    assert left.position_deg > 0 > right.position_deg  # right motors are reversed (ports -4..-6)
    assert left.velocity_rpm == pytest.approx(300, rel=0.05)
    assert left.current_ma > 0 and left.voltage_mv > 0


def test_motor_encoders_count_wheel_spin_not_ground_travel():
    world, robot, sensors = setup()
    truth = truth_at_samples(world, robot)
    drive(robot, 1.0, 1.0)
    world.run_for(0.1)  # launch: the wheels spin on the tiles
    wheel_travel = math.radians(sensors.device(1).value.position_deg) * 0.75 * in_to_m(3.25) / 2
    assert wheel_travel > 1.1 * truth["pose"][0]


# --- rotation sensors / tracking wheels --------------------------------------------------------


def test_ideal_tracking_wheel_measures_ground_travel():
    world, robot, sensors = setup()
    truth = truth_at_samples(world, robot)
    drive(robot, 0.6, 0.6)
    world.run_for(1.0)
    vertical = sensors.device(VERTICAL)
    travelled = vertical.value.position_cdeg / 36000 * math.pi * in_to_m(2.0)
    assert travelled == pytest.approx(truth["pose"][0], abs=in_to_m(0.01))
    assert abs(sensors.device(HORIZONTAL).value.position_cdeg) < 5  # no sideways motion


def test_horizontal_wheel_sees_sideways_slide():
    world, robot, sensors = setup()
    truth = truth_at_samples(world, robot)
    robot.external_force = np.array([0.0, 30.0])  # shove the robot left
    world.run_for(0.5)
    slide = sensors.device(HORIZONTAL).value.position_cdeg / 36000 * math.pi * in_to_m(2.0)
    assert slide == pytest.approx(truth["pose"][1], rel=0.01)
    assert truth["pose"][1] > 0.05


def test_reversed_rotation_sensor_reads_backwards():
    data = copy.deepcopy(ROBOT_DATA)
    data["sensors"][1]["reversed"] = True
    world, robot, sensors = setup(data=data)
    drive(robot, 0.5, 0.5)
    world.run_for(0.5)
    assert sensors.device(VERTICAL).value.position_cdeg < 0


def test_diameter_error_scales_the_reading():
    world, robot, sensors = setup("ideal", seed=4)
    device = sensors.device(VERTICAL)
    nominal = in_to_m(2.0) / 2
    device.radius = nominal * 1.02  # the real wheel is 2% bigger than configured
    truth = truth_at_samples(world, robot)
    drive(robot, 0.6, 0.6)
    world.run_for(1.0)
    measured = math.radians(device.value.position_cdeg / 100) * nominal
    assert measured / truth["pose"][0] == pytest.approx(1 / 1.02, rel=1e-3)
    assert setup("default", seed=4)[2].device(VERTICAL).radius != nominal  # drawn per device


def test_liftoff_loses_distance():
    data = copy.deepcopy(ROBOT_DATA)
    data["overrides"] = {"sensor.rotation.liftoff_rate_hz": 20.0}
    world, robot, sensors = setup("ideal", data=data)  # overrides apply on top of the preset
    assert sensors.device(VERTICAL).spec.liftoff_rate_hz == 20.0
    drive(robot, 0.6, 0.6)
    world.run_for(1.0)
    travelled = sensors.device(VERTICAL).value.position_cdeg / 36000 * math.pi * in_to_m(2.0)
    assert travelled < 0.8 * robot.pose[0]


# --- IMU ----------------------------------------------------------------------------------------


def test_imu_reads_nothing_while_calibrating():
    world, _, sensors = setup("default")
    imu = sensors.device(IMU)
    world.run_for(1.9)
    assert imu.calibrating and imu.value is None
    world.run_for(0.2)
    assert not imu.calibrating and imu.value.rotation_deg == pytest.approx(0.0, abs=0.1)


def test_imu_heading_is_clockwise_positive():
    world, robot, sensors = setup()
    truth = truth_at_samples(world, robot)
    world.run_for(2.1)
    drive(robot, -0.3, 0.3)  # turn left (counter-clockwise)
    world.run_for(1.0)
    reading = sensors.device(IMU).value
    true_ccw = math.degrees(truth["pose"][2])
    assert true_ccw > 30
    assert reading.rotation_deg == pytest.approx(-true_ccw, abs=1e-6)
    assert reading.heading_deg == pytest.approx(360 - true_ccw, abs=1e-6)
    assert reading.gyro_z_deg_s < 0


class StillRobot:
    heading = 0.0


def test_imu_drift_while_still_is_a_few_tenths_per_minute():
    from vexsim.config.robot import ImuConfig
    from vexsim.core.rng import RngStreams
    from vexsim.devices.devices import ImuDevice

    drifts = []
    for seed in range(20):
        rng = RngStreams(seed)
        imu = ImuDevice(
            ImuConfig(type="imu", port=IMU),
            StillRobot(),
            sensor_spec("imu", "default"),
            rng.stream("imu"),
            rng.stream("imu.static"),
        )
        for k in range(6200):  # calibrate for 2 s, then sit still for a minute
            reading = imu.measure(k * 10_000)
        drifts.append(abs(reading.rotation_deg))
    # VEX forum: a few tenths of a degree per minute is normal, under 1 deg/min is good.
    assert max(drifts) < 1.0
    assert np.mean(drifts) > 0.02


def test_moving_during_calibration_ruins_the_heading():
    world, robot, sensors = setup("ideal")
    drive(robot, -0.2, 0.2)  # spinning while the IMU calibrates
    world.run_for(2.0)
    drive(robot, 0, 0)
    world.run_for(1.0)
    still_since = robot.pose[2]
    world.run_for(10.0)
    assert abs(robot.pose[2] - still_since) < 1e-3  # really standing still...
    assert abs(sensors.device(IMU).value.gyro_z_deg_s) > 10  # ...but the IMU "sees" a turn


def test_imu_scale_error_survives_calibration():
    data = copy.deepcopy(ROBOT_DATA)
    data["overrides"] = {"sensor.imu.scale_error": 0.02}
    world, robot, sensors = setup("ideal", seed=2, data=data)
    imu = sensors.device(IMU)
    truth = truth_at_samples(world, robot)
    world.run_for(2.1)
    drive(robot, -0.3, 0.3)
    world.run_for(3.0)
    ratio = -imu.value.rotation_deg / math.degrees(truth["pose"][2])
    assert ratio == pytest.approx(imu.scale, rel=1e-3)
    assert abs(imu.scale - 1) > 0.001


# --- distance sensor ------------------------------------------------------------------------------


def test_ray_to_walls():
    assert ray_to_walls(0, 0, 0, 1.0, 2.0) == pytest.approx(1000)
    assert ray_to_walls(0.5, 0, math.pi, 1.0, 2.0) == pytest.approx(1500)
    assert ray_to_walls(0, 0, math.pi / 4, 1.0, 1.0) == pytest.approx(1000 * math.sqrt(2))
    assert ray_to_walls(2.0, 0, 0, 1.0, 1.0) is None


def test_distance_sensor_measures_the_wall_ahead():
    # Facing +x from 1 m left of the far wall: the sensor sits 7 in ahead of the center.
    half = in_to_m(72)
    world, robot, sensors = setup(pose=(half - 1.0, 0.0, 0.0))
    world.run_for(0.04)
    expected = (1.0 - in_to_m(7)) * 1000
    assert sensors.device(DISTANCE).value == pytest.approx(expected, abs=1)


def test_distance_sensor_range_and_noise():
    world, robot, sensors = setup("default", pose=(0.0, 0.0, 0.0))  # ~1.65 m to the wall
    device = sensors.device(DISTANCE)
    true = device.true_distance_mm()
    readings = [device.measure(0) for _ in range(2000)]
    assert np.mean(readings) == pytest.approx(true, rel=0.005)
    assert np.std(readings) == pytest.approx(0.025 * true, rel=0.1)

    far = setup("default", pose=(-in_to_m(60), 0.0, 0.0))[2].device(DISTANCE)
    assert far.true_distance_mm() > 2000 and far.measure(0) is None


# --- determinism ----


def test_same_seed_same_readings_and_streams_are_independent():
    def readings(seed, data=None):
        world, robot, sensors = setup("harsh", seed=seed, data=data)
        drive(robot, 0.7, 0.4)
        world.run_for(3.0)
        return sensors.device(IMU).value.rotation_deg, sensors.device(VERTICAL).value

    assert readings(5) == readings(5)
    assert readings(5) != readings(6)
    # Removing the distance sensor must not change any other sensor's noise.
    data = copy.deepcopy(ROBOT_DATA)
    data["sensors"] = data["sensors"][:3]
    assert readings(5, data) == readings(5)

"""All of a robot's devices, wired into the world loop."""

from __future__ import annotations

from collections.abc import Mapping

from vexsim.config.field import FieldConfig
from vexsim.core.rng import RngStreams
from vexsim.devices.devices import (
    Device,
    DistanceDevice,
    GpsDevice,
    ImuDevice,
    MotorDevice,
    RotationDevice,
)
from vexsim.devices.frame import SensorFrame
from vexsim.devices.specs import sensor_spec
from vexsim.physics.robot import Robot
from vexsim.physics.world import PRIORITY_SENSOR, World


class SensorSuite:
    """Builds one device per port from the robot config and samples them.

    Add the robot to the world first, then ``attach`` the suite, so each tick
    runs: sample sensors -> controllers -> robot physics -> sensor integration.

    ``noise`` overrides every sensor's configured preset (``ideal``, ``default``
    or ``harsh``). Robot-config overrides like ``sensor.imu.scale_error`` apply
    on top of the preset.
    """

    def __init__(
        self,
        robot: Robot,
        rng: RngStreams,
        *,
        field: FieldConfig | None = None,
        noise: str | None = None,
        arena=None,
    ):
        self.robot = robot
        field = field or FieldConfig()
        overrides: Mapping[str, dict[str, float]] = robot.params.sensor_overrides
        self.devices: dict[int, Device] = {}

        def spec(kind: str, preset: str):
            return sensor_spec(kind, noise or preset, overrides.get(kind))

        def streams(kind: str, port: int):
            return rng.stream(f"sensor.{kind}.{port}"), rng.stream(f"sensor.{kind}.{port}.static")

        for port, motor in sorted(robot.motors.items()):
            noisy, _ = streams("motor", port)
            self.devices[port] = MotorDevice(port, motor, spec("motor", "default"), noisy)
        for cfg in robot.config.sensors:
            noisy, static = streams(cfg.type, cfg.port)
            if cfg.type == "rotation":
                device = RotationDevice(cfg, robot, spec("rotation", cfg.noise), noisy, static)
            elif cfg.type == "imu":
                device = ImuDevice(cfg, robot, spec("imu", cfg.noise), noisy, static)
            elif cfg.type == "gps":
                device = GpsDevice(cfg, robot, field, spec("gps", cfg.noise), noisy, arena)
            else:
                distance_spec = spec("distance", cfg.noise)
                device = DistanceDevice(cfg, robot, field, distance_spec, noisy, arena)
            self.devices[cfg.port] = device

    def attach(self, world: World) -> SensorSuite:
        world.add_system(self)
        for device in self.devices.values():
            world.every(
                device.period_ms,
                lambda w, d=device: d.sample(w.clock.us),
                priority=PRIORITY_SENSOR,
                name=f"{device.kind}.{device.port}",
            )
        return self

    def step(self, world: World, dt: float) -> None:
        for device in self.devices.values():
            device.integrate(self.robot, dt)
        end_us = world.clock.us + world.dt_us
        for device in self.devices.values():
            device.publish(end_us)

    def frame(self, time: float) -> SensorFrame:
        groups: dict[str, dict] = {k: {} for k in ("motor", "rotation", "imu", "distance", "gps")}
        for port, device in self.devices.items():
            groups[device.kind][port] = device.value
        return SensorFrame(
            time=time,
            motors=groups["motor"],
            rotation=groups["rotation"],
            imu=groups["imu"],
            distance=groups["distance"],
            gps=groups["gps"],
        )

    def device(self, port: int) -> Device:
        return self.devices[port]

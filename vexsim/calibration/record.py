"""Recording a robot log in the simulator: the columns a real robot's logger writes."""

from __future__ import annotations

import math

from vexsim.calibration.log import RobotLog, columns_for, motor_ports
from vexsim.devices.suite import SensorSuite
from vexsim.physics.motor import BrakeMode, ControlMode
from vexsim.physics.robot import Robot
from vexsim.physics.world import PRIORITY_RECORD, World
from vexsim.units import rad_s_to_rpm

NAN = math.nan
BRAKE_CODE = {BrakeMode.COAST: 0, BrakeMode.BRAKE: 1, BrakeMode.HOLD: 2}  # PROS enum values
PERIOD_MS = 10
# What the simulated distance sensors report besides the distance, as the robot code sees it
# (bridge/cpp/runtime/devices.cpp): the most confidence there is, and a large object (a wall)
DISTANCE_CONFIDENCE = 63
DISTANCE_OBJECT_SIZE = 400


class RobotLogger:
    """Every 10 ms, after the robot code has run, records its readings and motor commands.

    Readings are the robot code's view (sampled, delayed, noisy, raw direction);
    commands are what the code set for the next step.
    """

    def __init__(self, robot: Robot, sensors: SensorSuite):
        self.robot, self.sensors = robot, sensors
        self.names = columns_for(robot.config)
        self.rows: list[list[float]] = []
        self._t0_us: int | None = None
        config = robot.config
        self._motor_ports = motor_ports(config)
        # (type, port) in column order, as columns_for lists them
        self._sensor_ports = [
            (s.type, s.port) for s in sorted(config.sensors, key=lambda s: s.port)
        ]

    def attach(self, world: World) -> RobotLogger:
        world.every(PERIOD_MS, self.capture, priority=PRIORITY_RECORD, name="robot log")
        return self

    def capture(self, world: World) -> None:
        if self._t0_us is None:
            self._t0_us = world.clock.us
        self.rows.append(self.row((world.clock.us - self._t0_us) / 1000.0))

    def row(self, time_ms: float) -> list[float]:
        robot, devices = self.robot, self.sensors.devices
        power = robot.power
        values = [time_ms, round(power.bus_voltage * 1000), round(power.battery_current_a * 1000)]
        for port in self._motor_ports:
            motor, device = robot.motors[port], devices[port]
            cmd_mv = cmd_rpm = NAN
            if motor.mode is ControlMode.VOLTAGE:
                cmd_mv = round(motor.command * 1000)
            elif motor.mode is ControlMode.VELOCITY:
                cmd_rpm = rad_s_to_rpm(motor.command)
            elif motor.mode is ControlMode.STOPPED:
                cmd_mv = 0
            r = device.value
            if r is None:
                values += [cmd_mv, cmd_rpm, BRAKE_CODE[motor.brake_mode], NAN, NAN, NAN, NAN, NAN]
            else:
                values += [
                    cmd_mv,
                    cmd_rpm,
                    BRAKE_CODE[motor.brake_mode],
                    r.position_deg - device.zero_deg,
                    r.velocity_rpm,
                    r.current_ma,
                    r.voltage_mv,
                    r.temperature_c,
                ]
        for kind, port in self._sensor_ports:
            values += _sensor_values(kind, devices[port].value)
        return values

    def log(self) -> RobotLog:
        return RobotLog.from_rows(self.names, self.rows)

    def devices(self) -> str:
        """What is on each port, as vexsim's logger lists it ("1 motor, 10 imu")."""
        found = [(p, "motor") for p in self._motor_ports]
        found += [(port, kind) for kind, port in self._sensor_ports]
        return ", ".join(f"{port} {kind}" for port, kind in sorted(found))


def _sensor_values(kind: str, value) -> list[float]:
    if kind == "gps":
        if value is None:
            return [NAN] * 4
        return [value.x_m, value.y_m, value.heading_deg, value.error_m]
    if kind == "distance":  # mm; with nothing in range, no confidence and no object
        if value is None:
            return [NAN, 0, 0]
        return [value, DISTANCE_CONFIDENCE, DISTANCE_OBJECT_SIZE]
    if value is None:
        return [NAN]
    if kind == "imu":
        return [value.rotation_deg]
    return [value.position_cdeg]  # rotation

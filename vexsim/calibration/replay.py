"""Replaying a robot log in the simulator.

The simulated robot gets the log's motor commands at the log's times, and its
sensors are read every millisecond. Comparing what it measures with the log
shows how well the model reproduces the real robot; the fit (fit.py) adjusts
parameters until they agree.

* Sensors are read without noise, per-device errors or latency (the
  ``replay`` preset): the model can't know a particular robot's errors.
* A reading is a few ms old by the time robot code sees it: the sensor's
  latency plus however long ago its last 10 ms update was, which depends on
  the phase between the code's loop and the sensor. That age is constant for
  a periodic logger, so each log row is compared with the replay's state
  ``age_ms`` before it, and ``best_age`` finds the age that fits.
* The battery voltage follows the log, when it has one: the motors see the
  voltage the real battery delivered, so battery modeling errors stay out of
  the fit.
* A motor whose commands weren't logged is driven with its logged voltage
  (``m<p>_mv``), which works for any program, whatever its control mode. That
  voltage is a reading too, so it is applied ``lead_ms`` before its row.
* The robot starts at rest, on an endless floor (no walls). Start logs at rest.
"""

from __future__ import annotations

import math

import numpy as np

from vexsim.calibration.log import RobotLog
from vexsim.calibration.record import RobotLogger
from vexsim.config.robot import RobotConfig
from vexsim.devices.devices import ImuDevice
from vexsim.devices.suite import SensorSuite
from vexsim.physics.motor import BrakeMode, V5Motor
from vexsim.physics.params import resolve_params
from vexsim.physics.robot import Robot
from vexsim.physics.world import PRIORITY_RECORD, World
from vexsim.units import rpm_to_rad_s

BRAKE_MODES = {0: BrakeMode.COAST, 1: BrakeMode.BRAKE, 2: BrakeMode.HOLD}
QUIESCENT_A = 0.3
AGES_MS = range(0, 26)  # reading ages best_age tries
LEADS_MS = range(0, 30, 5)  # how much earlier measured voltages may have been applied


class LoggedSupply:
    """The bus voltage a real battery delivered, played back from a log."""

    def __init__(self, time_s: np.ndarray, volts: np.ndarray):
        ok = np.isfinite(volts)
        self._time, self._volts = time_s[ok], volts[ok]
        self.time = 0.0
        self.battery_current_a = QUIESCENT_A
        self._load_w = 0.0
        self.bus_voltage = float(self._volts[0])

    def add_load(self, power_w: float) -> None:
        self._load_w += power_w

    def end_step(self, dt: float) -> None:
        self.battery_current_a = max(self._load_w, 0.0) / self.bus_voltage + QUIESCENT_A
        self._load_w = 0.0
        self.time += dt
        self.bus_voltage = float(np.interp(self.time, self._time, self._volts))


def commands_logged(log: RobotLog) -> bool:
    """Whether every motor in the log has its commands logged (not just its voltage)."""
    for port in log.ports("m"):
        known = [log[f"m{port}_{k}"] for k in ("cmd_mv", "cmd_rpm") if f"m{port}_{k}" in log]
        if not any(np.isfinite(c).any() for c in known):
            return False
    return True


def simulate(
    config: RobotConfig,
    log: RobotLog,
    overrides: dict[str, float] | None = None,
    lead_ms: int = 0,
) -> RobotLog:
    """The simulated robot's readings every millisecond while it follows the log's commands
    (``time_ms`` from 0, the log's first row)."""
    params = resolve_params({**config.overrides, **(overrides or {})})
    world = World(seed=0)
    robot = world.add_system(Robot(config, params=params))
    sensors = SensorSuite(robot, world.rng, noise="replay").attach(world)
    imus = [d for d in sensors.devices.values() if isinstance(d, ImuDevice)]
    world.run_until(lambda w: all(d.value is not None for d in imus), timeout_s=10.0)

    times = np.round(log.time_ms - log.time_ms[0]).astype(int)
    if "battery_mv" in log and np.isfinite(log["battery_mv"]).any():
        supply = LoggedSupply(times / 1000.0, log["battery_mv"] / 1000.0)
        robot.power = supply
        for motor in robot.motors.values():
            motor.supply = supply
    motors = [
        _MotorCommands(robot.motors[port], log, port)
        for port in log.ports("m")
        if port in robot.motors
    ]
    logged = [m for m in motors if m.logged]
    measured = [m for m in motors if not m.logged]
    logger = RobotLogger(robot, sensors)
    t0_us, rows = world.clock.us, []
    k_logged = k_measured = 0

    def tick(w: World) -> None:
        nonlocal k_logged, k_measured
        elapsed_ms = (w.clock.us - t0_us) // 1000
        rows.append(logger.row(float(elapsed_ms)))
        while k_logged < len(times) and times[k_logged] <= elapsed_ms:
            for m in logged:
                m.apply(k_logged)
            k_logged += 1
        while k_measured < len(times) and times[k_measured] - lead_ms <= elapsed_ms:
            for m in measured:
                m.apply(k_measured)
            k_measured += 1

    world.every(1, tick, priority=PRIORITY_RECORD, name="replay")
    world.run_for((int(times[-1]) + 1) / 1000)
    return RobotLog.from_rows(logger.names, rows)


def at_age(states: RobotLog, log: RobotLog, age_ms: int) -> RobotLog:
    """The replay's readings for each log row: its state ``age_ms`` before the row."""
    times = np.round(log.time_ms - log.time_ms[0]).astype(int) - age_ms
    index = np.clip(times, 0, len(states) - 1)
    out = RobotLog({name: values[index] for name, values in states.columns.items()})
    out.columns["time_ms"] = log.time_ms.copy()
    return out


def replay(
    config: RobotConfig, log: RobotLog, overrides: dict[str, float] | None = None, age_ms: int = 10
) -> RobotLog:
    """The simulated robot's log for the same commands, at the same times."""
    return at_age(simulate(config, log, overrides), log, age_ms)


class _MotorCommands:
    """One motor's logged commands as plain lists (fast to index every 10 ms)."""

    def __init__(self, motor: V5Motor, log: RobotLog, port: int):
        self.motor = motor

        def column(name: str) -> list[float]:
            key = f"m{port}_{name}"
            return log[key].tolist() if key in log else [math.nan] * len(log)

        self.cmd_mv, self.cmd_rpm = column("cmd_mv"), column("cmd_rpm")
        self.brake, self.mv = column("brake"), column("mv")
        self.logged = any(v == v for v in self.cmd_mv + self.cmd_rpm)  # any not NaN

    def apply(self, k: int) -> None:
        motor = self.motor
        brake = self.brake[k]
        if brake == brake and int(brake) in BRAKE_MODES:  # not NaN
            motor.brake_mode = BRAKE_MODES[int(brake)]
        mv, rpm = self.cmd_mv[k], self.cmd_rpm[k]
        if mv == mv:
            motor.set_voltage(mv / 1000.0)  # 0 stops with the brake mode
        elif rpm == rpm:
            motor.set_velocity(rpm_to_rad_s(rpm))
        else:
            measured = self.mv[k]
            if measured == measured:
                motor.set_voltage(measured / 1000.0 if abs(measured) >= 1.0 else 0.0)

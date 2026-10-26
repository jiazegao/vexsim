"""A built PROS project as a simulation program.

Pass a ``CppProgram`` as ``Simulation(program=...)``. The simulation calls the
competition functions (initialize, autonomous, opcontrol, ...) the way field
control would; the robot host runs them as the PROS competition task, and
every task the code creates keeps running across phases, as on the V5.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from vexsim.algorithms.localization.base import Pose
from vexsim.api.devices import ANALOG, DIGITAL
from vexsim.bridge.build import BuildResult, build_project
from vexsim.bridge.host import HostError, Reply, RobotHost
from vexsim.devices.devices import DistanceDevice, ImuDevice, MotorDevice, RotationDevice
from vexsim.physics.motor import BrakeMode
from vexsim.physics.world import PRIORITY_CONTROL, World
from vexsim.units import rpm_to_rad_s

if TYPE_CHECKING:
    from vexsim.runtime.simulation import Simulation

# competition_get_status() bits
DISABLED, AUTONOMOUS, CONNECTED, FIELD = 1, 2, 4, 8

# How each simulation mode looks to the robot: not connected (driver practice),
# a competition switch (autonomous runs), or field control (matches, skills).
CONNECTION = {
    "driver": 0,
    "autonomous": CONNECTED,
    "match": CONNECTED | FIELD,
    "skills": CONNECTED | FIELD,
}

_CARTRIDGES = {36: "red", 18: "green", 6: "blue"}
_BRAKES = {"coast": BrakeMode.COAST, "brake": BrakeMode.BRAKE, "hold": BrakeMode.HOLD}


class HostPhase:
    """One competition function running in the robot host (the Coroutine of C++ code)."""

    def __init__(
        self, program: CppProgram, name: str, serial: int, start_us: int, limit_s: float | None
    ):
        self.program = program
        self.name = name
        self.serial = serial
        self.end_us = None if limit_s is None else start_us + round(limit_s * 1e6)
        self.finished = False
        self.timed_out = False

    def tick(self, now_us: int) -> None:
        if self.finished:
            return
        if self.serial in self.program.finished_serials:
            self.finished = True
        elif self.end_us is not None and now_us >= self.end_us:
            self.timed_out = True
            self.stop()

    def stop(self) -> None:
        """Field control ends the period: the competition task is deleted, disabled() starts."""
        self.finished = True
        self.program.start_phase("disabled", None, 0)


class CppProgram:
    """A ``vexsim build`` executable, run in lockstep with the simulation."""

    native = True

    def __init__(
        self,
        executable: str | Path,
        *,
        name: str | None = None,
        spin_calls_per_ms: int = 1000,
        busy_timeout_s: float = 5.0,
        env: dict[str, str] | None = None,
    ):
        self.executable = Path(executable)
        self.env = env
        self.name = name or self.executable.parent.name
        self.spin_calls_per_ms = spin_calls_per_ms
        self.busy_timeout_s = busy_timeout_s
        self.build: BuildResult | None = None
        self.host: RobotHost | None = None
        self.sim: Simulation | None = None
        self.finished_serials: set[int] = set()
        self._serial = 0
        self._pending: list[str] = []
        self._next_wake: int | None = 0
        self._sent: dict[object, object] = {}

    @classmethod
    def from_project(cls, project: str | Path, *, log=None, **kwargs) -> CppProgram:
        """Build a PROS project (incrementally) and wrap the result."""
        result = build_project(project, log=log)
        program = cls(result.executable, name=Path(project).resolve().name, **kwargs)
        program.build = result
        return program

    # --- Simulation hooks ---------------------------------------------------------------------

    def attach(self, sim: Simulation) -> None:
        """Start the robot host with the robot's devices; called by Simulation.__init__."""
        self.sim = sim
        self._devices = sorted(sim.sensors.devices.items())
        for _, device in self._devices:
            if isinstance(
                device, ImuDevice
            ):  # the brain booted (and the IMU calibrated) before t = 0
                device.finish_boot_calibration(sim.world.clock.us)
        devices = []
        for port, device in self._devices:
            if isinstance(device, MotorDevice):
                devices.append((port, "motor", _CARTRIDGES.get(device.motor.ratio, "green")))
            elif isinstance(device, ImuDevice):
                devices.append((port, "imu", ""))
            elif isinstance(device, RotationDevice):
                devices.append((port, "rotation", ""))
            elif isinstance(device, DistanceDevice):
                devices.append((port, "distance", ""))
        self.host = RobotHost(
            self.executable,
            devices,
            spin_calls_per_ms=self.spin_calls_per_ms,
            busy_timeout_s=self.busy_timeout_s,
            env=self.env,
        )
        self._apply(self.host.startup, sim.world.clock.us)
        sim.world.every(1, self._tick, priority=PRIORITY_CONTROL, name="robot code")

    def start_phase(self, name: str, limit_s: float | None, now_us: int) -> HostPhase:
        """Switch field control to ``name``; the host starts it as the competition task."""
        self._serial += 1
        connection = CONNECTION.get(self.sim.mode if self.sim else "driver", 0)
        if name in ("initialize", "disabled", "competition_initialize"):
            status = connection | DISABLED if connection or name == "disabled" else 0
        elif name == "autonomous":
            status = connection | AUTONOMOUS
        else:
            status = connection
        self._pending.append(f"MODE {self._serial} {name} {status}")
        return HostPhase(self, name, self._serial, now_us, limit_s)

    def close(self) -> None:
        if self.host is not None:
            self.host.close()

    # --- each millisecond ---------------------------------------------------------------------

    def _tick(self, world: World) -> None:
        now = world.clock.us
        if not self._pending and (self._next_wake is None or now < self._next_wake):
            return
        lines = self._pending + self._readings()
        self._pending = []
        try:
            reply = self.host.run(now, lines)
        except HostError:
            world.stop()
            raise
        self._next_wake = reply.next_wake_us
        self._apply(reply, now)

    def _changed(self, key: object, value: object) -> bool:
        if self._sent.get(key) == value:
            return False
        self._sent[key] = value
        return True

    def _readings(self) -> list[str]:
        sim = self.sim
        lines = []
        for port, device in self._devices:
            value = device.value
            if isinstance(device, ImuDevice):
                calibrating = device.calibrating or value is None
                if not self._changed(port, (device.published_at_us, calibrating)):
                    continue
                if calibrating:
                    lines.append(f"i {port} cal")
                else:
                    lines.append(f"i {port} {value.rotation_deg:.9g} {value.gyro_z_deg_s:.6g}")
                continue
            if not self._changed(port, device.published_at_us):
                continue
            if isinstance(device, MotorDevice) and value is not None:
                flags = int(value.over_temp) | 2 * int(value.over_current)
                lines.append(
                    f"m {port} {value.position_deg:.10g} {value.velocity_rpm:.6g} "
                    f"{value.current_ma} {value.voltage_mv} {value.temperature_c:.4g} "
                    f"{value.torque_nm:.5g} {value.power_w:.5g} {flags}"
                )
            elif isinstance(device, RotationDevice) and value is not None:
                lines.append(f"r {port} {value.position_cdeg} {value.velocity_cdeg_s:.6g}")
            elif isinstance(device, DistanceDevice):
                lines.append(f"d {port} {-1 if value is None else value}")
        controller = sim.controller
        buttons = sum(1 << i for i, b in enumerate(DIGITAL) if b in controller.digital)
        axes = tuple(controller.analog[a] for a in ANALOG)
        if self._changed("controller", (axes, buttons)):
            lines.append("c {} {} {} {} {}".format(*axes, buttons))
        power = sim.robot.power
        battery = (
            round(power.bus_voltage * 1000),
            round(power.battery_current_a * 1000),
            round(power.battery.soc * 100, 1),
        )
        if self._changed("battery", battery):
            lines.append("b {} {} {}".format(*battery))
        return lines

    def _apply(self, reply: Reply, now_us: int) -> None:
        sim = self.sim
        devices = sim.sensors.devices
        for cmd in reply.commands:
            verb, port = cmd[0], int(cmd[1])
            device = devices.get(port)
            if verb == "I":
                if isinstance(device, ImuDevice):
                    device.calibrate(now_us)
                continue
            if not isinstance(device, MotorDevice):
                continue
            motor = device.motor
            if verb == "M":
                kind = cmd[2]
                if kind == "v":
                    motor.set_voltage(int(cmd[3]) / 1000.0)
                elif kind == "s":
                    motor.set_velocity(rpm_to_rad_s(float(cmd[3])))
                elif kind == "p":
                    motor.set_position(math.radians(float(cmd[3])), rpm_to_rad_s(float(cmd[4])))
            elif verb == "B":
                motor.brake_mode = _BRAKES[cmd[2]]
            elif verb == "L":
                motor.current_limit_a = int(cmd[2]) / 1000.0
        for text in reply.console:
            sim.log(text)
        sim.lcd.update(reply.lcd)
        sim.controller_screen.update(reply.controller_screen)
        if reply.pose is not None:
            x, y, theta = reply.pose
            sim.reported_pose = Pose(x, y, 90.0 - theta)
        self.finished_serials.update(reply.finished)

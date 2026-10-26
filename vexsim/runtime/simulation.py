"""A ready-to-run simulation: world, robot, sensors, odometry, a program, and telemetry.

Each tick: sensors sample -> controller input and odometry update (every 10 ms)
-> the program coroutine runs (checked every 1 ms) -> physics -> telemetry.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from vexsim.algorithms.localization.base import Localizer, Pose
from vexsim.algorithms.localization.baselines import baseline_localizers
from vexsim.api import delay
from vexsim.api.chassis import Chassis
from vexsim.api.devices import ANALOG, Controller, Distance, Imu, Motor, MotorGroup, Rotation
from vexsim.config.field import FieldConfig
from vexsim.config.robot import RobotConfig
from vexsim.devices.devices import ImuDevice
from vexsim.devices.suite import SensorSuite
from vexsim.physics.robot import Robot
from vexsim.physics.world import PRIORITY_CONTROL, PRIORITY_RECORD, World
from vexsim.runtime.program import Coroutine, as_generator
from vexsim.runtime.recorder import Recorder
from vexsim.units import in_to_m

ORIGIN = Pose(0.0, 0.0, 0.0)

MODES: dict[str, list[tuple[str, float | None]]] = {
    "autonomous": [("initialize", None), ("autonomous", None)],
    "driver": [("initialize", None), ("opcontrol", None)],
    "match": [("initialize", None), ("autonomous", 15.0), ("opcontrol", 105.0)],
    "skills": [("initialize", None), ("autonomous", 60.0)],
}


class InputSource(Protocol):
    def poll(self, time_s: float) -> tuple[dict[str, float], set[str]]: ...


@dataclass
class ScriptedInput:
    """Controller input from time-stamped keyframes; each one holds until the next."""

    keyframes: list[tuple[float, dict[str, float], set[str]]] = field(default_factory=list)

    def poll(self, time_s: float) -> tuple[dict[str, float], set[str]]:
        current: tuple[dict[str, float], set[str]] = ({}, set())
        for t, analog, digital in self.keyframes:
            if t > time_s:
                break
            current = (analog, digital)
        return current

    @classmethod
    def from_csv(cls, path: str | Path) -> ScriptedInput:
        """Columns: time_s, any of LEFT_X/LEFT_Y/RIGHT_X/RIGHT_Y, and buttons (space-separated)."""
        frames = []
        with Path(path).open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                analog = {k: float(row[k]) for k in ANALOG if row.get(k) not in (None, "")}
                buttons = set((row.get("buttons") or "").upper().split())
                frames.append((float(row["time_s"]), analog, buttons))
        return cls(sorted(frames, key=lambda f: f[0]))


class Bot:
    """What a robot program receives: device constructors, the controller, a chassis, a clock."""

    def __init__(self, sim: Simulation):
        self._sim = sim
        self.controller = sim.controller
        drive = sim.robot.config.drivetrain
        self.chassis: Chassis | None = None
        if drive.type == "differential":
            left = MotorGroup(sim, drive.gearing["left"].motors)
            right = MotorGroup(sim, drive.gearing["right"].motors)
            self.chassis = Chassis(sim, left, right)

    # PROS-style constructors
    def Motor(self, port: int) -> Motor:  # noqa: N802 - mirrors pros::Motor
        return Motor(self._sim, port)

    def MotorGroup(self, ports: list[int]) -> MotorGroup:  # noqa: N802
        return MotorGroup(self._sim, ports)

    def Imu(self, port: int) -> Imu:  # noqa: N802
        return Imu(self._sim, port)

    def Rotation(self, port: int) -> Rotation:  # noqa: N802
        return Rotation(self._sim, port)

    def Distance(self, port: int) -> Distance:  # noqa: N802
        return Distance(self._sim, port)

    def millis(self) -> int:
        return self._sim.world.clock.us // 1000

    def battery_voltage_mv(self) -> int:
        return round(self._sim.robot.power.bus_voltage * 1000)

    def print(self, *args: Any) -> None:
        """Print to the console panel (and the terminal), stamped with simulation time."""
        self._sim.log(" ".join(str(a) for a in args))

    @property
    def pose(self) -> Pose:
        return self._sim.estimated_pose


def default_initialize(bot: Bot) -> Iterator[Any]:
    """Wait for every IMU to finish calibrating, like ``imu.reset(true)`` in initialize()."""
    imus = [d for d in bot._sim.sensors.devices.values() if isinstance(d, ImuDevice)]
    while any(d.calibrating or d.value is None for d in imus):
        yield delay(10)


def default_opcontrol(bot: Bot) -> Iterator[Any]:
    """Arcade drive: left stick forward/back, right stick turns."""
    if bot.chassis is None:
        return
    while True:
        bot.chassis.arcade(
            bot.controller.get_analog("LEFT_Y"), bot.controller.get_analog("RIGHT_X")
        )
        yield delay(10)


class Simulation:
    def __init__(
        self,
        config: RobotConfig,
        *,
        program: ModuleType | None = None,
        field: FieldConfig | None = None,
        seed: int = 0,
        noise: str | None = None,
        start: Pose = ORIGIN,
        battery_soc: float = 1.0,
        localizer: Localizer | None = None,
        input_source: InputSource | None = None,
        record: bool = True,
        echo: Callable[[str], None] | None = print,
    ):
        self.config = config
        self.field = field or FieldConfig()
        self.world = World(seed=seed)
        si_start = (in_to_m(start.x), in_to_m(start.y), start.heading * 3.141592653589793 / 180)
        self.robot = self.world.add_system(Robot(config, pose=si_start, battery_soc=battery_soc))
        self.sensors = SensorSuite(self.robot, self.world.rng, field=self.field, noise=noise)
        self.sensors.attach(self.world)
        baselines = baseline_localizers(config)
        self.localizer = localizer or (baselines[-1] if baselines else None)
        self.localizer_ready = False
        self.start_pose = start
        self.controller = Controller()
        self.input_source = input_source
        self.program = program
        self.console: list[str] = []
        self._echo = echo
        self.bot = Bot(self)
        self.phase = "disabled"
        self._phases: list[tuple[str, float | None]] = []
        self._current: Coroutine | None = None
        self.recorder = Recorder(self) if record else None

        self.world.every(10, self._before_program, priority=PRIORITY_CONTROL - 1, name="inputs")
        self.world.every(1, self._tick_program, priority=PRIORITY_CONTROL, name="program")
        if self.recorder is not None:
            self.world.every(10, self.recorder.capture, priority=PRIORITY_RECORD, name="record")

    # --- program control -----------------------------------------------------------------

    def start(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {sorted(MODES)}")
        if mode in ("autonomous", "skills") and not hasattr(self.program, "autonomous"):
            raise ValueError("the program has no autonomous() function")
        self._phases = list(MODES[mode])
        self._current = None

    @property
    def finished(self) -> bool:
        return not self._phases and self._current is None and self.phase != "disabled"

    def run_for(self, seconds: float) -> None:
        self.world.run_for(seconds)

    def run_until_finished(self, max_seconds: float) -> bool:
        return self.world.run_until(lambda w: self.finished, timeout_s=max_seconds)

    def log(self, text: str) -> None:
        line = f"[{self.world.time:7.2f}] {text}"
        self.console.append(line)
        if self._echo is not None:
            self._echo(line)

    # --- localization ----------------------------------------------------------------------

    @property
    def estimated_pose(self) -> Pose:
        if self.localizer is None or not self.localizer_ready:
            return self.start_pose
        return self.localizer.pose

    def reset_localizer(self, pose: Pose) -> None:
        if self.localizer is None:
            raise RuntimeError("this robot has no sensors a localizer can use")
        self.localizer.reset(pose, self.sensors.frame(self.world.time))
        self.localizer_ready = True

    # --- scheduled hooks -------------------------------------------------------------------

    def _before_program(self, world: World) -> None:
        if self.input_source is not None:
            analog, digital = self.input_source.poll(world.time)
            self.controller.update(analog, digital)
        if self.localizer is None:
            return
        frame = self.sensors.frame(world.time)
        if self.localizer_ready:
            self.localizer.update(frame)
        else:
            try:
                self.localizer.reset(self.start_pose, frame)
                self.localizer_ready = True
            except ValueError:
                pass  # sensors not ready yet (IMU calibrating)

    def _tick_program(self, world: World) -> None:
        now = world.clock.us
        if self._current is None:
            if not self._phases:
                return
            name, limit = self._phases.pop(0)
            fn = getattr(self.program, name, None) if self.program else None
            fn = fn or {"initialize": default_initialize, "opcontrol": default_opcontrol}[name]
            self.phase = name
            self._current = Coroutine(name, as_generator(fn, self.bot), now, limit)
        self._current.tick(now)
        if self._current.finished:
            if self._current.timed_out:
                self._disable()
            self._current = None
            if not self._phases:
                self.phase = "done"

    def _disable(self) -> None:
        """Field control ending a period: every motor stops."""
        for motor in self.robot.motors.values():
            motor.stop()

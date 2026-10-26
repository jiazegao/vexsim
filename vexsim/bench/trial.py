"""One trial: a seed, a localizer and a controller driving the scenario's task."""

from __future__ import annotations

import importlib.util
import math
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from vexsim.algorithms.control.base import ChassisGeometry, Controller
from vexsim.algorithms.control.motions import (
    Boomerang,
    MoveToPoint,
    ProfiledDrive,
    TurnToHeading,
)
from vexsim.algorithms.control.paths import PurePursuit, Ramsete, generate_trajectory
from vexsim.algorithms.localization.base import Localizer, Pose
from vexsim.algorithms.localization.baselines import baseline_localizers
from vexsim.bench.metrics import TrialMetrics, score
from vexsim.bench.scenario import ControllerSpec, LoadedScenario
from vexsim.config.loader import load_field, load_robot
from vexsim.config.robot import RobotConfig
from vexsim.core.rng import RngStreams
from vexsim.devices.devices import ImuDevice, RotationDevice
from vexsim.physics.world import PRIORITY_RECORD
from vexsim.runtime.simulation import Simulation


def _load_factory(ref: str, base_dir: Path):
    """``path/to/file.py:name`` -> the callable ``name`` from that file."""
    file, _, name = ref.rpartition(":")
    path = (base_dir / file).resolve()
    module_name = f"vexsim_bench_{path.stem}_{abs(hash(str(path)))}"
    module = sys.modules.get(module_name)
    if module is None:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return getattr(module, name)


def available_localizers(loaded: LoadedScenario, config: RobotConfig) -> list[str]:
    names = []
    for ref in loaded.scenario.localizers:
        if ref == "all":
            names += [loc.name for loc in baseline_localizers(config)]
        else:
            names.append(ref)
    return list(dict.fromkeys(names))


def make_localizer(ref: str, config: RobotConfig, base_dir: Path) -> Localizer:
    if ":" in ref:
        localizer = _load_factory(ref, base_dir)(config)
        localizer.name = getattr(localizer, "name", ref)
        return localizer
    for loc in baseline_localizers(config):
        if loc.name == ref:
            return loc
    known = ", ".join(loc.name for loc in baseline_localizers(config))
    raise ValueError(f"no localizer {ref!r} for this robot (available: {known})")


def make_controller(
    spec: ControllerSpec, task, geometry: ChassisGeometry, base_dir: Path
) -> Controller:
    kind = spec.kind or spec.name
    opts = dict(spec.options)
    if ":" in kind:
        return _load_factory(kind, base_dir)(task, geometry, **opts)
    if kind == "move_to_point":
        return MoveToPoint(task.x, task.y, forwards=task.forwards, **opts)
    if kind == "boomerang":
        return Boomerang(task.x, task.y, task.heading, **opts)
    if kind == "turn_pid":
        return TurnToHeading(task.heading, **opts)
    if kind in ("profiled_trapezoid", "profiled_scurve"):
        profile = "trapezoid" if kind == "profiled_trapezoid" else "scurve"
        return ProfiledDrive(task.distance_in, geometry, profile=profile, **opts)
    if kind == "pure_pursuit":
        return PurePursuit(task.waypoints, geometry, **opts)
    if kind == "ramsete":
        gains = {k: opts.pop(k) for k in ("b", "zeta", "lead_s") if k in opts}
        return Ramsete(generate_trajectory(task.waypoints, geometry, **opts), geometry, **gains)
    raise ValueError(f"unknown controller kind {kind!r}")


@dataclass
class TrialResult:
    seed: int
    localizer: str
    controller: str
    metrics: TrialMetrics
    true_start: tuple[float, float, float]
    battery_soc: float
    params: dict[str, float]
    time: np.ndarray = field(repr=False)
    truth: np.ndarray = field(repr=False)
    estimate: np.ndarray = field(repr=False)
    telemetry: Simulation | None = field(default=None, repr=False)

    def row(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "localizer": self.localizer,
            "controller": self.controller,
            **self.metrics.as_dict(),
            "battery_soc": self.battery_soc,
            "true_start_x": self.true_start[0],
            "true_start_y": self.true_start[1],
            "true_start_heading": self.true_start[2],
            **{f"param:{k}": v for k, v in self.params.items()},
        }


def run_trial(
    loaded: LoadedScenario,
    seed: int,
    localizer_ref: str,
    controller: ControllerSpec,
    *,
    record: bool = False,
) -> TrialResult:
    s = loaded.scenario
    rng = RngStreams(seed).stream("bench.randomize")
    base_config = load_robot(loaded.path(s.robot))
    params = {k: float(rng.uniform(lo, hi)) for k, (lo, hi) in s.randomize.params.items()}
    config = base_config.model_copy(update={"overrides": {**base_config.overrides, **params}})
    field_cfg = load_field(loaded.path(s.field)) if s.field else None
    soc = float(rng.uniform(*s.randomize.battery_soc)) if s.randomize.battery_soc else s.battery_soc
    nominal = Pose(s.start.x, s.start.y, s.start.heading)
    dx, dy = rng.normal(0.0, s.randomize.start_xy_in, size=2) if s.randomize.start_xy_in else (0, 0)
    dh = rng.normal(0.0, s.randomize.start_heading_deg) if s.randomize.start_heading_deg else 0.0
    true_start = Pose(nominal.x + dx, nominal.y + dy, nominal.heading + dh)

    localizer = make_localizer(localizer_ref, config, loaded.base_dir)
    geometry = ChassisGeometry.from_config(config)
    ctrl = make_controller(controller, s.task, geometry, loaded.base_dir)
    state: dict[str, Any] = {"done_at": None, "timed_out": False, "energy": 0.0, "peak": 0.0}
    samples: list[tuple] = []

    def autonomous(bot):
        world = bot._sim.world
        t0 = world.time
        _schedule_disturbances(sim, s.disturbances)

        def sample(w):
            truth = Pose.from_si(sim.robot.pose)
            est = sim.estimated_pose
            power = sim.robot.power
            state["energy"] += power.bus_voltage * power.battery_current_a * 0.01
            state["peak"] = max(
                state["peak"], max(m.temperature_c for m in sim.robot.motors.values())
            )
            samples.append(
                (w.time - t0, truth.x, truth.y, truth.heading, est.x, est.y, est.heading)
            )

        handle = world.every(10, sample, priority=PRIORITY_RECORD)
        yield from bot.chassis.run(ctrl, timeout_ms=s.time_limit_s * 1000.0)
        state["timed_out"] = not ctrl.done()
        state["done_at"] = world.time - t0
        remaining = s.settle_window_s
        while remaining > 1e-9:
            yield
            remaining -= 0.01
        handle.cancel()

    sim = Simulation(
        config,
        program=types.SimpleNamespace(autonomous=autonomous),
        field=field_cfg,
        seed=seed,
        noise=s.noise,
        start=true_start,
        believed_start=nominal,
        battery_soc=soc,
        localizer=localizer,
        record=record,
        echo=None,
    )
    sim.start("autonomous")
    calibration = max(
        (d.spec.calibration_s for d in sim.sensors.devices.values() if isinstance(d, ImuDevice)),
        default=0,
    )
    if not sim.run_until_finished(calibration + s.time_limit_s + s.settle_window_s + 5.0):
        raise RuntimeError(f"seed {seed}: trial did not finish")

    data = np.array(samples)
    metrics = score(
        s.task,
        data[:, 0],
        data[:, 1:4],
        data[:, 4:7],
        completion_time_s=state["done_at"],
        timed_out=state["timed_out"],
        energy_j=state["energy"],
        peak_motor_temp_c=state["peak"],
    )
    return TrialResult(
        seed=seed,
        localizer=localizer_ref if ":" in localizer_ref else localizer.name,
        controller=controller.name,
        metrics=metrics,
        true_start=(true_start.x, true_start.y, true_start.heading),
        battery_soc=soc,
        params=params,
        time=data[:, 0],
        truth=data[:, 1:4],
        estimate=data[:, 4:7],
        telemetry=sim if record else None,
    )


def _schedule_disturbances(sim: Simulation, disturbances) -> None:
    world, robot = sim.world, sim.robot

    def at(seconds: float, action) -> None:
        world.after(round(seconds * 1000.0), lambda w: action())

    for d in disturbances:
        if d.type == "push":
            force = np.array(d.force_n, dtype=float)

            def start(force=force):
                robot.external_force = robot.external_force + force

            def stop(force=force):
                robot.external_force = robot.external_force - force

            at(d.at_s, start)
            at(d.at_s + d.duration_s, stop)
        elif d.type == "imu_bias_step":
            imus = [
                dev for dev in sim.sensors.devices.values()
                if isinstance(dev, ImuDevice) and (d.port is None or dev.port == d.port)
            ]  # fmt: skip

            rate = math.radians(d.deg_per_s)

            def step(imus=imus, rate=rate):
                for imu in imus:
                    imu.bias += rate

            at(d.at_s, step)
        elif d.type == "tracking_wheel_liftoff":
            device = sim.sensors.devices.get(d.port)
            if not isinstance(device, RotationDevice):
                raise ValueError(f"tracking_wheel_liftoff: port {d.port} is not a rotation sensor")

            def lift(device=device, duration=d.duration_s):
                device._lifted_until = robot.time + duration

            at(d.at_s, lift)

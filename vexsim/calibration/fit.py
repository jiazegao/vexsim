"""Fitting model parameters to a robot log.

The fit replays the log (replay.py) and compares what the simulated robot
measures with what the real one measured:

  motor velocity   every drive motor (rpm)
  motor current    every drive motor (A)
  tracking wheels  rotation sensor speed (deg/s)
  heading rate     IMU rotation rate (deg/s)

Rates come from 30 ms differences, so absolute drift (which open-loop replays
can't avoid) doesn't dominate. Each residual is divided by a typical error
size, and each of the four groups gets equal total weight however many
sensors it has.

Levenberg-Marquardt minimizes the sum of squares over the logarithms of the
parameters (so they stay positive and steps are relative), with a
finite-difference Jacobian: one replay per parameter, in parallel when
``workers`` > 1. The parameter uncertainty comes from the Jacobian at the
solution.

Some parameters are read directly off the log instead: the battery's internal
resistance is the slope of its voltage against its current.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from vexsim.calibration.log import RobotLog
from vexsim.calibration.replay import AGES_MS, LEADS_MS, at_age, commands_logged, simulate
from vexsim.config.robot import RobotConfig
from vexsim.physics.params import PARAM_GROUPS, check_overrides, resolve_params

RATE_SAMPLES = 3  # rates from differences over 3 samples (30 ms)
STEP = 0.02  # finite-difference step in log-parameter space (2%)
WHEEL_PARAMS = {
    "omni": ("longitudinal_mu", "lateral_mu", "rolling_resistance"),
    "traction": ("mu", "rolling_resistance"),
    "mecanum": ("grip_mu", "roller_mu", "rolling_resistance"),
}
GROUPS = ("motor velocity", "motor current", "tracking wheels", "heading rate")
UNITS = {
    "motor velocity": "rpm",
    "motor current": "A",
    "tracking wheels": "deg/s",
    "heading rate": "deg/s",
}


def default_parameters(config: RobotConfig) -> list[str]:
    """The wheel parameters for every wheel type on the robot."""
    types = sorted({w.type for w in config.drivetrain.wheels})
    return [f"wheel.{t}.{name}" for t in types for name in WHEEL_PARAMS[t]]


def current_value(config: RobotConfig, key: str) -> float:
    """A parameter's value for this robot: its override if it has one, else the default."""
    return resolve_params(config.overrides).value(key)


# --- residuals ---------------------------------------------------------------------------


@dataclass
class Channel:
    group: str
    name: str  # log column
    scale: float  # typical error size, in the group's units
    rate: bool  # compare rates (per second) instead of values
    factor: float = 1.0  # unit conversion of the logged value


def channels(config: RobotConfig, log: RobotLog) -> list[Channel]:
    out = []
    rpm = {abs(p): g.motor_free_rpm for g in config.drivetrain.gearing.values() for p in g.motors}
    for port in log.ports("m"):
        if port in rpm and f"m{port}_rpm" in log:
            out.append(Channel("motor velocity", f"m{port}_rpm", 0.01 * rpm[port], False))
            out.append(Channel("motor current", f"m{port}_ma", 0.1, False, 1e-3))
    for port in log.ports("r"):
        out.append(Channel("tracking wheels", f"r{port}_cdeg", 20.0, True, 0.01))
    for port in log.ports("imu"):
        out.append(Channel("heading rate", f"imu{port}_deg", 5.0, True))
    return out


def signal_of(log: RobotLog, ch: Channel) -> np.ndarray:
    values = log[ch.name] * ch.factor
    if not ch.rate:
        return values
    dt = (log.time_ms[RATE_SAMPLES:] - log.time_ms[:-RATE_SAMPLES]) / 1000.0
    return (values[RATE_SAMPLES:] - values[:-RATE_SAMPLES]) / dt


def residuals(real: RobotLog, sim: RobotLog, chans: Sequence[Channel]) -> np.ndarray:
    counts = {g: sum(c.group == g for c in chans) for g in GROUPS}
    parts = []
    for ch in chans:
        if ch.name not in sim:
            continue
        diff = signal_of(sim, ch) - signal_of(real, ch)
        diff = np.where(np.isfinite(diff), diff, 0.0)
        weight = 1.0 / (ch.scale * math.sqrt(counts[ch.group] * len(diff)))
        parts.append(diff * weight)
    return np.concatenate(parts) if parts else np.zeros(0)


def rms_by_group(real: RobotLog, sim: RobotLog, chans: Sequence[Channel]) -> dict[str, float]:
    """RMS difference per group, in the group's units."""
    out = {}
    for group in GROUPS:
        diffs = [
            signal_of(sim, c) - signal_of(real, c)
            for c in chans
            if c.group == group and c.name in sim
        ]
        if diffs:
            d = np.concatenate(diffs)
            d = d[np.isfinite(d)]
            out[group] = float(np.sqrt(np.mean(d**2))) if len(d) else math.nan
    return out


def best_age(log: RobotLog, states: RobotLog, chans: Sequence[Channel]) -> int:
    """How old (ms) the log's readings are, judged by which age fits the replay best.

    Motor current jumps the moment a command changes, whatever the wheel
    parameters, so it shows the timing even before the fit; other readings
    are used only when the log has no currents.
    """
    timing = [c for c in chans if c.group == "motor current"] or list(chans)
    costs = []
    for age in AGES_MS:
        r = residuals(log, at_age(states, log, age), timing)
        costs.append(float(r @ r))
    return AGES_MS[int(np.argmin(costs))]


def timing(
    config: RobotConfig, log: RobotLog, overrides: dict[str, float], chans: Sequence[Channel]
) -> tuple[int, int, RobotLog]:
    """(lead, age, states): when measured voltages stand in for commands, also how much
    earlier they were applied (one replay per candidate lead)."""
    leads = [0] if commands_logged(log) else list(LEADS_MS)
    best = None
    for lead in leads:
        states = simulate(config, log, overrides, lead)
        age = best_age(log, states, chans)
        r = residuals(log, at_age(states, log, age), chans)
        cost = float(r @ r)
        if best is None or cost < best[0]:
            best = (cost, lead, age, states)
    return best[1], best[2], best[3]


# --- direct estimates ------------------------------------------------------------------------


def battery_resistance(log: RobotLog) -> float | None:
    """Internal resistance (ohm) from the slope of voltage against current, if the log
    has enough current variation to tell (at least 2 A spread)."""
    if "battery_mv" not in log or "battery_ma" not in log:
        return None
    v, i = log["battery_mv"] / 1000.0, log["battery_ma"] / 1000.0
    ok = np.isfinite(v) & np.isfinite(i)
    if ok.sum() < 20 or np.ptp(i[ok]) < 2.0:
        return None
    slope = np.polyfit(i[ok], v[ok], 1)[0]
    return float(-slope) if slope < 0 else None


# --- the fit ------------------------------------------------------------------------------


@dataclass
class FitResult:
    parameters: list[str]
    before: dict[str, float]
    after: dict[str, float]
    uncertainty: dict[str, float]  # one standard deviation, as a fraction of the value
    rms_before: dict[str, float]
    rms_after: dict[str, float]
    iterations: int
    replays: int
    age_ms: int  # how old the log's readings were when the code read them
    lead_ms: int  # measured voltages applied this much before their rows
    direct: dict[str, float] = field(default_factory=dict)  # read off the log
    sim_before: RobotLog | None = None
    sim_after: RobotLog | None = None

    @property
    def overrides(self) -> dict[str, float]:
        """Every fitted value, ready for a robot config's ``overrides``."""
        return {**self.after, **self.direct}


def _simulate_job(args: tuple[RobotConfig, RobotLog, dict[str, float], int]) -> RobotLog:
    config, log, overrides, lead = args
    return simulate(config, log, overrides, lead)


def fit(
    config: RobotConfig,
    log: RobotLog,
    parameters: Sequence[str] | None = None,
    *,
    max_iterations: int = 12,
    workers: int = 1,
    progress: Callable[[str], None] | None = None,
) -> FitResult:
    """Fit ``parameters`` (dotted override keys; default: the wheel parameters) to the log."""
    names = list(default_parameters(config) if parameters is None else parameters)
    problems = [f"{k}: {m}" for s, k, m in check_overrides({n: 1.0 for n in names}) if s == "error"]
    if problems:
        raise ValueError("can't fit " + "; ".join(problems))
    for name in names:
        if name.rpartition(".")[0] not in PARAM_GROUPS or name.startswith("sensor."):
            raise ValueError(f"can't fit {name}: only physics parameters can be fitted")
    say = progress or (lambda text: None)
    chans = channels(config, log)
    if not chans:
        raise ValueError("the log has no drive motor, rotation sensor or IMU readings to compare")
    direct = {}
    resistance = battery_resistance(log)
    if resistance is not None:
        direct["battery.internal_resistance_ohm"] = round(resistance, 4)
    base = {**config.overrides, **direct}
    config = config.model_copy(update={"overrides": base})
    start = np.log([current_value(config, n) for n in names])
    lower, upper = start - math.log(20.0), start + math.log(20.0)
    pool = ProcessPoolExecutor(workers) if workers > 1 and names else None
    count = 0
    age = 10
    lead = 0

    def states_at(thetas: list[np.ndarray]) -> list[RobotLog]:
        nonlocal count
        jobs = [
            (config, log, dict(zip(names, np.exp(t).tolist(), strict=True)), lead) for t in thetas
        ]
        count += len(jobs)
        return (
            [_simulate_job(j) for j in jobs]
            if pool is None
            else list(pool.map(_simulate_job, jobs))
        )

    try:
        theta = start.copy()
        lead, age, states = timing(
            config, log, dict(zip(names, np.exp(theta).tolist(), strict=True)), chans
        )
        count += 1 if commands_logged(log) else len(LEADS_MS)
        if commands_logged(log):
            say(f"timing: the log's readings are {age} ms old")
        else:
            say(f"timing: readings {age} ms old; replaying measured voltages {lead} ms early")
        sim = sim_before = at_age(states, log, age)
        r = residuals(log, sim, chans)
        cost = float(r @ r)
        say(f"start: cost {cost:.4g}")
        damping, iterations = 1e-2, 0
        jac = np.zeros((len(r), len(names)))
        for iterations in range(1, max_iterations + 1):
            if not names:
                break
            probes = [theta + STEP * np.eye(len(names))[i] for i in range(len(names))]
            for i, probe in enumerate(states_at(probes)):
                jac[:, i] = (residuals(log, at_age(probe, log, age), chans) - r) / STEP
            jtj, jtr = jac.T @ jac, jac.T @ r
            improved = False
            for _ in range(8):
                a = jtj + damping * np.diag(np.maximum(np.diag(jtj), 1e-12))
                candidate = np.clip(theta - np.linalg.solve(a, jtr), lower, upper)
                trial_states = states_at([candidate])[0]
                trial_r = residuals(log, at_age(trial_states, log, age), chans)
                trial_cost = float(trial_r @ trial_r)
                if trial_cost < cost:
                    step = np.abs(candidate - theta).max()
                    gain = (cost - trial_cost) / cost
                    theta, states, r, cost = candidate, trial_states, trial_r, trial_cost
                    damping, improved = max(damping / 3, 1e-6), True
                    break
                damping *= 4
            values = ", ".join(
                f"{n.rsplit('.', 1)[1]} {v:.4g}" for n, v in zip(names, np.exp(theta), strict=True)
            )
            say(f"iteration {iterations}: cost {cost:.4g} ({values})")
            converged = not improved or gain < 1e-4 or step < 1e-4
            if converged:
                # The timing was judged with the starting parameters; check it with the fit's.
                new_age = best_age(log, states, chans)
                if new_age == age:
                    break
                age = new_age
                say(f"timing: the log's readings are {age} ms old")
                r = residuals(log, at_age(states, log, age), chans)
                cost = float(r @ r)
        sim = at_age(states, log, age)
    finally:
        if pool is not None:
            pool.shutdown()

    dof = max(len(r) - len(names), 1)
    sigma2 = cost / dof
    try:
        cov = np.linalg.inv(jac.T @ jac) * sigma2 if names else np.zeros((0, 0))
        spread = np.sqrt(np.maximum(np.diag(cov), 0.0))
    except np.linalg.LinAlgError:
        spread = np.full(len(names), math.inf)
    return FitResult(
        parameters=names,
        before=dict(zip(names, np.exp(start).tolist(), strict=True)),
        after={n: float(f"{v:.4g}") for n, v in zip(names, np.exp(theta), strict=True)},
        uncertainty=dict(zip(names, spread.tolist(), strict=True)),
        rms_before=rms_by_group(log, sim_before, chans),
        rms_after=rms_by_group(log, sim, chans),
        iterations=iterations,
        replays=count,
        age_ms=age,
        lead_ms=lead,
        direct=direct,
        sim_before=sim_before,
        sim_after=sim,
    )


def compare(
    config: RobotConfig, log: RobotLog, overrides: dict[str, float] | None = None
) -> tuple[dict[str, float], RobotLog]:
    """Replay a log without fitting: RMS differences per group, and the simulated log."""
    chans = channels(config, log)
    _, age, states = timing(config, log, overrides or {}, chans)
    sim = at_age(states, log, age)
    return rms_by_group(log, sim, chans), sim


def worker_count(requested: int | None) -> int:
    return requested if requested and requested > 0 else min(8, os.cpu_count() or 1)

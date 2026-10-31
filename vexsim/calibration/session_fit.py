"""Fitting a calibration session (phase 14.4): each test's logs, into what that test measures.

``calibrate(config, session, field)`` fits them in an order where each fit uses the values
the ones before found (``vexsim calibrate ROBOT.yaml SESSION``):

  device check    must have passed: a failed one stops it, saying what to fix
  free spin       the motors: natural_free_rpm, free_current_a, coulomb_fraction and the
                  velocity loop's kp, with the robot lifted (on its side), so nothing but the
                  motors and gears load them; whether voltage commands are capped at rated
                  speed (a capped motor runs no faster at 12 V than at its rated speed); how
                  noisy the motors' speed readings are
  IMU             its scale error from the 10 turns each way; its noise and drift from the
                  still log (Allan variance)
  push            the drive wheels' diameters (and the tracking wheels' that roll along):
                  the push replayed, a hand moving the simulated robot as the log's wheels
                  say it went, until its wheels turn as far as the real ones did (coasting
                  motors drag, so wheels creep a little: a plain ratio would be off by that)
  tracking wheels where each is, from the slow spin: its travel per turn, against the
                  replay's for where the config says it is
  drive           the wheels' friction and rolling resistance, from every driving run at once
                  but one, held out to check the result; the battery's resistance
  again           the push, the tracking wheels and the drive, with the friction found: how
                  much the wheels creep depends on it
  distance        the sensors' noise, range, misses at glancing angles and confidence, from
                  the sweeps, against what each should have read from where it was
  drive model     kS, kV, kA and kT for vexsim's own motions, from the driving runs

Each step's ``Step`` says what it found (before and after), how sure it is (``pinned``: the
logs pin a value down when its uncertainty is under its tolerance), and what to look at.
"""

from __future__ import annotations

import math
import types
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from vexsim.calibration import feedforward
from vexsim.calibration.fit import (
    FitResult,
    channels,
    compare,
    current_value,
    default_parameters,
    fit_logs,
    rms_by_group,
)
from vexsim.calibration.log import RobotLog
from vexsim.calibration.replay import at_age, simulate
from vexsim.calibration.routine import DRIVE_TESTS
from vexsim.calibration.session import Run, Session
from vexsim.config.field import FieldConfig
from vexsim.config.robot import RobotConfig
from vexsim.devices.devices import DistanceDevice
from vexsim.devices.specs import sensor_spec
from vexsim.physics.arena import Arena
from vexsim.physics.motor import BrakeMode
from vexsim.physics.params import resolve_params
from vexsim.physics.robot import Robot
from vexsim.physics.world import World
from vexsim.units import in_to_m

Say = Callable[[str], None]

HAND_GAINS = (200.0, 28.0)  # a hand pushing the replayed robot: 1/s^2, 1/s
FREE_SPIN = (
    "motor.natural_free_rpm",
    "motor.free_current_a",
    "motor.coulomb_fraction",
    "motor.velocity_kp",
)
CAPPED = 1.25  # 12 V's steady speed over 9 V's: about 1.34 for a free motor, 1.18 if capped
TOLERANCE = {  # how well a value must be known to count as pinned down, as a fraction of it
    "motor.natural_free_rpm": 0.01,
    "motor.free_current_a": 0.1,
    "motor.coulomb_fraction": 0.1,
    "motor.velocity_kp": 0.1,
    "sensor.motor.velocity_noise": 0.2,
    "battery.internal_resistance_ohm": 0.1,
    "sensor.imu.heading_noise_deg": 0.2,
    "sensor.imu.rate_noise_deg_s": 0.25,
    "sensor.imu.bias_walk_deg_s": 0.5,
    "sensor.distance.long_noise_fraction": 0.2,
    "sensor.distance.short_noise_mm": 0.25,
    "sensor.distance.confidence_per_m": 0.15,
    "sensor.distance.confidence_per_deg": 0.15,
    "wheel": 0.05,  # each wheel parameter
    "diameter_in": 0.005,
}
TOLERANCE_OF = {  # in the value's units
    "scale_error": 0.0005,
    "pos_in": 0.1,
    "motor.voltage_cap": 0.02,
    "sensor.distance.max_range_mm": 100.0,
    "sensor.distance.glancing_miss": 0.1,
    "sensor.distance.glancing_deg": 5.0,
    "sensor.distance.glancing_mm": 250.0,
}
TURN_LINEUP_DEG = 1.0  # how well a robot turned by hand lines up on its tape again
NOISE_MARGIN = 1.5  # a held-out run matches if each group is within this many times its noise
SQUARE_DEG = 30.0  # beams this close to square never miss for being glancing
NOISE_DEG = 40.0  # nor do their readings curve much from one to the next
FEW = 30  # fewer samples than this tell nothing
INSIDE_DEG, INSIDE_MM = 7.5, 150.0  # well inside where beams glance off: how far past


class SessionError(Exception):
    """The session can't be fitted (the message says what to do)."""


@dataclass
class Value:
    """One value a step found: where it goes, before and after, how sure."""

    key: str  # an override key, or a config field (wheels.left.diameter_in, sensors.16.scale_error)
    before: float
    after: float
    uncertainty: float = math.nan  # one standard deviation, in the value's units
    tolerance: float = math.nan  # how close it must be known to count as pinned down
    note: str = ""

    @property
    def pinned(self) -> bool:
        return math.isfinite(self.uncertainty) and self.uncertainty <= self.tolerance


@dataclass
class Step:
    """What one step of the fit found."""

    name: str
    values: list[Value] = field(default_factory=list)
    rms: dict[str, tuple[float, float]] = field(default_factory=dict)  # group: (before, after)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)  # the logs it used
    skipped: str = ""  # why it didn't run, if it didn't
    replays: list[tuple[str, RobotLog, RobotLog | None, RobotLog | None]] = field(
        default_factory=list
    )  # for plots: a title, a log, its replay before the fit and after
    readings: dict[int, Readings] = field(default_factory=dict)  # the distance sweeps'

    def value(self, key: str) -> Value | None:
        return next((v for v in self.values if v.key == key), None)


def _quiet(text: str) -> None:
    pass


def with_overrides(config: RobotConfig, values: dict[str, float]) -> RobotConfig:
    return config.model_copy(update={"overrides": {**config.overrides, **values}})


def _relative(key: str, value: float) -> float:
    """A key's tolerance, in its units."""
    if key in TOLERANCE_OF:
        return TOLERANCE_OF[key]
    if key in TOLERANCE:
        return TOLERANCE[key] * abs(value)
    if key.startswith("wheel."):
        return TOLERANCE["wheel"] * abs(value)
    return math.nan


def _fitted_values(result: FitResult, config: RobotConfig) -> list[Value]:
    """A least-squares fit's values, with their uncertainty in their own units."""
    return [
        Value(
            name,
            current_value(config, name),
            result.after[name],
            result.uncertainty[name] * result.after[name],
            _relative(name, result.after[name]),
        )
        for name in result.parameters
    ]


def as_configured(
    config: RobotConfig, logs: Sequence[RobotLog], *, lifted: bool = False
) -> FitResult:
    """The logs replayed with the config as it is (nothing fitted): the RMS difference of each
    group (``rms_after``), and the replays."""
    return fit_logs(config, logs, [], lifted=[lifted] * len(logs))


def _name(run: Run | None, log: RobotLog) -> str:
    return run.file if run is not None else log.info.get("name", "log")


# --- the device check -------------------------------------------------------------------------


def device_check(session: Session) -> tuple[Run, list[str]]:
    """The session's last device check and what it says to fix (nothing if it passed).
    Raises SessionError when there's none."""
    checks = session.logs("device_check", used=False)
    if not checks:
        raise SessionError(
            "the session has no device check: run test 1 (Device check) and collect its log"
        )
    run, log = checks[-1]
    if log.info.get("check") == "passed" and run.ended == "finished":
        return run, []
    problems = [text.removeprefix("to fix: ") for _, text in log.marks if text.startswith("to fix")]
    if not problems:
        problems = [f"the device check {run.ended if run.ended != 'finished' else 'failed'}"]
    return run, problems


# --- the free spin: the motors ----------------------------------------------------------------


def drive_ports(config: RobotConfig) -> dict[str, list[int]]:
    """Each drive group's motor ports (raw)."""
    return {name: [abs(p) for p in g.motors] for name, g in config.drivetrain.gearing.items()}


def rated_rpm(config: RobotConfig) -> dict[int, float]:
    """Each drive motor's rated speed (rpm), by its (raw) port."""
    return {abs(p): g.motor_free_rpm for g in config.drivetrain.gearing.values() for p in g.motors}


def stretches(log: RobotLog) -> list[tuple[str, np.ndarray]]:
    """Each marked stretch of a log: its mark's text and its rows (a mask)."""
    t = log.time_ms
    marks = sorted(log.marks)
    out = []
    for k, (at, text) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else t[-1] + 1
        out.append((text, (t >= at) & (t < end)))
    return out


def steady_speeds(config: RobotConfig, log: RobotLog, last_ms: float = 500.0) -> dict[str, float]:
    """Each stretch's steady speed: the drive motors' mean speed over its last ``last_ms``, as
    a fraction of their rated speed."""
    rated = rated_rpm(config)
    t = log.time_ms
    out = {}
    for text, rows in stretches(log):
        if not rows.any():
            continue
        end = t[rows][-1]
        tail = rows & (t > end - last_ms)
        speeds = [
            np.abs(log[f"m{p}_rpm"][tail]) / r for p, r in rated.items() if f"m{p}_rpm" in log
        ]
        if speeds:
            out[text] = float(np.nanmean(np.concatenate(speeds)))
    return out


def velocity_noise(config: RobotConfig, log: RobotLog) -> tuple[float, float] | None:
    """How noisy the drive motors' speed readings are (a fraction of rated speed), and how
    well that's known: their spread while the free spin holds each voltage steady."""
    rated = rated_rpm(config)
    t = log.time_ms
    spreads = []
    for text, rows in stretches(log):
        if not text.endswith(" V") or not rows.any():
            continue
        end = t[rows][-1]
        tail = rows & (t > end - 800.0)
        for p, r in rated.items():
            if f"m{p}_rpm" not in log:
                continue
            values = log[f"m{p}_rpm"][tail]
            values = values[np.isfinite(values)]
            if len(values) > 10:
                k = np.arange(len(values))
                trend = np.polyval(np.polyfit(k, values, 1), k)  # what's left of settling
                spreads.append(np.std(values - trend) / r)
    if not spreads:
        return None
    spread = 1.25 * float(np.std(spreads)) / math.sqrt(len(spreads))  # a median's
    return float(np.median(spreads)), spread


def voltage_cap(config: RobotConfig, log: RobotLog) -> tuple[float | None, str]:
    """Whether the free spin's voltage commands were held to rated speed: the cap (a fraction
    of rated speed, 0 for none; None if the log can't tell) and what showed it."""
    speeds = steady_speeds(config, log)
    v9, v12 = speeds.get("9 V"), speeds.get("12 V")
    if not v9 or not v12:
        return None, "the free spin has no steady 9 V and 12 V: the cap stays as it is"
    ratio = v12 / v9
    if ratio < CAPPED and v12 < 1.05:
        cap = round(v12, 2)
        return cap, (
            f"at 12 V the motors ran at {v12:.0%} of their rated speed, only {ratio:.2f} times "
            f"their 9 V speed: voltage commands are held to rated speed (motor.voltage_cap {cap:g})"
        )
    return 0.0, (
        f"at 12 V the motors ran at {v12:.0%} of their rated speed, {ratio:.2f} times their 9 V "
        "speed: voltage commands aren't capped"
    )


def fit_free_spin(
    config: RobotConfig,
    log: RobotLog,
    *,
    run: Run | None = None,
    workers: int = 1,
    say: Say = _quiet,
) -> tuple[dict[str, float], Step]:
    """The motors' parameters from the free spin (the robot on its side): the overrides, and
    the step."""
    step = Step("Free spin: the motors", runs=[_name(run, log)])
    cap, note = voltage_cap(config, log)
    step.notes.append(note)
    before_cap = current_value(config, "motor.voltage_cap")
    found: dict[str, float] = {}
    if cap is not None:
        found["motor.voltage_cap"] = cap
        step.values.append(
            Value("motor.voltage_cap", before_cap, cap, 0.0, TOLERANCE_OF["motor.voltage_cap"])
        )
    say("free spin: fitting the motors")
    trial = with_overrides(config, found)
    result = fit_logs(trial, [log], FREE_SPIN, workers=workers, progress=say, lifted=[True])
    found.update(result.after)
    step.values += _fitted_values(result, config)
    before = as_configured(config, [log], lifted=True)
    step.rms = {g: (before.rms_after.get(g, math.nan), v) for g, v in result.rms_after.items()}
    step.replays.append((_name(run, log), log, before.sim_after, result.sim_after))
    noise = velocity_noise(config, log)
    if noise is not None:
        key, (value, sigma) = "sensor.motor.velocity_noise", noise
        motors = resolve_params(config.overrides).sensor_overrides.get("motor")
        configured = sensor_spec("motor", "default", motors).velocity_noise
        found[key] = round(value, 5)
        step.values.append(Value(key, configured, found[key], sigma, _relative(key, value)))
    step.notes.append(
        "velocity_ki isn't fitted: a free spin can't tell it (it acts only under a changing load)"
    )
    return found, step


# --- the IMU ----------------------------------------------------------------------------------


def imu_ports(config: RobotConfig) -> list[int]:
    return [s.port for s in config.sensors if s.type == "imu"]


def _turned(log: RobotLog, port: int) -> float | None:
    column = f"imu{port}_deg"
    if column not in log:
        return None
    known = log[column][np.isfinite(log[column])]
    return float(known[-1] - known[0]) if len(known) > 1 else None


def allan(theta: np.ndarray, dt: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The overlapping Allan variance of a rate from its integral ``theta`` (sampled every
    ``dt`` s): the cluster times (s), the variances, and about how many independent clusters
    each has."""
    n = len(theta)
    sizes = np.unique(np.round(np.logspace(0, math.log10(max(n // 4, 2)), 40)).astype(int))
    taus, values, counts = [], [], []
    for m in sizes:
        if 2 * m >= n:
            break
        d = theta[2 * m :] - 2 * theta[m:-m] + theta[: -2 * m]
        taus.append(m * dt)
        values.append(float(np.mean(d**2)) / (2 * (m * dt) ** 2))
        counts.append(max((n - 2 * m) / m, 1.0))
    return np.array(taus), np.array(values), np.array(counts)


def imu_noise(theta: np.ndarray, dt: float, period_s: float) -> dict[str, tuple[float, float]]:
    """An IMU's noise from its rotation (deg) standing still, sampled every ``dt`` s:
    heading_noise_deg (each reading's), rate_noise_deg_s (each of its samples' rate, every
    ``period_s``) and bias_walk_deg_s (per root second), each with its uncertainty. The Allan
    variance of its rate is 3 h^2/tau^2 + r^2 T/tau + b^2 tau/3 for those three."""
    theta = theta[np.isfinite(theta)]
    taus, avar, counts = allan(theta, dt)
    keep = avar > 0
    taus, avar, counts = taus[keep], avar[keep], counts[keep]
    basis = np.column_stack([1 / taus**2, 1 / taus, taus])
    weight = np.sqrt(counts) / avar  # each variance is known to about 1/sqrt(clusters)
    a, w = basis * weight[:, None], np.ones(len(avar)) * np.sqrt(counts)
    best = None
    for subset in ((0, 1, 2), (0, 1), (0, 2), (1, 2), (0,), (1,), (2,)):
        cols = list(subset)
        coef, *_ = np.linalg.lstsq(a[:, cols], w, rcond=None)
        if (coef < 0).any():
            continue
        full = np.zeros(3)
        full[cols] = coef
        cost = float(np.sum((a @ full - w) ** 2))
        if best is None or cost < best[0]:
            best = (cost, full, cols)
    _, coef, cols = best
    spread = np.full(3, math.inf)
    try:  # neighbouring clusters overlap, so the variances aren't independent: x3
        cov = np.linalg.inv(a[:, cols].T @ a[:, cols]) * 9.0
        spread[cols] = np.sqrt(np.maximum(np.diag(cov), 0.0))
    except np.linalg.LinAlgError:
        pass
    h2, r2t, b2 = coef  # 3 h^2, r^2 T, b^2 / 3

    def root(value: float, sigma: float, scale: float) -> tuple[float, float]:
        if value <= 0:
            return 0.0, math.sqrt(max(sigma, 0.0) * scale) if math.isfinite(sigma) else math.inf
        found = math.sqrt(value * scale)
        return found, 0.5 * found * sigma / value

    return {
        "sensor.imu.heading_noise_deg": root(h2, spread[0], 1 / 3),
        "sensor.imu.rate_noise_deg_s": root(r2t, spread[1], 1 / period_s),
        "sensor.imu.bias_walk_deg_s": root(b2, spread[2], 3.0),
    }


def fit_imu(
    config: RobotConfig,
    still: Sequence[tuple[Run, RobotLog]],
    turns: Sequence[tuple[Run, RobotLog]],
) -> tuple[dict[int, float], dict[str, float], Step]:
    """Each IMU's scale error (by port) from the turns by hand, and the IMUs' noise (overrides)
    from the still log."""
    step = Step("IMU: scale error, noise and drift")
    step.runs = [r.file for r, _ in [*still, *turns]]
    scales: dict[int, float] = {}
    found: dict[str, float] = {}
    imus = [s for s in config.sensors if s.type == "imu"]
    for sensor in imus:
        port = sensor.port
        readings = []
        for run, log in turns:
            turned = _turned(log, port)
            if turned is None:
                continue
            n = float(log.info.get("turns") or 10)
            readings.append((log.info.get("direction", run.name), abs(turned) / (360 * n) - 1))
        if not readings:
            continue
        values = np.array([v for _, v in readings])
        scale = float(values.mean())
        spread = float(values.std(ddof=1)) / math.sqrt(len(values)) if len(values) > 1 else 0.0
        lineup = TURN_LINEUP_DEG / (3600 * math.sqrt(len(values)))
        scales[port] = round(scale, 5)
        before = sensor.scale_error if sensor.scale_error is not None else math.nan
        step.values.append(
            Value(
                f"sensors.{port}.scale_error",
                before,
                round(scale, 5),
                max(spread, lineup),
                TOLERANCE_OF["scale_error"],
                note=", ".join(f"{way}: {v:+.3%}" for way, v in readings),
            )
        )
        if len(values) > 1 and np.ptp(values) > 0.003:
            step.warnings.append(
                f"IMU {port} reads {np.ptp(values):.2%} more one way than the other: "
                "were both 10 full turns, lined up on the tape?"
            )
    period = sensor_spec("imu").period_ms / 1000.0
    noises: dict[str, list[tuple[float, float]]] = {}
    for _, log in still:
        dt = float(np.median(np.diff(log.time_ms))) / 1000.0
        for port in [s.port for s in imus if f"imu{s.port}_deg" in log]:
            for key, pair in imu_noise(log[f"imu{port}_deg"], dt, period).items():
                noises.setdefault(key, []).append(pair)
            drift = _turned(log, port) or 0.0
            seconds = (log.time_ms[-1] - log.time_ms[0]) / 1000.0
            step.notes.append(
                f"IMU {port} drifted {drift:+.2f} deg in {seconds:.0f} s standing still"
            )
    params = resolve_params(config.overrides)
    spec = sensor_spec("imu", "default", params.sensor_overrides.get("imu"))
    for key, pairs in noises.items():
        value = float(np.mean([v for v, _ in pairs]))
        sigma = float(np.mean([s for _, s in pairs])) / math.sqrt(len(pairs))
        before = getattr(spec, key.rsplit(".", 1)[1])
        found[key] = float(f"{value:.3g}")
        step.values.append(Value(key, before, found[key], sigma, _relative(key, value)))
    if not still:
        step.notes.append("no still log: the IMU's noise stays as it is")
    return scales, found, step


def with_imu_scales(config: RobotConfig, scales: dict[int, float]) -> RobotConfig:
    sensors = tuple(
        s.model_copy(update={"scale_error": scales[s.port]})
        if s.type == "imu" and s.port in scales
        else s
        for s in config.sensors
    )
    return config.model_copy(update={"sensors": sensors})


# --- the push: wheel diameters ----------------------------------------------------------------


def _travel(log: RobotLog, ports: Sequence[int]) -> np.ndarray:
    """How far the motors have turned since the log began (deg, each row, mean of |change|)."""
    columns = [log[f"m{p}_deg"] for p in ports if f"m{p}_deg" in log]
    moved = [np.abs(c - c[np.isfinite(c)][0]) for c in columns if np.isfinite(c).any()]
    return np.nanmean(moved, axis=0) if moved else np.zeros(len(log))


def push_replay(
    config: RobotConfig, log: RobotLog, length_in: float, sign: float
) -> dict[int, float]:
    """The push replayed: the simulated robot, its motors coasting, pushed straight ahead
    (``sign`` 1) or back (-1) by ``length_in``, as fast at each moment as the log's wheels say
    the real one went. How far each drive motor turned (deg)."""
    ports = [p for group in drive_ports(config).values() for p in group]
    travel = _travel(log, ports)
    if travel[-1] <= 0:
        raise SessionError("the push log's wheels didn't turn")
    times, rows = np.unique((log.time_ms - log.time_ms[0]) / 1000.0, return_index=True)
    progress = travel[rows] / travel[-1]
    world = World(seed=0)
    robot = world.add_system(Robot(config, params=resolve_params(config.overrides)))
    for motor in robot.motors.values():
        motor.brake_mode = BrakeMode.COAST
        motor.stop()
    start = {p: robot.motors[p].position for p in ports}
    meters = in_to_m(length_in) * sign
    kp, kd = HAND_GAINS
    rate = np.gradient(progress, times) if len(times) > 2 else np.zeros(len(times))

    def hand(w: World) -> None:
        t = w.time - t0
        x_t = meters * float(np.interp(t, times, progress))
        v_t = meters * float(np.interp(t, times, rate))
        x, y, h = robot.pose
        vx, vy = robot.field_velocity
        robot.external_force = robot.mass * np.array(
            [kp * (x_t - x) + kd * (v_t - vx), kp * (0.0 - y) + kd * (0.0 - vy)]
        )
        robot.external_torque = robot.yaw_inertia * (kp * (0.0 - h) - kd * robot.body_velocity[2])

    t0 = world.time
    world.every(1, hand, name="hand")
    world.run_for(float(times[-1]) + 0.5)
    return {p: abs(math.degrees(robot.motors[p].position - start[p])) for p in ports}


def with_diameters(config: RobotConfig, diameters: dict[str, float]) -> RobotConfig:
    """The config with each drive group's wheels at its diameter (in)."""
    of_wheel = {
        w: diameters[g]
        for g, gear in config.drivetrain.gearing.items()
        if g in diameters
        for w in gear.wheels
    }
    wheels = tuple(
        w.model_copy(update={"diameter_in": of_wheel[w.name]}) if w.name in of_wheel else w
        for w in config.drivetrain.wheels
    )
    return config.model_copy(
        update={"drivetrain": config.drivetrain.model_copy(update={"wheels": wheels})}
    )


def with_tracking(config: RobotConfig, tracking: dict[int, dict]) -> RobotConfig:
    """The config with its tracking wheels' fields changed (by port: diameter_in, pos_in)."""
    sensors = []
    for s in config.sensors:
        if s.type == "rotation" and s.tracking_wheel is not None and s.port in tracking:
            wheel = s.tracking_wheel.model_copy(update=tracking[s.port])
            s = s.model_copy(update={"tracking_wheel": wheel})
        sensors.append(s)
    return config.model_copy(update={"sensors": tuple(sensors)})


def fit_push(
    config: RobotConfig,
    pushes: Sequence[tuple[Run, RobotLog]],
    *,
    original: RobotConfig | None = None,
    say: Say = _quiet,
) -> tuple[dict[str, float], dict[int, float], Step]:
    """Each drive group's wheel diameter (in), and each tracking wheel's that rolls along the
    push (by port), from the push logs (each says its length and which way). ``original``:
    the config as it was, for the step's before."""
    original = original or config
    groups = drive_ports(config)
    first = {
        g: original.drivetrain.wheel(gear.wheels[0]).diameter_in
        for g, gear in config.drivetrain.gearing.items()
    }
    diameters = {
        g: config.drivetrain.wheel(gear.wheels[0]).diameter_in
        for g, gear in config.drivetrain.gearing.items()
    }
    logs = [
        (log, float(log.info["length_in"]), -1.0 if log.info.get("direction") == "back" else 1.0)
        for _, log in pushes
    ]
    logged = [
        {p: _travel(log, [p])[-1] for ports in groups.values() for p in ports} for log, _, _ in logs
    ]
    estimates: dict[str, list[float]] = {}
    for _ in range(3):  # the travel goes as 1/diameter: a few rounds settle it
        trial = with_diameters(config, diameters)
        found: dict[str, list[float]] = {g: [] for g in groups}
        for (log, length, sign), real in zip(logs, logged, strict=True):
            simulated = push_replay(trial, log, length, sign)
            for g, ports in groups.items():
                ratio = np.mean([simulated[p] / real[p] for p in ports if real[p] > 0])
                found[g].append(diameters[g] * float(ratio))
        estimates = found
        diameters = {g: float(np.mean(v)) for g, v in found.items()}
    step = Step("Push: wheel diameters", runs=[r.file for r, _ in pushes])
    for g, values in estimates.items():
        spread = float(np.std(values, ddof=1)) / math.sqrt(len(values)) if len(values) > 1 else 0
        step.values.append(
            Value(
                f"wheels.{g}.diameter_in",
                first[g],
                round(diameters[g], 4),
                spread,
                TOLERANCE["diameter_in"] * first[g],
            )
        )
    tracking = {}
    for sensor in config.sensors:
        if sensor.type != "rotation" or sensor.tracking_wheel is None:
            continue
        along = math.cos(math.radians(sensor.tracking_wheel.heading_deg))
        if abs(along) < 0.7 or f"r{sensor.port}_cdeg" not in logs[0][0]:
            continue  # it rolls across the push: its diameter isn't measured here
        found_d = []
        for log, length, _ in logs:
            cdeg = log[f"r{sensor.port}_cdeg"]
            known = cdeg[np.isfinite(cdeg)]
            turns = abs(known[-1] - known[0]) / 36000.0
            if turns > 0:
                found_d.append(length * abs(along) / (math.pi * turns))
        if found_d:
            d = float(np.mean(found_d))
            tracking[sensor.port] = round(d, 4)
            before = next(
                s.tracking_wheel.diameter_in for s in original.sensors if s.port == sensor.port
            )
            spread = (
                float(np.std(found_d, ddof=1)) / math.sqrt(len(found_d)) if len(found_d) > 1 else 0
            )
            step.values.append(
                Value(
                    f"sensors.{sensor.port}.tracking_wheel.diameter_in",
                    before,
                    round(d, 4),
                    spread,
                    TOLERANCE["diameter_in"] * before,
                )
            )
    if len(estimates) and all(len(v) < 2 for v in estimates.values()):
        step.notes.append("one push: push it both ways to know how well the diameters are known")
    say("push: " + ", ".join(f"{v.key} {v.before:g} -> {v.after:g}" for v in step.values))
    return {g: round(d, 4) for g, d in diameters.items()}, tracking, step


# --- the drive --------------------------------------------------------------------------------


@dataclass
class HeldOut:
    """The driving run the fit left out, replayed with what it found."""

    run: str
    rms: dict[str, float]  # by group, simulated against logged
    noise: dict[str, float]  # each group's noise: what a perfect model would leave
    log: RobotLog
    sim: RobotLog

    @property
    def matches(self) -> bool:
        return all(self.rms[g] <= NOISE_MARGIN * n for g, n in self.noise.items() if g in self.rms)


CURRENT_A = 0.1  # vexsim's motor current has no noise: the fit's typical error stands in


def noise_floor(config: RobotConfig, log: RobotLog) -> dict[str, float]:
    """What the sensors' noise alone leaves between a log and its replay, group by group: the
    log's commands simulated with each sensor's noise (as the config gives it, without
    per-device errors), against the replay without any."""
    chans = channels(config, log)
    clean = simulate(config, log, distance=False)
    noisy = simulate(config, log, distance=False, noisy=True)
    found = rms_by_group(at_age(clean, log, 10), at_age(noisy, log, 10), chans)
    found["motor current"] = max(found.get("motor current", 0.0), CURRENT_A)
    return found


def driving_runs(session: Session) -> list[tuple[Run, RobotLog]]:
    """The session's driving runs the fit uses, in the session's order of tests."""
    runs = []
    for test in DRIVE_TESTS:
        runs += session.logs(test)
    return runs


def fit_drive(
    config: RobotConfig,
    runs: Sequence[tuple[Run, RobotLog]],
    *,
    original: RobotConfig | None = None,
    max_iterations: int = 12,
    workers: int = 1,
    say: Say = _quiet,
) -> tuple[dict[str, float], Step, HeldOut | None]:
    """The wheels' friction and rolling resistance (and the battery's resistance) from every
    driving run but the last, which is held out to check them: the overrides, the step, and
    how the held-out run matches."""
    original = original or config
    if not runs:
        raise SessionError("the session has no driving runs to fit (tests 6: straight, spin, arc)")
    held = runs[-1] if len(runs) > 1 else None
    used = list(runs[:-1]) if held else list(runs)
    step = Step("Drive: friction and rolling resistance", runs=[r.file for r, _ in used])
    names = default_parameters(config)
    result = fit_logs(
        config,
        [log for _, log in used],
        names,
        max_iterations=max_iterations,
        workers=workers,
        progress=say,
    )
    found = result.overrides
    step.values += _fitted_values(result, original)
    for key, value in result.direct.items():
        before = current_value(original, key)
        step.values.append(
            Value(
                key, before, value, 0.05 * value, _relative(key, value), note="voltage vs current"
            )
        )
    before = as_configured(original, [log for _, log in used])
    step.rms = {g: (before.rms_after.get(g, math.nan), v) for g, v in result.rms_after.items()}
    for (run, log), was, now in zip(used, before.sims_after, result.sims_after, strict=True):
        step.replays.append((run.file, log, was, now))
    if held is None:
        step.notes.append("only one driving run: none left to check the fit with")
        return found, step, None
    fitted = with_overrides(config, found)
    rms, sim = compare(fitted, held[1])
    floor = noise_floor(fitted, held[1])
    out = HeldOut(held[0].file, rms, floor, held[1], sim)
    shown = ", ".join(f"{g} {rms[g]:.3g} (noise {floor[g]:.2g})" for g in rms if g in floor)
    step.notes.append(f"held out {held[0].file}: {shown}")
    if not out.matches:
        step.warnings.append(
            f"the held-out run ({held[0].file}) doesn't match within the sensors' noise: "
            "see its plot"
        )
    return found, step, out


# --- the tracking wheels ----------------------------------------------------------------------


def _rotation(log: RobotLog, port: int, scale: float) -> np.ndarray:
    """The robot's rotation (rad, counter-clockwise) from the IMU on ``port``."""
    return -np.radians(log[f"imu{port}_deg"]) / (1 + scale)


def _levers(
    config: RobotConfig, log: RobotLog, imu: int, scale: float
) -> dict[int, tuple[float, list[float]]]:
    """Each tracking wheel's travel per radian the robot turned (in), over the whole log and
    turn by turn."""
    theta = _rotation(log, imu, scale)
    ok = np.isfinite(theta)
    out = {}
    for s in config.sensors:
        if s.type != "rotation" or s.tracking_wheel is None or f"r{s.port}_cdeg" not in log:
            continue
        sign = -1.0 if s.reversed else 1.0
        travel = sign * log[f"r{s.port}_cdeg"] / 36000.0 * math.pi * s.tracking_wheel.diameter_in
        rows = ok & np.isfinite(travel)
        th, tr = theta[rows] - theta[rows][0], travel[rows] - travel[rows][0]
        if len(th) < 2 or abs(th[-1]) < math.pi:
            continue
        whole = float(tr[-1] / th[-1])
        marks = np.arange(0.0, abs(th[-1]), 2 * math.pi) * np.sign(th[-1])
        at = [int(np.argmin(np.abs(th - m))) for m in marks] + [len(th) - 1]
        turns = [
            float((tr[b] - tr[a]) / (th[b] - th[a]))
            for a, b in zip(at, at[1:], strict=False)
            if abs(th[b] - th[a]) > math.pi
        ]
        out[s.port] = (whole, turns)
    return out


def fit_tracking(
    config: RobotConfig,
    spin: tuple[Run, RobotLog],
    *,
    original: RobotConfig | None = None,
    say: Say = _quiet,
) -> tuple[dict[int, dict], Step]:
    """Where each tracking wheel is (by port: pos_in), from the slow spin: how far it rolls per
    turn of the robot (by its IMU), against how far the replayed spin's rolls with it where
    the config says (the replay knows where the robot turns about)."""
    original = original or config
    run, log = spin
    step = Step("Slow spin: where the tracking wheels are", runs=[run.file])
    imus = [s for s in config.sensors if s.type == "imu" and f"imu{s.port}_deg" in log]
    if not imus:
        step.skipped = "the slow spin has no IMU readings"
        return {}, step
    imu = imus[0]
    scale = imu.scale_error or 0.0
    real = _levers(config, log, imu.port, scale)
    say("slow spin: replaying it")
    sim = simulate(config, log, distance=False)
    replayed = _levers(config, sim, imu.port, scale)
    found: dict[int, dict] = {}
    for s in config.sensors:
        if s.port not in real or s.port not in replayed:
            continue
        lever, turns = real[s.port]
        shift = lever - replayed[s.port][0]  # the wheel is this much further out than configured
        heading = math.radians(s.tracking_wheel.heading_deg)
        x, y = s.tracking_wheel.pos_in
        pos = (round(x + shift * math.sin(heading), 3), round(y - shift * math.cos(heading), 3))
        spread = float(np.std(turns, ddof=1)) / math.sqrt(len(turns)) if len(turns) > 1 else 0.0
        before = next(o.tracking_wheel.pos_in for o in original.sensors if o.port == s.port)
        found[s.port] = {"pos_in": pos}
        across = "y" if abs(math.cos(heading)) >= abs(math.sin(heading)) else "x"
        step.values.append(
            Value(
                f"sensors.{s.port}.tracking_wheel.pos_in",
                before[1] if across == "y" else before[0],
                pos[1] if across == "y" else pos[0],
                spread,
                TOLERANCE_OF["pos_in"],
                note=f"{across}: how far it is from the turn's center, across its wheel",
            )
        )
        if abs(math.cos(heading)) < 0.7:
            step.notes.append(
                f"tracking wheel {s.port} rolls sideways: the push can't measure its diameter, so "
                "its position here takes the config's diameter"
            )
    return found, step


# --- the distance sensors ---------------------------------------------------------------------


@dataclass
class Readings:
    """A distance sensor's readings in the sweeps, and what each should have been."""

    port: int
    time_ms: np.ndarray
    reading: np.ndarray  # mm, NaN for none
    confidence: np.ndarray
    true_mm: np.ndarray  # what it should have read: NaN if the beam met nothing
    angle: np.ndarray  # how far off square the beam met it (deg)
    new: np.ndarray  # whether the row's reading is new (not the one before, again)
    sweep: np.ndarray  # which sweep


def _field_without_pieces(field: FieldConfig) -> FieldConfig:
    return field.model_copy(
        update={"elements": tuple(e for e in field.elements if e.type != "piece")}
    )


def _sweep_headings(log: RobotLog, imu, scale: float, age_ms: float) -> np.ndarray | None:
    """The robot's heading (deg, counter-clockwise) at each row of a sweep, ``age_ms`` before
    it, from its spot's heading and its IMU."""
    column = f"imu{imu.port}_deg"
    if column not in log:
        return None
    t = log.time_ms
    turned = -(log[column] - log[column][0]) / (1 + scale)
    ok = np.isfinite(turned)
    if ok.sum() < 2:
        return None
    return np.interp(t - age_ms, t[ok], turned[ok])


def _cast(device: DistanceDevice, robot, x: float, y: float, headings, angles: bool):
    """What the sensor should read with the robot at (x, y) m turned to each heading (deg),
    and how far off square its beam meets it (NaN where it meets nothing)."""
    true, angle = np.full(len(headings), np.nan), np.full(len(headings), np.nan)
    for row, h in enumerate(headings):
        robot.pose = (x, y, math.radians(h))
        mm = device.true_distance_mm()
        if mm is not None:
            true[row] = mm
            if angles:
                angle[row] = device.incidence_deg(mm)
    return true, angle


def sweep_readings(
    config: RobotConfig,
    field: FieldConfig,
    sweeps: Sequence[tuple[Run, RobotLog]],
    *,
    age_ms: float | None = None,
) -> dict[int, Readings]:
    """Each distance sensor's readings in the sweeps, with what it should have read from the
    sweep's spot, turned as the IMU says. A reading is older than the IMU's beside it by
    ``age_ms``, or by what fits the readings best (``sweep_age``)."""
    bare = _field_without_pieces(field)
    arena = Arena.of(bare)
    imu = next((s for s in config.sensors if s.type == "imu"), None)
    if imu is None:
        return {}
    scale = imu.scale_error or 0.0
    spec = sensor_spec("distance", "ideal")
    rng = np.random.default_rng(0)
    robot = types.SimpleNamespace(pose=(0.0, 0.0, 0.0))
    devices = {
        s.port: DistanceDevice(s, robot, bare, spec, rng, arena)
        for s in config.sensors
        if s.type == "distance"
    }
    spotted = []
    for k, (_, log) in enumerate(sweeps):
        try:
            x_in, y_in, h_deg = (float(v) for v in log.info["spot"].split())
        except (KeyError, ValueError):
            continue
        spotted.append((k, log, in_to_m(x_in), in_to_m(y_in), h_deg))
    if age_ms is None:
        age_ms = sweep_age(spotted, devices, robot, imu, scale)
    parts: dict[int, list[dict]] = {}
    for k, log, x, y, h_deg in spotted:
        turned = _sweep_headings(log, imu, scale, age_ms)
        if turned is None:
            continue
        t = log.time_ms
        for port, device in devices.items():
            if f"d{port}_mm" not in log:
                continue
            true, angle = _cast(device, robot, x, y, turned + h_deg, angles=True)
            reading = log[f"d{port}_mm"]
            confidence = log[f"d{port}_conf"] if f"d{port}_conf" in log else np.full(len(t), 63.0)
            same = np.zeros(len(t), dtype=bool)
            same[1:] = (reading[1:] == reading[:-1]) | (
                np.isnan(reading[1:]) & np.isnan(reading[:-1])
            )
            parts.setdefault(port, []).append(
                {
                    "time_ms": t,
                    "reading": reading,
                    "confidence": confidence,
                    "true_mm": true,
                    "angle": angle,
                    "new": ~same,
                    "sweep": np.full(len(t), k),
                }
            )
    return {
        port: Readings(port, **{key: np.concatenate([p[key] for p in ps]) for key in ps[0]})
        for port, ps in parts.items()
    }


AGES_MS = tuple(range(-40, 61, 10))  # how much older a distance reading may be than the IMU's


def sweep_age(spotted, devices, robot, imu, scale: float) -> float:
    """How much older the distance readings are than the IMU's beside them (ms): the age at
    which what they read best matches what they should have, where the beam meets things
    at a slant (and so reads differently as the robot turns). Every other row, coarse then
    fine."""

    def misfit(age: float) -> float:
        errors = []
        for _, log, x, y, h_deg in spotted:
            turned = _sweep_headings(log, imu, scale, age)
            if turned is None:
                continue
            rows = np.arange(0, len(log), 2)
            for port, device in devices.items():
                if f"d{port}_mm" not in log:
                    continue
                true, _ = _cast(device, robot, x, y, turned[rows] + h_deg, angles=False)
                reading = log[f"d{port}_mm"][rows]
                ok = np.isfinite(true) & np.isfinite(reading) & (true > 200)
                errors.append(np.abs(reading[ok] - true[ok]) / true[ok])
        joined = np.concatenate(errors) if errors else np.zeros(0)
        return float(np.mean(np.minimum(joined, 0.2))) if len(joined) else math.inf

    coarse = min(AGES_MS, key=misfit)
    return float(min((coarse - 5, coarse, coarse + 5), key=misfit))


def _range(readings: Sequence[Readings], spec) -> tuple[float | None, str]:
    """The sensors' range (mm): beams near square came back out to here, and no further."""
    true = np.concatenate([r.true_mm[r.angle < SQUARE_DEG] for r in readings])
    seen = np.concatenate([np.isfinite(r.reading[r.angle < SQUARE_DEG]) for r in readings])
    keep = np.isfinite(true)
    true, seen = true[keep], seen[keep]
    if not seen.any():
        return None, "no beam near square came back: is the field config the real field?"
    longest = float(true[seen].max())
    beyond = true[~seen & (true > longest)]
    if len(beyond) < 5:
        if longest > spec.max_range_mm:
            return round(
                longest, -1
            ), f"readings came back out to {longest:.0f} mm, all the sweeps reached"
        return None, (
            f"every beam near square came back, out to {longest:.0f} mm: the range stays "
            f"{spec.max_range_mm:g} mm"
        )
    order = np.argsort(true)
    t, s = true[order], seen[order]
    # the cut with the fewest beams on the wrong side of it: back within it, none past it
    wrong = np.cumsum(~s)[:-1] + (np.sum(s) - np.cumsum(s)[:-1])
    cut = int(np.argmin(wrong))
    found = 0.5 * (t[cut] + t[cut + 1])
    return round(
        found, -1
    ), f"beams near square came back to {t[cut]:.0f} mm and none past {t[cut + 1]:.0f} mm"


def _glancing(readings: Sequence[Readings], max_range: float) -> dict | None:
    """Misses at glancing angles: the angle and the distance past which a beam misses this
    often (the best split, by likelihood), or None if there are too few readings to tell."""
    true = np.concatenate([r.true_mm for r in readings])
    angle = np.concatenate([r.angle for r in readings])
    seen = np.concatenate([np.isfinite(r.reading) for r in readings])
    keep = np.isfinite(true) & (true >= 20) & (true <= max_range - 50)
    true, angle, missed = true[keep], angle[keep], ~seen[keep]
    if len(true) < FEW:
        return None

    def loglik(k: int, n: int) -> float:
        if n == 0 or k == 0 or k == n:
            return 0.0
        p = k / n
        return k * math.log(p) + (n - k) * math.log(1 - p)

    base = loglik(int(missed.sum()), len(missed))
    grid = []
    for deg in np.arange(15.0, 86.0, 2.5):
        for mm in np.arange(0.0, max_range, 100.0):
            inside = (angle > deg) & (true > mm)
            n_in = int(inside.sum())
            if n_in < 10:
                continue
            k_in, k_out = int(missed[inside].sum()), int(missed[~inside].sum())
            ll = loglik(k_in, n_in) + loglik(k_out, len(missed) - n_in)
            grid.append(
                (ll, float(deg), float(mm), k_in / n_in, n_in, k_out / max(len(missed) - n_in, 1))
            )
    if not grid:
        return None
    best = max(grid)
    ll, deg, mm, p_in, n_in, p_out = best
    if ll - base < 3.0 or p_in < 0.05:  # no better than missing evenly everywhere
        n = len(missed)
        return {
            "miss": 0.0,
            "deg": math.nan,
            "mm": math.nan,
            "n": n,
            "outside": float(missed.mean()),
            "sd": (1 / math.sqrt(n), math.nan, math.nan),
        }
    near = [g for g in grid if g[0] >= ll - 0.5]  # within one standard deviation
    sd_deg = max(np.ptp([g[1] for g in near]) / 2, 1.25)
    sd_mm = max(np.ptp([g[2] for g in near]) / 2, 50.0)
    # how often, from the beams well inside that: near its edges, a little error in where the
    # robot was puts beams on the wrong side of it
    deep = (angle > deg + INSIDE_DEG) & (true > mm + INSIDE_MM)
    if deep.sum() >= FEW:
        p_in, n_in = float(missed[deep].mean()), int(deep.sum())
    sd_p = math.sqrt(max(p_in * (1 - p_in), 0.01) / n_in)
    return {
        "miss": p_in,
        "deg": deg,
        "mm": mm,
        "n": n_in,
        "outside": p_out,
        "sd": (sd_p, sd_deg, sd_mm),
    }


def _noise(readings: Sequence[Readings]) -> dict[str, tuple[float, float, int]]:
    """The readings' noise from each new reading against its neighbours (second differences,
    which a slowly turning beam hardly curves): long_noise_fraction past 200 mm and
    short_noise_mm closer, with their uncertainty and how many readings told."""
    long, short = [], []
    for r in readings:
        rows = np.flatnonzero(r.new & np.isfinite(r.reading))
        for k in range(1, len(rows) - 1):
            a, b, c = rows[k - 1], rows[k], rows[k + 1]
            if r.sweep[a] != r.sweep[c] or r.time_ms[c] - r.time_ms[a] > 100:
                continue
            if not (
                np.isfinite(r.true_mm[[a, b, c]]).all() and (r.angle[[a, b, c]] < NOISE_DEG).all()
            ):
                continue
            if np.ptp(r.true_mm[[a, b, c]]) > 0.1 * r.true_mm[b]:
                continue  # the beam moved from one thing to another
            e = r.reading[c] - 2 * r.reading[b] + r.reading[a]
            if r.true_mm[b] >= 200:
                long.append(abs(e) / r.true_mm[b])
            else:
                short.append(abs(e))
    gauss = 0.6745 * math.sqrt(6)  # a normal's median |x| over its sd, for 6 sd^2 of variance
    out = {}
    if len(long) >= FEW:
        value = float(np.median(long)) / gauss
        out["sensor.distance.long_noise_fraction"] = (
            value,
            1.2 * value / math.sqrt(len(long)),
            len(long),
        )
    if len(short) >= FEW:
        value = float(np.median(short)) / gauss
        out["sensor.distance.short_noise_mm"] = (
            value,
            1.2 * value / math.sqrt(len(short)),
            len(short),
        )
    return out


def _confidence(readings: Sequence[Readings]) -> dict[str, tuple[float, float]] | None:
    """How the confidence drops: per meter past 0.2 m and per degree off square (least
    squares over the new readings, those it didn't clip at 0)."""
    x1, x2, y = [], [], []
    for r in readings:
        rows = r.new & np.isfinite(r.reading) & np.isfinite(r.true_mm) & (r.confidence > 0)
        x1.append(np.maximum(r.true_mm[rows] / 1000.0 - 0.2, 0.0))
        x2.append(r.angle[rows])
        y.append(63.0 - r.confidence[rows])
    x = np.column_stack([np.concatenate(x1), np.concatenate(x2)])
    y = np.concatenate(y)
    if len(y) < FEW:
        return None
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    coef = np.maximum(coef, 0.0)
    resid = y - x @ coef
    sigma2 = float(resid @ resid) / max(len(y) - 2, 1)
    try:
        spread = np.sqrt(np.diag(np.linalg.inv(x.T @ x)) * sigma2)
    except np.linalg.LinAlgError:
        spread = np.full(2, math.inf)
    return {
        "sensor.distance.confidence_per_m": (float(coef[0]), float(spread[0])),
        "sensor.distance.confidence_per_deg": (float(coef[1]), float(spread[1])),
    }


def fit_distance(
    config: RobotConfig,
    field: FieldConfig,
    sweeps: Sequence[tuple[Run, RobotLog]],
) -> tuple[dict[str, float], Step]:
    """The distance sensors' noise, range, glancing misses and confidence from the sweeps,
    against what each should have read from where it was: the overrides and the step."""
    step = Step("Distance sweeps: the distance sensors", runs=[r.file for r, _ in sweeps])
    params = resolve_params(config.overrides)
    spec = sensor_spec("distance", "default", params.sensor_overrides.get("distance"))
    readings = sweep_readings(config, field, sweeps)
    step.readings = readings
    found: dict[str, float] = {}
    if not readings:
        step.skipped = "no sweep has a spot and both IMU and distance readings"
        return found, step
    for r in readings.values():  # a sensor that reads far from what it should is set up wrong
        both = np.isfinite(r.reading) & np.isfinite(r.true_mm) & (r.angle < SQUARE_DEG) & r.new
        if both.sum() >= FEW:
            off = float(np.median(np.abs(r.reading[both] - r.true_mm[both]) / r.true_mm[both]))
            step.notes.append(
                f"port {r.port}: {both.sum()} readings near square, {off:.1%} off what it should"
            )
            if off > 0.08:
                step.warnings.append(
                    f"the distance sensor on port {r.port} reads {off:.0%} off what it should: "
                    "check its pos_in and heading_deg in the config, and the spot it swept from"
                )

    def put(key: str, value: float, sigma: float, digits: int, note: str = "") -> None:
        before = getattr(spec, key.rsplit(".", 1)[1])
        found[key] = float(round(float(value), digits))
        step.values.append(Value(key, before, found[key], sigma, _relative(key, value), note))

    for key, (value, sigma, n) in _noise(readings.values()).items():
        put(key, value, sigma, 4 if key.endswith("fraction") else 2, f"{n} readings")
    if "sensor.distance.short_noise_mm" not in found:
        step.notes.append("too few readings under 200 mm to tell short_noise_mm: it stays as it is")
    reach, how = _range(readings.values(), spec)
    step.notes.append(how)
    if reach is not None:
        put("sensor.distance.max_range_mm", reach, 25.0, 0)
    max_range = found.get("sensor.distance.max_range_mm", spec.max_range_mm)
    glancing = _glancing(readings.values(), max_range)
    if glancing is None:
        step.notes.append("too few readings to tell misses at glancing angles")
    else:
        sd_p, sd_deg, sd_mm = glancing["sd"]
        put(
            "sensor.distance.glancing_miss",
            glancing["miss"],
            sd_p,
            2,
            f"of {glancing['n']} readings",
        )
        if glancing["miss"] > 0:
            put("sensor.distance.glancing_deg", glancing["deg"], sd_deg, 1)
            put("sensor.distance.glancing_mm", glancing["mm"], sd_mm, 0)
        if glancing["outside"] > 0.05:
            step.warnings.append(
                f"{glancing['outside']:.0%} of the readings that should have come back didn't, "
                "beyond the glancing ones: is the field config the real field, elements and all?"
            )
    confidence = _confidence(readings.values())
    if confidence is None:
        step.notes.append("too few readings to tell how the confidence drops")
    else:
        for key, (value, sigma) in confidence.items():
            put(key, value, sigma, 3)
    return found, step


# --- the drive model --------------------------------------------------------------------------


def drive_model(
    config: RobotConfig, runs: Sequence[tuple[Run, RobotLog]]
) -> feedforward.DriveModel | None:
    """kS, kV, kA and kT for vexsim's own motions, from the driving runs as they were logged
    (each side's voltage and wheel speed), with the wheels' measured diameters."""
    if config.drivetrain.type not in ("differential", "hdrive"):
        return None
    return feedforward.fit_logs(config, [log for _, log in runs])


# --- the whole session ------------------------------------------------------------------------


@dataclass
class Calibration:
    """What a session's fit found: each step, the config with all of it, and the changes."""

    robot: str
    session: Path
    steps: list[Step]
    config: RobotConfig  # the robot as calibrated
    overrides: dict[str, float]  # new or changed override values
    diameters: dict[str, float]  # drive group: its wheels' diameter (in)
    tracking: dict[int, dict]  # tracking wheel's port: changed fields (diameter_in, pos_in)
    imu_scales: dict[int, float]  # IMU's port: scale_error
    held_out: HeldOut | None = None
    drive: feedforward.DriveModel | None = None

    def values(self) -> list[Value]:
        """Every value found, the last step's where two steps found one (the second push)."""
        out: dict[str, Value] = {}
        for step in self.steps:
            for v in step.values:
                out[v.key] = v
        return list(out.values())

    @property
    def warnings(self) -> list[str]:
        return [w for s in self.steps for w in s.warnings]


def calibrate(
    config: RobotConfig,
    session: Session,
    field: FieldConfig | None = None,
    *,
    workers: int = 1,
    say: Say = _quiet,
) -> Calibration:
    """Fit the whole session, test by test (the module says in which order and why).
    Raises SessionError if it can't: a failed device check, or a test the fit needs missing."""
    check, problems = device_check(session)
    if problems:
        raise SessionError(
            f"the device check ({check.file}) found what to fix first:\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\nFix the config (or the wiring), run the device check again and collect it."
        )
    if session.robot and config.name and session.robot != config.name:
        raise SessionError(
            f"the session is {session.robot}'s, and the config is {config.name}'s: "
            "pick the robot's config"
        )
    original = config
    steps: list[Step] = []
    overrides: dict[str, float] = {}

    free = session.logs("free_spin")
    if not free:
        raise SessionError("the session has no free spin (test 2): run it and collect its log")
    run, log = free[-1]
    say("free spin")
    motors, step = fit_free_spin(config, log, run=run, workers=workers, say=say)
    steps.append(step)
    overrides.update(motors)
    config = with_overrides(config, motors)

    scales: dict[int, float] = {}
    turns, still = session.logs("imu_turns"), session.logs("imu_still")
    if imu_ports(config) and (turns or still):
        say("IMU")
        scales, imu_noise_found, step = fit_imu(config, still, turns)
        steps.append(step)
        overrides.update(imu_noise_found)
        config = with_overrides(with_imu_scales(config, scales), imu_noise_found)

    pushes = session.logs("push")
    if not pushes:
        raise SessionError("the session has no push (test 5): run it and collect its logs")
    runs = driving_runs(session)
    if not runs:
        raise SessionError("the session has no driving runs (tests 6): run them and collect them")
    diameters: dict[str, float] = {}
    tracking: dict[int, dict] = {}
    held, spin_step = None, None
    spins = session.logs("slow_spin")
    has_tracking = any(s.type == "rotation" and s.tracking_wheel for s in config.sensors)
    # The push replays with the friction the drive finds, so both go twice; the tracking
    # wheels go between, as the drive's fit compares their readings too.
    for round_ in (1, 2):
        say(f"push (round {round_} of 2)")
        diameters, rolled, push_step = fit_push(config, pushes, original=original, say=say)
        for port, d in rolled.items():
            tracking.setdefault(port, {})["diameter_in"] = d
        config = with_tracking(with_diameters(config, diameters), tracking)
        if spins and has_tracking:
            say(f"slow spin (round {round_} of 2)")
            placed, spin_step = fit_tracking(config, spins[-1], original=original, say=say)
            for port, fields in placed.items():
                tracking.setdefault(port, {}).update(fields)
            config = with_tracking(config, tracking)
        say(f"drive (round {round_} of 2)")
        drive, drive_step, held = fit_drive(
            config,
            runs,
            original=original,
            max_iterations=12 if round_ == 1 else 6,
            workers=workers,
            say=say,
        )
        overrides.update(drive)
        config = with_overrides(config, drive)
    steps += [push_step, drive_step]
    if spin_step is not None:
        steps.append(spin_step)

    sweeps = [(r, log) for test in _sweep_tests(session) for r, log in session.logs(test)]
    if sweeps:
        if field is None:
            step = Step("Distance sweeps: the distance sensors", runs=[r.file for r, _ in sweeps])
            step.skipped = "no field config: give the field the sweeps ran on (--field FIELD.yaml)"
            steps.append(step)
        else:
            say("distance sweeps")
            found, step = fit_distance(config, field, sweeps)
            steps.append(step)
            overrides.update(found)
            config = with_overrides(config, found)

    model = drive_model(config, runs)
    changed = {
        k: v
        for k, v in overrides.items()
        if k not in original.overrides or original.overrides[k] != v
    }
    return Calibration(
        robot=config.name or session.robot or "robot",
        session=session.folder,
        steps=steps,
        config=config,
        overrides=changed,
        diameters=diameters,
        tracking=tracking,
        imu_scales=scales,
        held_out=held,
        drive=model,
    )


def _sweep_tests(session: Session) -> list[str]:
    return sorted({r.test for r in session.runs if r.test.startswith("sweep")})

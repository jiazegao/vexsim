"""A drive's feedforward model, for vexsim's own motions (PLAN.md 13.4): how each side of a
differential drive answers voltage,

    volts = kS * sign(v) + kV * v + kA * a +- kT * turning(w)

for the side's wheel speed v (in/s) and its acceleration a (in/s^2); kT pushes the sides apart
against the wheels' scrub when the robot turns (w, rad/s: the right side forward for a turn
counter-clockwise). It's fitted to a robot log by least squares. The log is a real robot's (the
calibration routine's, section 12 of the README), or one vexsim records driving the robot its
config describes (``characterize``). The motions (vexsim/bridge/cpp/motions) plan within the
limits that come with it, and drive each side with the voltage the model says.
"""

from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from vexsim.calibration.log import RobotLog
from vexsim.config.robot import RobotConfig

G_IN_S2 = 386.09
MIN_SPEED = 0.5  # in/s: slower than this, a sample says little about kS's sign
VOLTS = 12.0
FEEDBACK = 4.0  # kP, as a multiple of kV
TURNING = 0.15  # rad/s: turning faster than this, the scrub is all there (a smooth sign)
TURNED = 0.5  # rad/s: a log turned the robot if it turned this fast (else, it says nothing of kT)


def turning(w):
    """How much of the wheels' scrub a turn at ``w`` rad/s meets, -1..1."""
    return np.tanh(np.asarray(w) / TURNING)


@dataclass(frozen=True)
class DriveModel:
    """kS (V), kV (V per in/s), kA (V per in/s^2) and kT (V, against the scrub in a turn);
    kP, the volts more for each in/s a side's wheels are slower than the model says (for what
    it leaves out); the limits motions plan within: the fastest either side's wheels may go,
    how fast the robot may speed up and slow down, and how hard it may turn at speed (in/s,
    in/s^2); and how well the model fits its log."""

    kS: float
    kV: float
    kA: float
    kT: float
    kP: float
    max_velocity: float
    max_accel: float
    max_lateral_accel: float
    top_speed: float  # in/s: where 12 V levels off, (12 - kS) / kV, at most the rated speed
    samples: int
    r2: float
    turned: bool = True  # whether its log turned the robot: kT is 0 if it didn't

    def describe(self) -> str:
        return (
            f"kS {self.kS:.3f} V, kV {self.kV:.4f} V per in/s, kA {self.kA:.4f} V per in/s^2, "
            f"kT {self.kT:.3f} V (fits {self.samples} samples, R² {self.r2:.3f}); top speed "
            f"{self.top_speed:.1f} in/s"
        )


def sides(config: RobotConfig) -> dict[str, tuple[list[int], float]]:
    """Each side of a differential drive (or H-drive), left then right: its motors' config
    ports (negative: reversed) and how many in/s of wheel speed a motor rpm makes."""
    drive = config.drivetrain
    if drive.type not in ("differential", "hdrive"):
        raise ValueError(
            "a feedforward model is for a differential drive's left and right sides; "
            f"this robot's is {drive.type}"
        )
    out = {}
    for name in ("left", "right"):
        group = drive.gearing[name]
        diameter = sum(drive.wheel(w).diameter_in for w in group.wheels) / len(group.wheels)
        out[name] = (list(group.motors), group.speed_ratio * math.pi * diameter / 60.0)
    return out


def side_samples(config: RobotConfig, log: RobotLog) -> list[tuple[np.ndarray, ...]]:
    """For each side: the times (s), the voltage it was driven with (V), its wheel speed (in/s)
    and acceleration (in/s^2), and whether a voltage drove it then (not stopped or coasting)."""
    t = log.time_s
    out = []
    for ports, per_rpm in sides(config).values():
        volts, speed, driven = [], [], []
        for port in ports:
            p, sign = abs(port), (1.0 if port > 0 else -1.0)
            if f"m{p}_mv" not in log or f"m{p}_rpm" not in log:
                continue
            volts.append(sign * log[f"m{p}_mv"] / 1000.0)
            speed.append(sign * log[f"m{p}_rpm"] * per_rpm)
            command = log[f"m{p}_cmd_mv"] if f"m{p}_cmd_mv" in log else np.full(len(t), np.nan)
            driven.append(np.isfinite(command) & (command != 0))
        if not volts:
            continue
        v = np.nanmean(speed, axis=0)
        smooth = np.convolve(np.nan_to_num(v), np.ones(5) / 5, mode="same")  # readings jitter
        with np.errstate(divide="ignore", invalid="ignore"):  # rows logged at the same time
            a = np.gradient(smooth, t) if len(t) > 2 else np.zeros_like(v)
        out.append((t, np.nanmean(volts, axis=0), v, a, np.all(driven, axis=0)))
    return out


def fit(config: RobotConfig, log: RobotLog) -> DriveModel | None:
    """kS, kV, kA and kT fitted to ``log`` (both sides together), and the limits that follow;
    None if the log has too little driving in it to tell. (A log without turns says nothing
    of kT: it's 0.)"""
    return fit_logs(config, [log])


def fit_logs(config: RobotConfig, logs: list[RobotLog]) -> DriveModel | None:
    """``fit`` over several logs together (a calibration session's driving runs)."""
    parts = [part for log in logs if (part := _rows(config, log)) is not None]
    if not parts:
        return None
    rows = [r for part in parts for r in part[0]]
    targets = [t for part in parts for t in part[1]]
    turns = [t for part in parts for t in part[2]]
    return _solve(config, rows, targets, turns)


def _rows(config: RobotConfig, log: RobotLog):
    """One log's least-squares rows (sign, speed, acceleration, turning), each side's
    voltages, and which rows turned the robot; None without both sides."""
    samples = side_samples(config, log)
    if len(samples) != 2:
        return None
    (_, _, left, _, _), (_, _, right, _, _) = samples
    w = (right - left) / track_width(config)  # rad/s, counter-clockwise
    # turning harder than its wheels hold, the robot slides sideways, which takes more than
    # the model says: those samples are left out
    sliding = np.abs((left + right) / 2 * w) > turning_grip(config) * G_IN_S2
    rows, targets, turns = [], [], []
    for side, (_, volts, v, a, driven) in zip((-1.0, 1.0), samples, strict=True):
        edge = np.zeros(len(v), dtype=bool)
        edge[2:-2] = True  # the smoothing's ends
        use = driven & edge & np.isfinite(volts) & np.isfinite(v) & (np.abs(v) >= MIN_SPEED)
        use &= np.isfinite(a)
        use &= np.isfinite(w) & ~sliding
        rows.append(np.column_stack([np.sign(v[use]), v[use], a[use], side * turning(w[use])]))
        targets.append(volts[use])
        turns.append(np.abs(w[use]) > TURNED)
    return rows, targets, turns


def _solve(config: RobotConfig, rows, targets, turns) -> DriveModel | None:
    if sum(len(r) for r in rows) < 20:
        return None
    x, y = np.vstack(rows), np.concatenate(targets)
    turned = bool(np.count_nonzero(np.concatenate(turns)) >= 20)
    if not turned:  # nothing to tell kT by
        x = x[:, :3]
    found, *_ = np.linalg.lstsq(x, y, rcond=None)
    ks, kv, ka, kt = (*found, 0.0) if not turned else found
    if kv <= 0:
        return None
    ks, ka, kt = (max(0.0, float(k)) for k in (ks, ka, kt))
    residual = y - x @ np.array([ks, kv, ka, kt][: x.shape[1]])
    total = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(residual**2)) / total if total > 0 else 1.0
    return dataclasses.replace(model(config, ks, float(kv), ka, kt, len(y), r2), turned=turned)


def fit_log(config: RobotConfig, log: RobotLog) -> DriveModel | None:
    """``fit``, or None when the robot's drive isn't a differential drive's two sides."""
    if config.drivetrain.type not in ("differential", "hdrive"):
        return None
    return fit(config, log)


def drive_section(found: DriveModel) -> str:
    """The model as a route's drive: section has it: its constants (kT only if its log turned
    the robot; the limits follow from them)."""
    keys = ("kS", "kV", "kA", *(("kT",) if found.turned else ()))
    return "drive: {" + ", ".join(f"{k}: {getattr(found, k):g}" for k in keys) + "}"


def track_width(config: RobotConfig) -> float:
    """How far apart the left and right wheels are (in)."""
    from vexsim.algorithms.control.base import ChassisGeometry

    return ChassisGeometry.from_config(config).track_width_in


def rated_speed(config: RobotConfig) -> float:
    """How fast the wheels go with the motors at their cartridge's rated speed (in/s)."""
    from vexsim.algorithms.control.base import ChassisGeometry

    return ChassisGeometry.from_config(config).max_speed_in_s


def model(
    config: RobotConfig,
    ks: float,
    kv: float,
    ka: float,
    kt: float = 0.0,
    samples: int = 0,
    r2: float = 1.0,
) -> DriveModel:
    """A model from its constants, with the limits vexsim plans within for this robot: 80%
    of the top speed (headroom for the corrections; no faster than its motors' rated speed
    turns its wheels, where a log of slower driving can't tell), the acceleration a third of
    the voltage at a standstill gives, and half the sideways grip a turn leaves it
    (``turning_grip``)."""
    top = min((VOLTS - ks) / kv, rated_speed(config))
    accel = (VOLTS - ks) / (3 * ka) if ka > 0 else 120.0
    return DriveModel(
        kS=round(ks, 3),
        kV=round(kv, 4),
        kA=round(ka, 4),
        kT=round(kt, 3),
        kP=round(FEEDBACK * kv, 4),
        max_velocity=round(0.8 * top, 1),
        max_accel=round(min(accel, 250.0), 1),
        max_lateral_accel=round(0.5 * turning_grip(config) * G_IN_S2, 1),
        top_speed=round(top, 1),
        samples=samples,
        r2=round(r2, 4),
    )


MIDDLE_IN = 1.5  # wheels this close to the robot's middle, front to back, don't scrub in a turn


def turning_grip(config: RobotConfig) -> float:
    """How hard the robot can be pushed sideways while it turns, as a fraction of its weight
    (the friction coefficient of the robot as a whole). In a turn the wheels ahead of and
    behind its middle slide sideways (the scrub), which uses up their sideways grip; only the
    wheels in the middle, with their share of the weight, hold it on its curve. A robot with
    none there slides in any turn: a quarter of its wheels' grip, as a guess."""
    wheels = config.drivetrain.wheels
    cg = config.body.cg_in[0]
    grip = [
        _lateral_mu(config, w.type)
        for w in wheels
        if abs(w.pos_in[0] - cg) <= MIDDLE_IN and w.heading_deg % 180 == 0
    ]
    if grip:
        return sum(grip) / len(wheels)
    every = [_lateral_mu(config, w.type) for w in wheels]
    return 0.25 * sum(every) / len(every) if every else 0.05


def _lateral_mu(config: RobotConfig, wheel_type: str) -> float:
    from vexsim.physics.params import resolve_params

    spec = resolve_params(config.overrides).wheel(wheel_type)
    return float(getattr(spec, "lateral_mu", getattr(spec, "mu", getattr(spec, "roller_mu", 0.2))))


# --- vexsim's own robot, driven open-loop -------------------------------------------------------


def characterization_steps(config: RobotConfig):
    """Straight drives at a few voltages, forward and back, from a standstill and from speed,
    then turns in place: the steady speeds tell kS and kV, the changes in between tell kA,
    and the turns kT. About 9 s; the robot ends near where it started."""
    from vexsim.calibration.routine import Step

    return [
        Step("settle", 0.3),
        Step("slow", 1.2, forward=0.25),
        Step("faster", 0.9, forward=0.55),
        Step("fast", 0.7, forward=0.9),
        Step("brake", 0.5, brake="brake"),
        Step("back", 1.0, forward=-0.4),
        Step("back faster", 0.9, forward=-0.75),
        Step("brake", 0.5, brake="brake"),
        Step("turn", 1.0, turn=0.3),
        Step("turn faster", 0.7, turn=0.6),
        Step("brake", 0.4, brake="brake"),
        Step("turn back", 1.0, turn=-0.45),
        Step("brake", 0.4, brake="brake"),
    ]


def characterize(config: RobotConfig) -> DriveModel:
    """The model of the drive ``config`` describes: vexsim drives it open-loop through
    ``characterization_steps``, logs it as a robot would, and fits that."""
    return _characterize(json.dumps(config.model_dump(mode="json"), sort_keys=True))


@lru_cache(maxsize=32)
def _characterize(config_json: str) -> DriveModel:
    from vexsim.calibration.routine import run_routine

    config = RobotConfig.model_validate(json.loads(config_json))
    found = fit(config, run_routine(config, characterization_steps(config), noise="ideal"))
    if found is None:  # (it always drives: the steps say so)
        raise ValueError("the simulated drive didn't move: no model to fit")
    return found

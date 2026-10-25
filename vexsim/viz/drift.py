"""Arc-turn drift: true path vs. what drive-encoder odometry believes, across roller friction."""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from vexsim.config.robot import RobotConfig
from vexsim.physics.params import resolve_params
from vexsim.physics.robot import Robot
from vexsim.units import m_to_in

# Reference palette (dataviz skill): categorical slots in fixed order; reference ink.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"


@dataclass(frozen=True)
class DriftRun:
    lateral_mu: float
    true_xy: np.ndarray  # (n, 2) inches, footprint center
    odom_xy: np.ndarray  # (n, 2) inches, from drive-encoder dead reckoning

    @property
    def final_error_in(self) -> float:
        return float(np.hypot(*(self.true_xy[-1] - self.odom_xy[-1])))


def run_arc(
    config: RobotConfig,
    lateral_mu: float,
    *,
    left: float,
    right: float,
    seconds: float,
    sample_every: int = 10,
) -> DriftRun:
    """Drive both sides at fractions of rated speed and record true vs. odometry paths."""
    if config.drivetrain.type != "differential":
        raise ValueError("drift runs need a differential drivetrain")
    overrides = {**config.overrides, "wheel.omni.lateral_mu": lateral_mu}
    robot = Robot(config, params=resolve_params(overrides))
    groups = {name: robot.group(name) for name in ("left", "right")}
    for name, fraction in (("left", left), ("right", right)):
        groups[name].set_velocity(fraction * groups[name].rated_speed)

    # Drive-encoder odometry: integrate side surface speeds over the track width.
    radius = {n: float(np.mean(robot.wheel_radius[g.wheels])) for n, g in groups.items()}
    side_y = {n: float(np.mean(robot.wheel_pos[g.wheels, 1])) for n, g in groups.items()}
    track = side_y["left"] - side_y["right"]
    x, y, heading = robot.pose
    true_xy, odom_xy = [], []
    dt = 0.001
    for i in range(round(seconds / dt)):
        robot.advance(dt)
        vl, vr = (robot.group_speed(n) * groups[n].ratio * radius[n] for n in ("left", "right"))
        forward, turn = 0.5 * (vl + vr), (vr - vl) / track
        mid = heading + 0.5 * turn * dt
        x += forward * math.cos(mid) * dt
        y += forward * math.sin(mid) * dt
        heading += turn * dt
        if i % sample_every == 0:
            true_xy.append(robot.pose[:2])
            odom_xy.append((x, y))
    to_in = np.vectorize(m_to_in)
    return DriftRun(lateral_mu, to_in(np.array(true_xy)), to_in(np.array(odom_xy)))


def to_csv(runs: list[DriftRun]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["lateral_mu", "sample", "true_x_in", "true_y_in", "odom_x_in", "odom_y_in"])
    for run in runs:
        for k, (t, o) in enumerate(zip(run.true_xy, run.odom_xy, strict=True)):
            writer.writerow(
                [run.lateral_mu, k, f"{t[0]:.2f}", f"{t[1]:.2f}", f"{o[0]:.2f}", f"{o[1]:.2f}"]
            )
    return out.getvalue()


def plot(runs: list[DriftRun], path: str | Path, *, title: str) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if len(runs) > len(SERIES):
        raise ValueError(f"plot at most {len(SERIES)} friction values")
    fig, ax = plt.subplots(figsize=(7.5, 7.0), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=TEXT_SECONDARY)

    for run, color in zip(runs, SERIES, strict=False):
        label = f"roller friction {run.lateral_mu:g}"
        ax.plot(*run.true_xy.T, color=color, linewidth=2, label=f"{label}: true path")
        ax.plot(*run.odom_xy.T, color=color, linewidth=1.2, linestyle=(0, (4, 3)), alpha=0.9)
        ax.plot(*run.true_xy[-1], "o", color=color, markersize=8, markeredgecolor=SURFACE)
        ax.annotate(
            f"{run.final_error_in:.0f} in odometry error",
            xy=run.true_xy[-1],
            xytext=(8, -4),
            textcoords="offset points",
            color=TEXT_PRIMARY,
            fontsize=9,
        )
    ax.plot(
        [],
        [],
        color=TEXT_SECONDARY,
        linewidth=1.2,
        linestyle=(0, (4, 3)),
        label="drive-encoder odometry",
    )
    ax.plot(0, 0, "s", color=TEXT_SECONDARY, markersize=6)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("x (in)", color=TEXT_SECONDARY)
    ax.set_ylabel("y (in)", color=TEXT_SECONDARY)
    ax.legend(frameon=False, loc="best", fontsize=9, labelcolor=TEXT_PRIMARY)
    ax.set_title(title, color=TEXT_PRIMARY, fontsize=11)
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return path

"""A robot log against the simulation's replay of it, before and after a fit."""

from __future__ import annotations

from pathlib import Path

from vexsim.calibration.fit import Channel, channels, signal_of
from vexsim.calibration.log import RobotLog
from vexsim.config.robot import RobotConfig
from vexsim.viz.odometry import GRID, SERIES, SURFACE, TEXT_PRIMARY, TEXT_SECONDARY


def _panels(config: RobotConfig, log: RobotLog) -> list[tuple[str, Channel]]:
    """One motor per gear group, then every tracking wheel and IMU."""
    chans = {c.name: c for c in channels(config, log)}
    out = []
    for name, gear in config.drivetrain.gearing.items():
        port = abs(gear.motors[0])
        if f"m{port}_rpm" in chans:
            out.append((f"{name} motor (port {port}) velocity, rpm", chans[f"m{port}_rpm"]))
    for ch in chans.values():
        if ch.group == "tracking wheels":
            out.append((f"rotation sensor {ch.name[1:].split('_')[0]} speed, deg/s", ch))
        elif ch.group == "heading rate":
            out.append(("IMU heading rate, deg/s (clockwise +)", ch))
    return out[:7]


def plot(
    config: RobotConfig,
    log: RobotLog,
    before: RobotLog | None,
    after: RobotLog | None,
    path: str | Path,
    *,
    title: str,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    panels = _panels(config, log)
    fig, axes = plt.subplots(
        len(panels), 1, figsize=(8.0, 1.9 * len(panels) + 0.8), sharex=True, facecolor=SURFACE
    )
    axes = [axes] if len(panels) == 1 else list(axes)
    t = log.time_s
    for ax, (label, ch) in zip(axes, panels, strict=True):
        ax.set_facecolor(SURFACE)
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
        ax.tick_params(colors=TEXT_SECONDARY, labelsize=8)
        x = t[len(t) - len(signal_of(log, ch)) :]
        ax.plot(x, signal_of(log, ch), color=TEXT_PRIMARY, linewidth=1.2, label="robot log")
        if before is not None:
            style = {"color": SERIES[1], "linewidth": 1.2, "linestyle": "--"}
            ax.plot(x, signal_of(before, ch), **style, label="simulated, before the fit")
        if after is not None:
            ax.plot(x, signal_of(after, ch), color=SERIES[0], linewidth=1.5, label="simulated")
        ax.set_title(label, color=TEXT_PRIMARY, fontsize=9, loc="left")
    axes[-1].set_xlabel("time (s)", color=TEXT_SECONDARY)
    fig.suptitle(title, color=TEXT_PRIMARY, fontsize=11)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.955),
        ncol=len(labels),
        frameon=False,
        fontsize=8,
        labelcolor=TEXT_PRIMARY,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    path = Path(path)
    fig.savefig(path, dpi=110, facecolor=SURFACE)
    plt.close(fig)
    return path

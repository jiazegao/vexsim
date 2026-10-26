"""Telemetry plots from a run's CSV log: path, speed, motor currents and temperatures, battery."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from vexsim.runtime.recorder import Log

# Reference palette (dataviz skill): categorical slots in fixed order.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"


def plot(log: Log, path: str | Path, *, title: str = "") -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = _identical_motors(log)
    if len(groups) > len(SERIES):
        raise ValueError(f"at most {len(SERIES)} motor groups can be told apart in one panel")
    t = log["time_s"]
    fig = plt.figure(figsize=(11, 8.5), facecolor=SURFACE)
    grid = fig.add_gridspec(4, 2, width_ratios=[1.1, 1.0])
    path_ax = fig.add_subplot(grid[:, 0])
    axes = [fig.add_subplot(grid[i, 1]) for i in range(4)]
    for ax in (path_ax, *axes):
        ax.set_facecolor(SURFACE)
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
        ax.tick_params(colors=TEXT_SECONDARY, labelsize=8)

    path_ax.plot(log["x_in"], log["y_in"], color=TEXT_PRIMARY, linewidth=2, label="true")
    path_ax.plot(
        log["est_x_in"], log["est_y_in"], color=SERIES[0], linewidth=1.5, label="estimated"
    )
    path_ax.plot(log["x_in"][0], log["y_in"][0], "s", color=TEXT_SECONDARY)
    path_ax.set_aspect("equal", adjustable="datalim")
    path_ax.set_xlabel("x (in)", color=TEXT_SECONDARY)
    path_ax.set_ylabel("y (in)", color=TEXT_SECONDARY)
    path_ax.legend(frameon=False, fontsize=9, labelcolor=TEXT_PRIMARY)
    path_ax.set_title("path", color=TEXT_PRIMARY, fontsize=10, loc="left")

    speed_ax, current_ax, temp_ax, battery_ax = axes
    speed_ax.plot(t, log["speed_in_s"], color=SERIES[0], linewidth=1.5)
    speed_ax.set_title("speed (in/s)", color=TEXT_PRIMARY, fontsize=10, loc="left")
    for ports, color in zip(groups, SERIES, strict=False):
        label = f"port {ports[0]}" if len(ports) == 1 else "ports " + ", ".join(map(str, ports))
        p = ports[0]
        current_ax.plot(t, log[f"motor{p}_current_a"], color=color, linewidth=1.2, label=label)
        temp_ax.plot(t, log[f"motor{p}_temp_c"], color=color, linewidth=1.2, label=label)
    current_ax.set_title("motor current (A)", color=TEXT_PRIMARY, fontsize=10, loc="left")
    current_ax.legend(frameon=False, fontsize=7, ncol=2, labelcolor=TEXT_PRIMARY, loc="upper right")
    temp_ax.set_title("motor temperature (C)", color=TEXT_PRIMARY, fontsize=10, loc="left")
    battery_ax.plot(t, log["battery_v"], color=SERIES[0], linewidth=1.5)
    battery_ax.set_title("battery (V)", color=TEXT_PRIMARY, fontsize=10, loc="left")
    battery_ax.set_xlabel("time (s)", color=TEXT_SECONDARY)
    if title:
        fig.suptitle(title, color=TEXT_PRIMARY, fontsize=11)
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)
    return path


def _identical_motors(log: Log) -> list[list[int]]:
    """Ports grouped by identical current and temperature traces (motors geared together)."""
    groups: list[list[int]] = []
    for port in log.motor_ports:
        trace = np.concatenate([log[f"motor{port}_current_a"], log[f"motor{port}_temp_c"]])
        for group in groups:
            ref = np.concatenate(
                [log[f"motor{group[0]}_current_a"], log[f"motor{group[0]}_temp_c"]]
            )
            if np.allclose(trace, ref, atol=1e-6):
                group.append(port)
                break
        else:
            groups.append([port])
    return groups

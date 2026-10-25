"""Torque, current and power vs. speed for a V5 motor, measured on the simulated dynamometer."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from vexsim.physics.motor import V5Motor
from vexsim.physics.rig import TorqueSpeedCurve, torque_speed_curve
from vexsim.units import rad_s_to_rpm

# Reference palette (dataviz skill): categorical slots 1-2, light surface and text tokens.
SERIES = {"velocity": "#2a78d6", "voltage": "#eb6834"}
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"

LABELS = {"velocity": "move_velocity(max)", "voltage": "move_voltage(12000)"}


def compute(cartridge: str, supply_voltage: float, points: int = 61) -> list[TorqueSpeedCurve]:
    return [
        torque_speed_curve(cartridge, command, supply_voltage=supply_voltage, points=points)
        for command in ("velocity", "voltage")
    ]


def to_csv(curves: list[TorqueSpeedCurve]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["command", "speed_rpm", "torque_nm", "current_a", "power_out_w"])
    for c in curves:
        for w, t, i, p in zip(c.speed, c.torque, c.current, c.power_out, strict=True):
            writer.writerow(
                [c.command, f"{rad_s_to_rpm(w):.2f}", f"{t:.4f}", f"{i:.4f}", f"{p:.3f}"]
            )
    return out.getvalue()


def plot(curves: list[TorqueSpeedCurve], path: str | Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cartridge, volts = curves[0].cartridge, curves[0].supply_voltage
    current_limit = V5Motor(cartridge).spec.current_limit_a

    plt.rcParams.update(
        {
            "font.size": 10,
            "text.color": TEXT_PRIMARY,
            "axes.labelcolor": TEXT_SECONDARY,
            "xtick.color": TEXT_SECONDARY,
            "ytick.color": TEXT_SECONDARY,
            "axes.edgecolor": GRID,
        }
    )
    fig, axes = plt.subplots(3, 1, figsize=(7.5, 8.5), sharex=True, facecolor=SURFACE)
    panels = [
        ("Torque (N*m)", lambda c: c.torque),
        ("Current (A)", lambda c: c.current),
        ("Output power (W)", lambda c: c.power_out),
    ]
    for ax, (label, getter) in zip(axes, panels, strict=True):
        ax.set_facecolor(SURFACE)
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.set_ylabel(label)
        for c in curves:
            rpm = [rad_s_to_rpm(w) for w in c.speed]
            ax.plot(rpm, getter(c), color=SERIES[c.command], linewidth=2, label=LABELS[c.command])
        ax.axhline(0, color=TEXT_SECONDARY, linewidth=0.8)
    axes[1].axhline(current_limit, color=TEXT_SECONDARY, linewidth=1, linestyle=(0, (4, 3)))
    axes[1].annotate(
        f"current limit {current_limit:g} A",
        xy=(0, current_limit),
        xytext=(4, 4),
        textcoords="offset points",
        color=TEXT_SECONDARY,
        fontsize=9,
    )
    axes[0].legend(frameon=False, loc="upper right")
    axes[-1].set_xlabel("Shaft speed (rpm)")
    fig.suptitle(
        f"V5 11W motor, {cartridge} cartridge, {volts:g} V supply (simulated dynamometer)",
        color=TEXT_PRIMARY,
        fontsize=11,
    )
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return path

"""True path vs. each localizer's estimate over a scripted drive."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from vexsim.algorithms.localization.runner import OdometryRun

# Reference palette (dataviz skill): categorical slots in fixed order; truth in primary ink.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"


def to_csv(run: OdometryRun) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["time_s", "source", "x_in", "y_in", "heading_deg"])
    sources = {"truth": run.truth, **run.estimates}
    for k, t in enumerate(run.time):
        for name, path in sources.items():
            x, y, h = path[k]
            writer.writerow([f"{t:.3f}", name, f"{x:.3f}", f"{y:.3f}", f"{h:.3f}"])
    return out.getvalue()


def plot(run: OdometryRun, path: str | Path, *, title: str) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if len(run.estimates) > len(SERIES):
        raise ValueError(f"plot at most {len(SERIES)} localizers")
    fig, (ax, err_ax) = plt.subplots(
        2, 1, figsize=(7.5, 9.0), gridspec_kw={"height_ratios": [3, 1.3]}, facecolor=SURFACE
    )
    for a in (ax, err_ax):
        a.set_facecolor(SURFACE)
        a.grid(True, color=GRID, linewidth=0.8)
        a.set_axisbelow(True)
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            a.spines[side].set_color(GRID)
        a.tick_params(colors=TEXT_SECONDARY)

    ax.plot(*run.truth[:, :2].T, color=TEXT_PRIMARY, linewidth=2.5, label="true path")
    finals = []
    for (name, est), color in zip(run.estimates.items(), SERIES, strict=False):
        ax.plot(*est[:, :2].T, color=color, linewidth=2, label=name)
        ax.plot(*est[-1, :2], "o", color=color, markersize=8, markeredgecolor=SURFACE)
        position, _ = run.errors(name)
        err_ax.plot(run.time, position, color=color, linewidth=2, label=name)
        finals.append(float(position[-1]))
    for value, y in zip(finals, _spread(finals, err_ax.get_ylim()), strict=True):
        err_ax.annotate(
            f"{value:.1f} in",
            xy=(run.time[-1], y),
            xytext=(4, 0),
            textcoords="offset points",
            va="center",
            color=TEXT_PRIMARY,
            fontsize=9,
        )
    ax.plot(*run.truth[0, :2], "s", color=TEXT_SECONDARY, markersize=6)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("x (in)", color=TEXT_SECONDARY)
    ax.set_ylabel("y (in)", color=TEXT_SECONDARY)
    ax.legend(frameon=False, loc="best", fontsize=9, labelcolor=TEXT_PRIMARY)
    ax.set_title(title, color=TEXT_PRIMARY, fontsize=11)
    err_ax.set_xlabel("time (s)", color=TEXT_SECONDARY)
    err_ax.set_ylabel("position error (in)", color=TEXT_SECONDARY)
    err_ax.set_xlim(run.time[0], run.time[-1] * 1.08)
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return path


def _spread(values: list[float], ylim: tuple[float, float], gap: float = 0.07) -> list[float]:
    """Label heights near ``values`` but at least ``gap`` of the axis height apart, inside ylim."""
    min_gap = (ylim[1] - ylim[0]) * gap
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
    placed: dict[int, float] = {}
    previous = None
    for i in order:
        y = min(values[i], ylim[1]) if previous is None else min(values[i], previous - min_gap)
        placed[i] = previous = y
    shift = max(0.0, ylim[0] - min(placed.values()))
    return [placed[i] + shift for i in range(len(values))]

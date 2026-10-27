"""Benchmark outputs: trial and summary CSVs, charts, worst-case replays, one HTML report."""

from __future__ import annotations

import base64
import csv
import html
import io
import math
import os
import re
from pathlib import Path

import numpy as np

from vexsim.algorithms.control.paths import spline
from vexsim.bench.metrics import target_of
from vexsim.bench.runner import SUMMARY_METRICS, BenchResult
from vexsim.bench.trial import run_trial

# Reference palette (dataviz skill): categorical slots in fixed order, light surface.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"


def _display(path: str | Path) -> str:
    """A path relative to the working directory when possible, so commands work elsewhere."""
    try:
        return Path(os.path.relpath(path)).as_posix()
    except ValueError:  # another drive on Windows
        return str(path)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def write_csv(path: Path, rows: list[dict]) -> Path:
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in r.items()})
    return path


def _flat_summary(result: BenchResult) -> list[dict]:
    rows = []
    for entry in result.summary():
        row = {
            k: entry[k] for k in ("localizer", "controller", "trials", "success_rate", "timeouts")
        }
        for key, _ in SUMMARY_METRICS:
            stats = entry[key]
            for stat in ("mean", "median", "p95", "max"):
                row[f"{key}_{stat}"] = stats[stat] if stats else ""
        rows.append(row)
    return rows


# --- charts -------------------------------------------------------------------------------------


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=TEXT_SECONDARY, labelsize=8)


def _legend_below(ax) -> None:
    ax.legend(
        frameon=False, fontsize=8, labelcolor=TEXT_PRIMARY, ncol=2,
        loc="upper center", bbox_to_anchor=(0.5, -0.2),
    )  # fmt: skip


def _png(fig) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=120, facecolor=SURFACE)
    import matplotlib.pyplot as plt

    plt.close(fig)
    return buffer.getvalue()


def _ecdf_chart(
    result: BenchResult, key: str, label: str, threshold: float | None = None
) -> bytes | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.2, 4.2), facecolor=SURFACE)
    _style(ax)
    drawn = False
    for (loc, ctrl), color in zip(result.combos(), SERIES, strict=False):
        values = np.sort([r[key] for r in result.rows_for(loc, ctrl)])
        values = values[~np.isnan(values)]
        if len(values) == 0:
            continue
        drawn = True
        ys = np.arange(1, len(values) + 1) / len(values)
        ax.step(values, ys, where="post", color=color, linewidth=2, label=f"{loc} / {ctrl}")
    if not drawn:
        plt.close(fig)
        return None
    if threshold is not None:
        ax.axvline(threshold, color=TEXT_SECONDARY, linewidth=1, linestyle=(0, (4, 3)))
        ax.annotate("tolerance", xy=(threshold, 0.02), xytext=(4, 0), textcoords="offset points",
                    color=TEXT_SECONDARY, fontsize=8)  # fmt: skip
    ax.set_xlabel(label, color=TEXT_SECONDARY)
    ax.set_ylabel("share of trials at or below", color=TEXT_SECONDARY)
    ax.set_ylim(0, 1.02)
    _legend_below(ax)
    fig.tight_layout()
    return _png(fig)


def _scatter_chart(result: BenchResult) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.2, 4.4), facecolor=SURFACE)
    _style(ax)
    for (loc, ctrl), color in zip(result.combos(), SERIES, strict=False):
        rows = result.rows_for(loc, ctrl)
        ax.scatter(
            [r["loc_error_final_in"] for r in rows],
            [r["final_error_in"] for r in rows],
            s=14, color=color, alpha=0.75, edgecolors=SURFACE, linewidths=0.5,
            label=f"{loc} / {ctrl}",
        )  # fmt: skip
    lim = max(ax.get_xlim()[1], ax.get_ylim()[1])
    ax.plot([0, lim], [0, lim], color=TEXT_SECONDARY, linewidth=1, linestyle=(0, (4, 3)))
    ax.annotate("final error = localization error", xy=(lim * 0.55, lim * 0.55), xytext=(6, -12),
                textcoords="offset points", color=TEXT_SECONDARY, fontsize=8)  # fmt: skip
    ax.set_xlabel("localization error at end (in)", color=TEXT_SECONDARY)
    ax.set_ylabel("final position error (in)", color=TEXT_SECONDARY)
    _legend_below(ax)
    fig.tight_layout()
    return _png(fig)


def _worst_case_chart(result: BenchResult, trials: dict) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    combos = result.combos()
    cols = min(len(combos), 2)
    rows = math.ceil(len(combos) / cols)
    fig, axes = plt.subplots(
        rows, cols, figsize=(3.9 * cols, 3.7 * rows), facecolor=SURFACE, squeeze=False
    )
    task = result.loaded.scenario.task
    for ax in axes.flat[len(combos) :]:
        ax.set_visible(False)
    for ax, combo in zip(axes.flat, combos, strict=False):
        _style(ax)
        trial = trials[combo]
        if task.type == "follow":
            ref = spline(task.waypoints, 0.5)
            ax.plot(ref[:, 0], ref[:, 1], color=SERIES[1], linewidth=1.5, label="reference")
        tx, ty, _ = target_of(task, tuple(trial.truth[0]))
        ax.plot(tx, ty, "o", color=SERIES[1], markersize=7, markerfacecolor="none")
        ax.plot(
            trial.truth[:, 0], trial.truth[:, 1], color=TEXT_PRIMARY, linewidth=1.8, label="true"
        )
        ax.plot(
            trial.estimate[:, 0],
            trial.estimate[:, 1],
            color=SERIES[0],
            linewidth=1.2,
            label="estimated",
        )
        ax.set_aspect("equal", adjustable="datalim")
        m = trial.metrics
        ax.set_title(
            f"{combo[0]} / {combo[1]}\nseed {trial.seed}: final {m.final_error_in:.1f} in, "
            f"localization {m.loc_error_final_in:.1f} in",
            color=TEXT_PRIMARY, fontsize=8.5, loc="left",
        )  # fmt: skip
    axes.flat[0].legend(frameon=False, fontsize=7, labelcolor=TEXT_PRIMARY)
    fig.tight_layout()
    return _png(fig)


# --- report -------------------------------------------------------------------------------------


def write_report(result: BenchResult, out_dir: str | Path, *, worst_cases: bool = True) -> Path:
    """Write trials.csv, summary.csv, worst-case telemetry, charts/*.png and report.html."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "trials.csv", result.rows)
    write_csv(out / "summary.csv", _flat_summary(result))

    s = result.loaded.scenario
    tolerance = getattr(s.task, "tolerance_in", None)
    charts = [
        ("Final position error", _ecdf_chart(result, "final_error_in", "final position error (in)", tolerance)),
        ("Localization error at the end", _ecdf_chart(result, "loc_error_final_in", "localization error at end (in)")),
        ("Completion time", _ecdf_chart(result, "completion_time_s", "completion time (s)")),
        ("Path tracking error (RMS)", _ecdf_chart(result, "path_rms_in", "path RMS error (in)")),
        ("Where the final error comes from", _scatter_chart(result)),
    ]  # fmt: skip
    worst_html = ""
    if worst_cases:
        trials = write_worst_cases(result, out)
        replays = [
            (loc, ctrl, trial.seed, worst_case_name(loc, ctrl))
            for (loc, ctrl), trial in trials.items()
        ]
        charts.append(("Worst case of each combination", _worst_case_chart(result, trials)))
        robot = _display(result.loaded.path(s.robot))
        items = "".join(
            f"<li><b>{html.escape(loc)} / {html.escape(ctrl)}</b>: seed {seed}. "
            f"<code>vexsim replay {html.escape(robot)} {html.escape(_display(out / name))}</code></li>"
            for loc, ctrl, seed, name in replays
        )
        worst_html = f"<h2>Worst cases</h2><p>Re-run with full telemetry (runs are deterministic):</p><ul>{items}</ul>"

    chart_dir = out / "charts"
    chart_dir.mkdir(exist_ok=True)
    for title, png in charts:
        if png:
            (chart_dir / f"{slug(title)}.png").write_bytes(png)
    (out / "report.html").write_text(_html(result, charts, worst_html), encoding="utf-8")
    return out / "report.html"


def worst_case_name(localizer: str, controller: str) -> str:
    """The telemetry log of a combination's worst trial, in the report's folder."""
    return f"worst_{slug(localizer)}__{slug(controller)}.csv"


def write_worst_cases(result: BenchResult, out: Path) -> dict:
    """Re-run each combination's worst trial with full telemetry (runs are deterministic)
    and write its log; returns the trials by (localizer, controller)."""
    trials = {}
    controllers = {c.name: c for c in result.loaded.controllers}
    for loc, ctrl in result.combos():
        row = result.worst(loc, ctrl)
        trial = run_trial(
            result.loaded,
            row["seed"],
            loc,
            controllers[ctrl],
            record=True,
            executable=result.executables.get(ctrl),
        )
        trials[(loc, ctrl)] = trial
        trial.telemetry.recorder.write_csv(out / worst_case_name(loc, ctrl))
    return trials


def _fmt(value, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "&ndash;"
    return f"{value:.{digits}f}"


def _wall_contacts(entry: dict) -> str:
    if not _stat(entry, "wall_contacts", "max"):
        return "&ndash;"  # the column only shows when some trial hit a wall
    return _fmt(_stat(entry, "wall_contacts", "mean"), 1)


def _html(result: BenchResult, charts: list[tuple[str, bytes | None]], worst_html: str) -> str:
    s = result.loaded.scenario
    summary = result.summary()
    columns = [
        ("success", lambda e: f"{e['success_rate'] * 100:.0f}%"),
        ("final error mean / p95 (in)", lambda e: _pair(e, "final_error_in")),
        ("heading error p95 (deg)", lambda e: _fmt(_stat(e, "final_heading_error_deg", "p95"), 1)),
        ("completion median (s)", lambda e: _fmt(_stat(e, "completion_time_s", "median"))),
        ("path RMS mean (in)", lambda e: _fmt(_stat(e, "path_rms_in", "mean"))),
        ("localization error mean / p95 (in)", lambda e: _pair(e, "loc_error_final_in")),
        ("energy mean (J)", lambda e: _fmt(_stat(e, "energy_j", "mean"), 0)),
        ("wall contacts mean", _wall_contacts),
        ("timeouts", lambda e: str(e["timeouts"])),
    ]
    columns = [(c, fn) for c, fn in columns if any(fn(e) != "&ndash;" for e in summary)]
    head = "".join(f"<th>{html.escape(c)}</th>" for c, _ in columns)
    body = "".join(
        f"<tr><td>{html.escape(e['localizer'])}</td><td>{html.escape(e['controller'])}</td>"
        + "".join(f"<td class='num'>{fn(e)}</td>" for _, fn in columns)
        + "</tr>"
        for e in summary
    )
    images = "".join(
        f"<figure><figcaption>{html.escape(title)}</figcaption>"
        f"<img alt='{html.escape(title)}' src='data:image/png;base64,{base64.b64encode(png).decode()}'></figure>"
        for title, png in charts
        if png
    )
    r = s.randomize
    randomized = [
        f"true start within &sigma; {r.start_xy_in:g} in, {r.start_heading_deg:g}&deg; of where odometry believes",
    ]
    if r.battery_soc:
        randomized.append(f"battery charge {r.battery_soc[0]:.0%}&ndash;{r.battery_soc[1]:.0%}")
    randomized += [f"{html.escape(k)} {lo:g}&ndash;{hi:g}" for k, (lo, hi) in r.params.items()]
    disturbances = "; ".join(describe_disturbance(d) for d in s.disturbances) or "none"
    seeds = result.seeds
    settings = [
        ("robot", html.escape(s.robot)),
        ("task", describe_task(s.task)),
        ("sensor noise", s.noise or "as configured"),
        ("seeds", f"{len(seeds)} ({seeds[0]}&ndash;{seeds[-1]})" if seeds else "none"),
        (
            "trials",
            f"{len(result.rows)} on {result.workers} worker(s) in {result.wall_time_s:.0f} s",
        ),
        ("varies per seed", "; ".join(randomized)),
        ("disturbances", disturbances),
        ("time limit", f"{s.time_limit_s:g} s"),
    ]
    settings_html = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in settings)
    command = (
        f"vexsim bench {_display(result.scenario_path)} --seeds {len(seeds)} "
        f"--first-seed {seeds[0] if seeds else 0}"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(s.name)} - vexsim benchmark</title>
<style>
:root {{ color-scheme: light; --surface: #fcfcfb; --panel: #f4f3f0; --text: #0b0b0b; --text-2: #52514e; --grid: #e4e3df; --accent: #2a78d6; }}
body {{ margin: 0; background: var(--surface); color: var(--text); font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1000px; margin: 0 auto; padding: 24px 16px 48px; }}
h1 {{ font-size: 24px; margin: 0 0 4px; }} h2 {{ font-size: 18px; margin: 32px 0 8px; }}
p.lead {{ color: var(--text-2); margin-top: 0; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--grid); vertical-align: top; overflow-wrap: anywhere; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.settings th {{ width: 30%; max-width: 160px; color: var(--text-2); font-weight: 500; }}
.wrap {{ overflow-x: auto; }}
figure {{ margin: 20px 0; }} figcaption {{ font-weight: 600; margin-bottom: 6px; }}
img {{ max-width: 100%; height: auto; border: 1px solid var(--grid); border-radius: 6px; }}
code {{ background: var(--panel); padding: 1px 5px; border-radius: 4px; font-size: 12px; word-break: break-all; }}
</style></head>
<body><main>
<h1>{html.escape(s.name)}</h1>
<p class="lead">{html.escape(s.description)}</p>
<table class="settings">{settings_html}</table>
<h2>Summary</h2>
<p>A trial succeeds when the robot finishes within the task tolerance before the time limit. p95 = 95th percentile.</p>
<div class="wrap"><table><thead><tr><th>localizer</th><th>controller</th>{head}</tr></thead><tbody>{body}</tbody></table></div>
<h2>Distributions</h2>
<p>Each curve shows the share of trials (y) that did at least as well as x: further left and higher is better.
In the scatter plot, points far above the diagonal missed the target even though the robot knew where it was
(a control problem); points near it missed because it didn't (a localization problem).</p>
{images}
{worst_html}
<h2>Reproduce</h2>
<p><code>{html.escape(command)}</code></p>
<p>Every trial in <code>trials.csv</code> can be re-run exactly from its seed.</p>
</main></body></html>
"""


def describe_task(task) -> str:
    t = task.type
    if t == "move_to_point":
        return f"move to ({task.x:g}, {task.y:g}), tolerance {task.tolerance_in:g} in"
    if t == "move_to_pose":
        return (
            f"move to ({task.x:g}, {task.y:g}) facing {task.heading:g}&deg;, tolerance "
            f"{task.tolerance_in:g} in / {task.heading_tolerance_deg:g}&deg;"
        )
    if t == "turn_to_heading":
        return f"turn to {task.heading:g}&deg;, tolerance {task.heading_tolerance_deg:g}&deg;"
    if t == "drive":
        return f"drive {task.distance_in:g} in, tolerance {task.tolerance_in:g} in"
    points = " &rarr; ".join(f"({x:g}, {y:g})" for x, y in task.waypoints)
    return f"follow {points}, tolerance {task.tolerance_in:g} in at the end"


def describe_disturbance(d) -> str:
    if d.type == "push":
        fx, fy = d.force_n
        return f"push ({fx:g}, {fy:g}) N for {d.duration_s:g} s at {d.at_s:g} s"
    if d.type == "imu_bias_step":
        which = f"IMU {d.port}" if d.port is not None else "IMU"
        return f"{which} gyro bias jumps {d.deg_per_s:g}&deg;/s at {d.at_s:g} s"
    return f"tracking wheel {d.port} lifts off for {d.duration_s:g} s at {d.at_s:g} s"


def _stat(entry: dict, key: str, stat: str):
    values = entry.get(key)
    return values[stat] if values else None


def _pair(entry: dict, key: str) -> str:
    return f"{_fmt(_stat(entry, key, 'mean'))} / {_fmt(_stat(entry, key, 'p95'))}"

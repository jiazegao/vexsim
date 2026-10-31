"""A calibration's report, and its changes to the robot's YAML (phase 14.4).

    SESSION/report/
      report.md       each step: what it found, before and after, which values the logs pin
                      down, its notes and warnings; whether the held-out run matches within
                      the sensors' noise; the drive model for the robot's routes
      changes.yaml    what ``--apply`` writes into the robot config
      *.png           the logs against their replays, before and after (with matplotlib)

``changes(config, calibration)`` lists what to write: each value the logs pin down that
differs from the config's by more than half its tolerance (the rest the report shows, and
says why it isn't written). ``apply_changes(text, ...)`` writes them into the robot YAML's
text, every comment kept, with a comment naming the session.
"""

from __future__ import annotations

import datetime
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from vexsim.app.yamledit import Change, apply
from vexsim.calibration.feedforward import drive_section
from vexsim.calibration.fit import UNITS
from vexsim.calibration.session_fit import Calibration, Step, Value
from vexsim.config.robot import RobotConfig

STAMP = "# Calibrated from session "  # the comment --apply leaves (one, the latest)


@dataclass
class Write:
    """One change to the robot's YAML: where, what, and the value it comes from."""

    location: str  # as yamledit takes it: overrides["motor.free_current_a"], sensors[6].scale_error
    value: Any
    value_of: Value


def _significant(v: Value) -> bool:
    if not math.isfinite(v.before):
        return True
    margin = 0.5 * v.tolerance if math.isfinite(v.tolerance) else 0.0
    return abs(v.after - v.before) > margin


def why_not(v: Value) -> str:
    """Why a value isn't written ('' if it is)."""
    if not v.pinned:
        if not math.isfinite(v.uncertainty):
            return "not written: the logs can't tell it"
        return f"not written: the logs don't pin it down (+/-{v.uncertainty:.3g})"
    if not _significant(v):
        return "not written: the same as the config's, as near as the logs tell"
    return ""


def changes(config: RobotConfig, calibration: Calibration) -> list[Write]:
    """What to write into the robot's YAML: the values the logs pin down that changed."""
    sensors = {s.port: i for i, s in enumerate(config.sensors)}
    wheels = {w.name: i for i, w in enumerate(config.drivetrain.wheels)}
    out: list[Write] = []
    for v in calibration.values():
        if why_not(v):
            continue
        parts = v.key.split(".")
        if parts[0] == "wheels" and parts[-1] == "diameter_in":  # wheels.<group>.diameter_in
            group = config.drivetrain.gearing[parts[1]]
            for name in group.wheels:
                out.append(
                    Write(f"drivetrain.wheels[{wheels[name]}].diameter_in", float(v.after), v)
                )
        elif parts[0] == "sensors":  # sensors.<port>.<field...>
            index = sensors[int(parts[1])]
            path = ".".join(parts[2:])
            if path == "tracking_wheel.pos_in":
                pos = calibration.tracking[int(parts[1])]["pos_in"]
                out.append(Write(f"sensors[{index}].{path}", [float(p) for p in pos], v))
            else:
                out.append(Write(f"sensors[{index}].{path}", float(v.after), v))
        else:
            out.append(Write(f'overrides["{v.key}"]', float(v.after), v))
    return out


def apply_changes(text: str, writes: Sequence[Write], session: str, when: str) -> str:
    """The robot YAML's text with the changes written in, its comments kept, and a comment
    at the top naming the session (in place of an earlier one)."""
    newline = "\r\n" if "\r\n" in text else "\n"
    loaded = yaml.safe_load(text) or {}
    edits: list[Change] = []
    section: list[Write] = []  # overrides for a section the file doesn't have yet
    for w in writes:
        if w.location.startswith("overrides[") and not loaded.get("overrides"):
            section.append(w)
        else:
            edits.append(Change("set", w.location, w.value))
    if section and "overrides" in loaded:
        edits.insert(0, Change("remove", "overrides"))  # an empty one: written anew below
    text = apply(text, edits) if edits else text
    if section:
        block = ["overrides:"] + [f"  {_key(w.location)}: {_scalar(w.value)}" for w in section]
        text = text.rstrip("\r\n") + newline + newline + newline.join(block) + newline
    stamp = f"{STAMP}{session} on {when} (vexsim calibrate --apply)"
    lines = text.split(newline)
    lines = [line for line in lines if not line.startswith(STAMP)]
    at = 0
    while at < len(lines) and lines[at].startswith("#"):
        at += 1  # after the file's opening comments
    lines.insert(at, stamp)
    return newline.join(lines)


def _key(location: str) -> str:
    """The override key in a location: overrides["motor.voltage_cap"] -> motor.voltage_cap."""
    return location.removeprefix('overrides["').removesuffix('"]')


def _scalar(value: Any) -> str:
    return yaml.safe_dump(value, default_flow_style=True).splitlines()[0].removesuffix(" ...")


# --- the report -------------------------------------------------------------------------------


def _number(value: float) -> str:
    if not math.isfinite(value):
        return "?"
    if value == 0:
        return "0"
    if abs(value) >= 100:
        return f"{value:.0f}"
    return f"{value:.4g}"


def _values_table(step: Step) -> list[str]:
    if not step.values:
        return []
    lines = [
        "| Value | Before | After | Known to | Pinned down | |",
        "|---|---:|---:|---:|:---:|---|",
    ]
    for v in step.values:
        known = f"±{_number(v.uncertainty)}" if math.isfinite(v.uncertainty) else "?"
        pinned = "yes" if v.pinned else "no"
        note = "; ".join(x for x in (why_not(v), v.note) if x)
        before, after = _number(v.before), _number(v.after)
        lines.append(f"| `{v.key}` | {before} | {after} | {known} | {pinned} | {note} |")
    return lines


def _rms_lines(step: Step) -> list[str]:
    if not step.rms:
        return []
    shown = ", ".join(
        f"{g} {_number(b)} → {_number(a)} {UNITS.get(g, '')}" for g, (b, a) in step.rms.items()
    )
    return [f"Simulated against logged (RMS), before → after: {shown}."]


def report_text(
    config: RobotConfig,
    calibration: Calibration,
    writes: Sequence[Write],
    plots: dict[str, Path],
    *,
    when: str,
) -> str:
    c = calibration
    lines = [f"# Calibration of {c.robot}", ""]
    lines.append(f"Session `{c.session.name}`, fitted by `vexsim calibrate` on {when}.")
    lines.append("")
    if c.held_out is not None:
        h = c.held_out
        shown = ", ".join(
            f"{g} {_number(h.rms[g])} {UNITS.get(g, '')} (noise {_number(h.noise[g])})"
            for g in h.rms
            if g in h.noise
        )
        verdict = "matches" if h.matches else "**doesn't match**"
        lines.append(
            f"The held-out run ({h.run}), which the fit didn't use, {verdict} within the "
            f"sensors' noise: {shown}."
        )
        lines.append("")
    if c.warnings:
        lines.append("## Warnings")
        lines.append("")
        lines += [f"- {w}" for w in c.warnings]
        lines.append("")
    lines.append("## What --apply writes")
    lines.append("")
    if writes:
        lines += ["| Where | Value |", "|---|---:|"]
        for w in writes:
            value = w.value if isinstance(w.value, list) else f"{w.value:.6g}"
            lines.append(f"| `{w.location}` | {value} |")
        lines.append("")
        lines.append(
            "Write them into the robot config with `vexsim calibrate ROBOT.yaml SESSION --apply` "
            "(its comments stay)."
        )
    else:
        lines.append("Nothing: the logs agree with the robot config as it is.")
    lines.append("")
    if c.drive is not None:
        lines.append("## The drive model, for the robot's routes")
        lines.append("")
        lines.append(f"{c.drive.describe()}. Add to the robot's routes:")
        lines.append("")
        lines.append(f"    {drive_section(c.drive)}")
        lines.append("")
    for number, step in enumerate(c.steps, 1):
        lines.append(f"## {number}. {step.name}")
        lines.append("")
        if step.runs:
            lines.append("From " + ", ".join(f"`{r}`" for r in step.runs) + ".")
            lines.append("")
        if step.skipped:
            lines.append(f"Skipped: {step.skipped}.")
            lines.append("")
            continue
        table = _values_table(step)
        if table:
            lines += [*table, ""]
        rms = _rms_lines(step)
        if rms:
            lines += [*rms, ""]
        for note in step.notes:
            lines.append(f"- {note}")
        for warning in step.warnings:
            lines.append(f"- **Warning:** {warning}")
        if step.notes or step.warnings:
            lines.append("")
        for title, path in plots.items():
            if title.startswith(f"{number}."):
                lines += [f"![{title}]({path.name})", ""]
    return "\n".join(lines).rstrip() + "\n"


def changes_yaml(calibration: Calibration, writes: Sequence[Write], when: str) -> str:
    data: dict[str, Any] = {
        "robot": calibration.robot,
        "session": calibration.session.name,
        "fitted": when,
        "changes": {w.location: w.value for w in writes},
    }
    if calibration.drive is not None:
        data["drive"] = drive_section(calibration.drive).removeprefix("drive: ")
    head = "# What vexsim calibrate --apply writes into the robot config (report.md says why)\n"
    return head + yaml.safe_dump(data, sort_keys=False, width=100, default_flow_style=False)


def write_report(
    config: RobotConfig,
    calibration: Calibration,
    folder: str | Path,
    *,
    when: str | None = None,
) -> tuple[Path, list[Write]]:
    """Write report.md, changes.yaml and the plots into ``folder``: report.md's path, and the
    changes."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    when = when or datetime.date.today().isoformat()
    writes = changes(config, calibration)
    plots = _plots(config, calibration, folder)
    (folder / "changes.yaml").write_text(
        changes_yaml(calibration, writes, when), encoding="utf-8", newline="\n"
    )
    path = folder / "report.md"
    path.write_text(
        report_text(config, calibration, writes, plots, when=when), encoding="utf-8", newline="\n"
    )
    return path, writes


def _plots(config: RobotConfig, calibration: Calibration, folder: Path) -> dict[str, Path]:
    """Each step's plots (with matplotlib; none without it), by a title starting with its
    step's number."""
    try:
        import matplotlib  # noqa: F401
    except ModuleNotFoundError:
        return {}
    from vexsim.viz import calibration as cal_plot

    out: dict[str, Path] = {}
    for number, step in enumerate(calibration.steps, 1):
        slug = re.sub(r"[^a-z0-9]+", "_", step.name.split(":")[0].lower()).strip("_")
        if step.replays and step.name.startswith("Free spin"):
            name, log, before, after = step.replays[0]
            title = f"{number}. {name}: logged against simulated"
            out[title] = cal_plot.plot(
                config, log, before, after, folder / f"{slug}.png", title=title.split(". ", 1)[1]
            )
        if step.readings:
            title = f"{number}. distance readings against what each should have read"
            out[title] = _plot_readings(step, folder / "distance.png")
    held = calibration.held_out
    if held is not None:
        number = next(
            (n for n, s in enumerate(calibration.steps, 1) if s.name.startswith("Drive")), 0
        )
        title = f"{number}. {held.run} (held out): logged against simulated"
        out[title] = cal_plot.plot(
            calibration.config,
            held.log,
            None,
            held.sim,
            folder / "held_out.png",
            title=title.split(". ", 1)[1],
        )
    return out


def _plot_readings(step: Step, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from vexsim.viz.odometry import GRID, SERIES, SURFACE, TEXT_PRIMARY, TEXT_SECONDARY

    readings = list(step.readings.values())
    fig, axes = plt.subplots(
        len(readings), 1, figsize=(8.0, 1.8 * len(readings) + 0.8), sharex=False, facecolor=SURFACE
    )
    axes = [axes] if len(readings) == 1 else list(axes)
    for ax, r in zip(axes, readings, strict=True):
        ax.set_facecolor(SURFACE)
        ax.grid(True, color=GRID, linewidth=0.8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=TEXT_SECONDARY, labelsize=8)
        x = range(len(r.reading))
        ax.plot(x, r.true_mm, color=TEXT_PRIMARY, linewidth=1.0, label="should read")
        ax.plot(x, r.reading, ".", color=SERIES[0], markersize=2.5, label="read")
        missed = [i for i in x if r.reading[i] != r.reading[i] and r.true_mm[i] == r.true_mm[i]]
        ax.plot(
            missed,
            [r.true_mm[i] for i in missed],
            "x",
            color=SERIES[1],
            markersize=3,
            label="missed",
        )
        ax.set_title(
            f"port {r.port}, mm (every 10 ms of the sweeps)",
            color=TEXT_PRIMARY,
            fontsize=9,
            loc="left",
        )
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        ncol=3,
        frameon=False,
        fontsize=8,
        labelcolor=TEXT_PRIMARY,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(path, dpi=100, facecolor=SURFACE)
    plt.close(fig)
    return path

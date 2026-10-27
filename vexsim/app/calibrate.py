"""The Calibrate page: ``vexsim calibration-routine`` and ``vexsim calibrate`` for the UI.

First the calibration routine goes into a PROS project (two files), for the real robot
to drive while it logs what its motors and sensors read; then a job fits the simulator's
physics parameters to that log. A fit's result goes to the workspace's
.vexsim/calibrations/<id>/: what the page shows in result.json, beside the fitted values
as overrides.yaml and the simulation's own log as simulated.csv.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from vexsim.app.chartdata import every, rounded
from vexsim.app.workspace import Workspace

if TYPE_CHECKING:
    from vexsim.app.jobs import Report
    from vexsim.config.robot import RobotConfig

MAX_POINTS = 3000  # samples per chart, at most


def routine_plan(config: RobotConfig, project: Path, root: Path) -> dict:
    """What adding the routine to ``project`` does: the files it writes (and whether each
    is there already, as written for this robot or otherwise), and the maneuvers."""
    from vexsim.calibration.cpp import generate, routine_files
    from vexsim.calibration.routine import schedule, standard_routine

    workspace = Workspace(root)
    texts = generate(config)
    files = []
    for path, text in zip(routine_files(project), texts, strict=True):
        if not path.is_file():
            state = "new"
        else:
            same = path.read_text(encoding="utf-8", errors="replace") == text
            state = "same" if same else "different"
        files.append({"path": workspace.relative(path), "state": state})
    plan = schedule(config, standard_routine(config))
    return {
        "project": workspace.relative(project),
        "files": files,
        "seconds": plan[-1][0] / 1000,
        "steps": [
            {"name": step.name, "start_s": start / 1000, "seconds": step.seconds}
            for start, step, _ in plan[:-1]
        ],
    }


def write_routine(config: RobotConfig, project: Path, root: Path) -> dict:
    """Add the routine to ``project``; returns its plan, now with every file the same."""
    from vexsim.calibration.cpp import write_routine as write

    write(config, project)
    return routine_plan(config, project, root)


def parameters(config: RobotConfig) -> list[dict]:
    """The parameters a fit adjusts unless told otherwise, with their values now."""
    from vexsim.calibration.fit import current_value, default_parameters

    return [
        {"name": name, "value": current_value(config, name), "overridden": name in config.overrides}
        for name in default_parameters(config)
    ]


def calibrate(params: dict, report: Report) -> dict:
    """``vexsim calibrate`` for the page. Params: ``robot`` and ``log`` (files), their
    workspace paths ``robot_name`` and ``log_name``, ``results`` (where results go),
    ``fit`` (parameter names, or None for the default ones), ``compare_only``,
    ``max_iterations`` and ``workers``."""
    from vexsim.app import results
    from vexsim.app.analyze import robot_config
    from vexsim.calibration.fit import UNITS, compare, fit, worker_count
    from vexsim.calibration.log import RobotLog

    config = robot_config(params)
    log_name = params.get("log_name") or Path(params["log"]).name
    try:
        log = RobotLog.read(params["log"])
    except (OSError, ValueError) as exc:
        raise ValueError(f"{log_name}: {exc}") from None
    facts = _facts(config, log)
    report(f"Robot log: {facts['rows']} rows ({facts['seconds']:.1f} s): {facts['found']}")
    store = Path(params["results"])
    result_id, folder = results.new_result(store)
    try:
        before = after = None
        table, direct, rms = [], [], []
        overrides: dict[str, float] = {}
        if params.get("compare_only"):
            values, after = compare(config, log)
            rms = [
                {"group": g, "unit": UNITS[g], "before": None, "after": value}
                for g, value in values.items()
            ]
            replays = 1
        else:
            fitted = fit(
                config,
                log,
                params.get("fit") or None,
                max_iterations=int(params.get("max_iterations", 12)),
                workers=worker_count(params.get("workers")),
                progress=report,
            )
            before, after = fitted.sim_before, fitted.sim_after
            table = [
                {
                    "name": name,
                    "before": fitted.before[name],
                    "after": fitted.after[name],
                    "uncertainty": fitted.uncertainty[name],
                }
                for name in fitted.parameters
            ]
            direct = [
                {"name": name, "before": config.overrides.get(name), "after": value}
                for name, value in fitted.direct.items()
            ]
            rms = [
                {"group": g, "unit": UNITS[g], "before": fitted.rms_before[g], "after": v}
                for g, v in fitted.rms_after.items()
            ]
            overrides = fitted.overrides
            replays = fitted.replays
        if overrides:
            text = "overrides:\n" + "".join(f"  {k}: {v:g}\n" for k, v in overrides.items())
            (folder / "overrides.yaml").write_text(text, encoding="utf-8")
        after.write(folder / "simulated.csv")
        robot_name = params.get("robot_name") or Path(params["robot"]).name
        fitted_text = (
            "compared, nothing fitted"
            if params.get("compare_only")
            else f"{len(table)} parameter{'s' if len(table) != 1 else ''} fitted"
        )
        about = results.write_result(
            folder,
            "calibrations",
            f"{Path(log_name).name} on {Path(robot_name).name}",
            f"{fitted_text} in {replays} replays",
            {
                "robot": robot_name,
                "log": log_name,
                "log_facts": facts,
                "compare_only": bool(params.get("compare_only")),
                "parameters": table,
                "direct": direct,
                "rms": rms,
                "overrides": overrides,
                "replays": replays,
                "panels": _panels(config, log, before, after),
                "files": sorted(p.name for p in folder.iterdir() if p.suffix in (".csv", ".yaml")),
            },
        )
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    results.prune(store)
    return {"id": about["id"]}


def _facts(config: RobotConfig, log) -> dict:
    kinds = [
        (len(log.ports("m")), "motor"),
        (len(log.ports("r")), "rotation sensor"),
        (len(log.ports("imu")), "IMU"),
        (len(log.ports("gps")), "GPS"),
    ]
    drive = {abs(p) for g in config.drivetrain.gearing.values() for p in g.motors}
    return {
        "rows": len(log),
        "seconds": float((log.time_ms[-1] - log.time_ms[0]) / 1000) if len(log) else 0.0,
        "found": ", ".join(f"{n} {name}{'s' if n > 1 else ''}" for n, name in kinds if n),
        "skipped_lines": log.skipped_lines,
        "ignored_motors": sorted(set(log.ports("m")) - drive),
    }


def _panels(config: RobotConfig, log, before, after) -> list[dict]:
    """The charts: each drive side's first motor, then each tracking wheel and IMU, as the
    robot logged them and as the simulation replayed them (before and after the fit)."""
    from vexsim.calibration.fit import UNITS, signal_of
    from vexsim.viz.calibration import panels

    out = []
    time = log.time_s
    for label, channel in panels(config, log):
        logged = signal_of(log, channel)
        keep = every(len(logged), MAX_POINTS)
        series = {"robot log": logged}
        if before is not None and channel.name in before:
            series["simulated, before the fit"] = signal_of(before, channel)
        if after is not None and channel.name in after:
            series["simulated"] = signal_of(after, channel)
        out.append(
            {
                "title": label,
                "unit": UNITS[channel.group],
                "time_s": rounded(time[len(time) - len(logged) :][keep], 3),
                "series": [
                    {"name": name, "values": rounded(values[keep], 3)}
                    for name, values in series.items()
                ],
            }
        )
    return out

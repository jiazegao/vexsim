"""The Bench page: a scenario described before it runs, and ``vexsim bench`` as a job.

A benchmark's result goes to the workspace's .vexsim/bench/<id>/ (see results.py): what
the page shows in result.json, beside the files ``vexsim bench`` writes (trials.csv,
summary.csv, each combination's worst trial as a telemetry log, and with matplotlib,
charts and report.html).
"""

from __future__ import annotations

import html
import importlib.util
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from vexsim.app.workspace import Workspace

if TYPE_CHECKING:
    from vexsim.app.jobs import Report


class ScenarioProblem(ValueError):
    """A scenario that doesn't load; ``issues`` as ``vexsim bench`` prints them."""

    def __init__(self, message: str, issues: list):
        super().__init__(message)
        self.issues = issues


def describe_scenario(path: Path, root: Path) -> dict:
    """What the page shows about a scenario before it runs (raises ScenarioProblem)."""
    from vexsim.bench.report import describe_disturbance, describe_task
    from vexsim.bench.scenario import CONTROLLER_KINDS, LoadedScenario, validate_scenario
    from vexsim.bench.trial import available_localizers
    from vexsim.config.loader import validate_robot

    workspace = Workspace(root)
    checked = validate_scenario(path)
    if not checked.ok or checked.config is None:
        raise ScenarioProblem(f"{workspace.relative(path)}: invalid scenario", checked.issues)
    loaded = LoadedScenario(checked.config, path.resolve().parent)
    s = loaded.scenario
    robot = validate_robot(loaded.path(s.robot))
    if not robot.ok or robot.config is None:
        message = f"{workspace.relative(loaded.path(s.robot))}: invalid robot config"
        raise ScenarioProblem(message, robot.issues)
    default_kind = CONTROLLER_KINDS[s.task.type][0]
    return {
        "name": s.name,
        "description": s.description,
        "path": workspace.relative(path),
        "robot": workspace.relative(loaded.path(s.robot)),
        "field": workspace.relative(loaded.path(s.field)) if s.field else None,
        "task": html.unescape(describe_task(s.task)),
        "tolerance_in": getattr(s.task, "tolerance_in", None),
        "time_limit_s": s.time_limit_s,
        "noise": s.noise,
        "disturbances": [html.unescape(describe_disturbance(d)) for d in s.disturbances],
        "randomized": _randomized(s),
        "localizers": available_localizers(loaded, robot.config),
        "controllers": [
            {"name": c.name, "kind": c.kind or default_kind, "project": c.project}
            for c in loaded.controllers
        ],
    }


def _randomized(s) -> list[str]:
    """What each seed changes, in words."""
    r = s.randomize
    out = []
    if r.start_xy_in or r.start_heading_deg:
        out.append(
            f"where the robot really starts: off by {r.start_xy_in:g} in and "
            f"{r.start_heading_deg:g}° (standard deviations)"
        )
    if r.battery_soc:
        low, high = r.battery_soc
        out.append(f"battery charge {low:.0%} to {high:.0%}")
    for key, (low, high) in r.params.items():
        out.append(f"{key} {low:g} to {high:g}")
    return out


def run_benchmark(params: dict, report: Report) -> dict:
    """``vexsim bench`` for the page: progress per trial, then the report. Params:
    ``scenario`` (a file), ``root`` (the workspace), ``results`` (where results go),
    ``seeds``, ``first_seed``, ``workers``, ``localizers``, ``controllers``, ``worst_cases``."""
    from vexsim.app import results
    from vexsim.bench.report import worst_case_name, write_csv, write_report, write_worst_cases
    from vexsim.bench.runner import SUMMARY_METRICS, run_bench

    root = Path(params["root"])
    path = Path(params["scenario"])
    scenario = describe_scenario(path, root)
    first, count = int(params.get("first_seed", 0)), int(params.get("seeds", 20))
    store = Path(params["results"])
    result_id, folder = results.new_result(store)
    try:
        report(f"Running {scenario['name']} with {count} seed{'s' if count != 1 else ''}")
        bench = run_bench(
            path,
            list(range(first, first + count)),
            localizers=params.get("localizers") or None,
            controllers=params.get("controllers") or None,
            workers=params.get("workers") or None,
            progress=report.progress,
        )
        report(f"{len(bench.rows)} trials in {bench.wall_time_s:.1f} s on {bench.workers} workers")
        worst_cases = params.get("worst_cases", True)
        if worst_cases:
            report("Re-running the worst trial of each combination with full telemetry")
        has_charts = importlib.util.find_spec("matplotlib") is not None
        if has_charts:
            write_report(bench, folder, worst_cases=worst_cases)
        else:
            write_csv(folder / "trials.csv", bench.rows)
            if worst_cases:
                write_worst_cases(bench, folder)
            report('The HTML report needs matplotlib: pip install -e ".[viz]"')
        combos = bench.combos()
        worst = [
            {
                "localizer": loc,
                "controller": ctrl,
                "seed": bench.worst(loc, ctrl)["seed"],
                "file": worst_case_name(loc, ctrl),
            }
            for loc, ctrl in combos
        ]
        files = sorted(p.name for p in folder.iterdir() if p.suffix in (".csv", ".html"))
        trials = len(bench.rows)
        about = results.write_result(
            folder,
            "bench",
            scenario["name"],
            f"{_count(len(bench.localizers), 'localizer')} x "
            f"{_count(len(bench.controllers), 'controller')} x {_count(count, 'seed')}: "
            f"{trials} trials in {bench.wall_time_s:.0f} s",
            {
                "scenario": scenario,
                "first_seed": first,
                "seeds": count,
                "workers": bench.workers,
                "wall_time_s": bench.wall_time_s,
                "metrics": [{"key": k, "label": label} for k, label in SUMMARY_METRICS],
                "combos": [{"localizer": loc, "controller": ctrl} for loc, ctrl in combos],
                "summary": [
                    {
                        **{k: e[k] for k in ("localizer", "controller", "trials", "timeouts")},
                        "success_rate": e["success_rate"],
                        "stats": {key: e[key] for key, _ in SUMMARY_METRICS},
                    }
                    for e in bench.summary()
                ],
                "rows": bench.rows,
                "worst": worst if worst_cases else [],
                "report": "report.html" if has_charts else None,
                "files": files,
                "command": _command(scenario["path"], first, count, params),
            },
        )
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    results.prune(store)
    return {"id": about["id"]}


def _command(scenario: str, first: int, count: int, params: dict) -> str:
    from vexsim.app.runspec import quote_arg

    args = ["vexsim", "bench", scenario, "--seeds", str(count)]
    if first:
        args += ["--first-seed", str(first)]
    for flag in ("localizers", "controllers"):
        if params.get(flag):
            args += [f"--{flag}", ",".join(params[flag])]
    if not params.get("worst_cases", True):
        args.append("--no-worst")
    return " ".join(quote_arg(a) for a in args)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"

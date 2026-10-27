"""Sweeps: saved runs run many times over, and measured. The workspace's
``.vexsim/sweeps.yaml`` keeps them.

A sweep runs each of its saved runs (from .vexsim/launch.yaml) once per variation (values
of environment variables the robot code reads) and seed, with the robot put down a little
off its start as a hand would, headless and in parallel. It measures how far the robot
code's pose was from the truth while the program ran. Team 1239E's evaluation of its
localization (examples/scripts/evaluate_1239e.py) is one::

    version: 1
    sweeps:
      - name: "1239E: localization"
        runs: ["1239E: Left 40", "1239E: Right 40", ...]
        vary: {VEXSIM_TRACKING: [rcl+mcl, odom]}
        seeds: 3
        placement_sd: [0.5, 0.5, 1]
        max_seconds: 75

Placement errors are drawn as that script draws them (numpy's ``default_rng([seed,
1239])``), so a seed puts the robot down the same way for every run and variation, and
the two agree. A sweep's result goes to the workspace's .vexsim/sweeps/<id>/ (see
results.py): every trial's numbers and its error over time in result.json, and
trials.csv.
"""

from __future__ import annotations

import csv
import itertools
import math
import os
import shutil
import time
from concurrent.futures import as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import numpy as np
import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from vexsim.app.launch import Inline, dump_yaml, read_configurations
from vexsim.app.runspec import RunSpec
from vexsim.config.yaml_io import parse_yaml

if TYPE_CHECKING:
    from vexsim.app.jobs import Report
    from vexsim.app.launch import RunConfiguration

SWEEPS_FILE = ".vexsim/sweeps.yaml"
VERSION = 1
HEADER = """\
# Sweeps for `vexsim ui`: each runs saved runs (.vexsim/launch.yaml) once per variation of
# their environment variables and per seed, puts the robot down a little off its start
# (placement_sd: x, y in inches, heading in degrees), and measures how far the robot
# code's pose is from the truth. The app rewrites this file when you save from it
# (comments here aren't kept).
"""
PLACEMENT_STREAM = 1239  # the random stream of placement errors, as evaluate_1239e.py's
ACTIVE_PHASES = ("autonomous", "opcontrol")  # when the program runs the robot
TRACE_STEP_MS = 100  # the error over time, every this often
MAX_TRIALS = 5000


def _text(value: Any) -> Any:
    """Values YAML reads as numbers or booleans, as the text a program reads from its
    environment."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value) if isinstance(value, int | float) else value


EnvName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
EnvValue = Annotated[str, BeforeValidator(_text)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Sweep(BaseModel):
    """A sweep, as .vexsim/sweeps.yaml keeps it."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=80)]
    description: str = ""
    runs: Annotated[list[str], Field(min_length=1)]  # saved runs' names
    vary: dict[EnvName, Annotated[list[EnvValue], Field(min_length=1)]] = Field(
        default_factory=dict
    )
    seeds: Annotated[int, Field(ge=1, le=1000)] = 3
    first_seed: Annotated[int, Field(ge=0)] = 0
    placement_sd: tuple[NonNegative, NonNegative, NonNegative] = (0.0, 0.0, 0.0)
    max_seconds: Annotated[float, Field(gt=0, le=3600)] = 60.0


class SweepError(ValueError):
    """A sweep that can't run as it is, or a sweeps file that can't be used."""


# --- the file ---------------------------------------------------------------------------------


def read_sweeps(root: Path) -> list[Sweep]:
    """The workspace's sweeps (none without a file); raises SweepError when the file is
    there but broken."""
    path = Path(root) / SWEEPS_FILE
    if not path.is_file():
        return []
    try:
        data = parse_yaml(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SweepError(f"{SWEEPS_FILE}: {exc}") from None
    if data is None:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("sweeps", []), list):
        raise SweepError(f"{SWEEPS_FILE}: expected a list under 'sweeps'")
    sweeps = []
    for i, item in enumerate(data.get("sweeps") or []):
        try:
            sweeps.append(Sweep.model_validate(item))
        except ValidationError as exc:
            error = exc.errors()[0]
            where = ".".join(str(part) for part in error["loc"])
            name = item.get("name") if isinstance(item, dict) else None
            label = f"sweep {i + 1}" + (f" ({name})" if name else "")
            raise SweepError(
                f"{SWEEPS_FILE}: {label}: {where + ': ' if where else ''}{error['msg']}"
            ) from None
    _check_names(sweeps)
    return sweeps


def write_sweeps(root: Path, sweeps: list[Sweep]) -> Path:
    """Save the sweeps (creating .vexsim/ if needed); returns the file."""
    _check_names(sweeps)
    path = Path(root) / SWEEPS_FILE
    entries = []
    for sweep in sweeps:
        entry: dict[str, Any] = {"name": sweep.name}
        if sweep.description:
            entry["description"] = sweep.description
        entry["runs"] = list(sweep.runs)
        if sweep.vary:
            entry["vary"] = {key: Inline(values) for key, values in sweep.vary.items()}
        entry["seeds"] = sweep.seeds
        if sweep.first_seed:
            entry["first_seed"] = sweep.first_seed
        if any(sweep.placement_sd):
            entry["placement_sd"] = Inline(_number(v) for v in sweep.placement_sd)
        entry["max_seconds"] = _number(sweep.max_seconds)
        entries.append(entry)
    text = dump_yaml({"version": VERSION, "sweeps": entries})
    head, *rest = text.split("\n  - name:")  # a blank line between sweeps
    text = HEADER + head
    text += "".join(("\n\n" if i else "\n") + "  - name:" + e for i, e in enumerate(rest))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _check_names(sweeps: list[Sweep]) -> None:
    seen: set[str] = set()
    for sweep in sweeps:
        key = sweep.name.strip().casefold()
        if key in seen:
            raise SweepError(f"two sweeps are named {sweep.name!r}")
        seen.add(key)


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


# --- trials -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Trial:
    index: int
    run: str  # the saved run's name
    variation: dict[str, str]  # the environment variables it sets
    seed: int
    spec: RunSpec  # what runs: the saved run, varied, with its seed and placement


def variations(sweep: Sweep) -> list[dict[str, str]]:
    """Every combination of the varied values, in order ([{}] when nothing varies)."""
    keys = list(sweep.vary)
    product = itertools.product(*sweep.vary.values())
    return [dict(zip(keys, values, strict=True)) for values in product]


def label(variation: dict[str, str]) -> str:
    """What a variation is called: its value, when one variable varies."""
    if not variation:
        return "as saved"
    if len(variation) == 1:
        return next(iter(variation.values()))
    return ", ".join(f"{key}={value}" for key, value in variation.items())


def placement(
    start: tuple[float, float, float], seed: int, sd: tuple[float, float, float]
) -> tuple[float, float, float]:
    """Where the robot really starts: ``start`` plus a hand placement error, the same for
    every run and variation with this seed."""
    if not any(sd):
        return start
    dx, dy, dh = np.random.default_rng([seed, PLACEMENT_STREAM]).normal(0.0, sd)
    return (start[0] + float(dx), start[1] + float(dy), start[2] + float(dh))


def expand(sweep: Sweep, configurations: list[RunConfiguration]) -> list[Trial]:
    """The sweep's trials: each run, each variation, each seed (raises SweepError)."""
    saved = {c.name: c for c in configurations}
    missing = [name for name in sweep.runs if name not in saved]
    if missing:
        names = ", ".join(repr(name) for name in missing)
        raise SweepError(f"no saved run named {names} (they're in .vexsim/launch.yaml)")
    if len(set(sweep.runs)) != len(sweep.runs):
        raise SweepError("a saved run is listed twice")
    combos = variations(sweep)
    total = len(sweep.runs) * len(combos) * sweep.seeds
    if total > MAX_TRIALS:
        raise SweepError(f"that's {total} trials; a sweep runs at most {MAX_TRIALS}")
    trials = []
    seeds = range(sweep.first_seed, sweep.first_seed + sweep.seeds)
    for run, variation, seed in itertools.product(sweep.runs, combos, seeds):
        base = saved[run]
        spec = RunSpec.model_validate(base.model_dump(exclude={"name"})).model_copy(
            update={
                "env": {**base.env, **variation},
                "seed": seed,
                "start": placement(base.start, seed, sweep.placement_sd),
            }
        )
        trials.append(Trial(len(trials), run, variation, seed, spec))
    return trials


# --- one trial, in a worker process --------------------------------------------------------


def measure(rows: list[list]) -> dict[str, Any]:
    """How far the robot code's pose was from the truth while its program ran (the
    autonomous and driver periods' telemetry rows that have an estimate): as
    ``Recorder.pose_error`` has it, and every TRACE_STEP_MS from the first estimate on."""
    active = [r for r in rows if r[1] in ACTIVE_PHASES]
    estimated = [r for r in active if not math.isnan(r[5])]
    out: dict[str, Any] = {
        "seconds": active[-1][0] - active[0][0] if active else None,
        "end": [active[-1][2], active[-1][3], active[-1][4]] if active else None,
        "end_estimate": None,
        "mean_in": None,
        "max_in": None,
        "final_in": None,
        "max_deg": None,
        "trace": [],
    }
    if not estimated:
        return out
    begin = estimated[0][0]
    distance = [math.hypot(r[2] - r[5], r[3] - r[6]) for r in estimated]
    turn = [abs((r[4] - r[7] + 180.0) % 360.0 - 180.0) for r in estimated]
    at = {round((r[0] - begin) * 1000): error for r, error in zip(estimated, distance, strict=True)}
    steps = max(at) // TRACE_STEP_MS + 1
    trace = [at.get(k * TRACE_STEP_MS) for k in range(steps)]  # None where it had no estimate
    last = estimated[-1]
    out.update(
        end_estimate=[last[5], last[6], last[7]],
        mean_in=sum(distance) / len(distance),
        max_in=max(distance),
        final_in=distance[-1],
        max_deg=max(turn),
        trace=[None if e is None else round(e, 3) for e in trace],
    )
    return out


def run_trial(
    index: int, spec_data: dict, root: str, executable: str | None, max_seconds: float
) -> dict:
    """One trial (in a pool's worker): run the spec headless until its program finishes
    or ``max_seconds`` pass, and measure it. Never raises: a failure is the row's error."""
    from vexsim.app.runspec import check, program_factory, simulation_factory

    started = time.perf_counter()
    spec = RunSpec.model_validate(spec_data)
    environment = dict(os.environ)
    try:
        prepared = check(spec, root)
        make_program, mode = program_factory(prepared, executable)
        sim = simulation_factory(prepared, make_program, mode, echo=None)()
        try:
            finished = sim.run_until_finished(max_seconds)
        finally:
            sim.close()
        result = {"finished": finished, "error": None, **measure(sim.recorder.rows)}
    except Exception as exc:  # the trial failed; the sweep goes on
        message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
        result = {"finished": False, "error": message, **measure([])}
    finally:  # a Python program's environment variables don't outlive its trial
        os.environ.clear()
        os.environ.update(environment)
    return {"index": index, "wall_s": round(time.perf_counter() - started, 2), **result}


def _run_trial(args: tuple) -> dict:
    return run_trial(*args)


# --- the job ---------------------------------------------------------------------------------


def run_sweep(params: dict, report: Report) -> dict:
    """A sweep as a job: each trial's row as an item once it's done, then the result.
    Params: ``sweep`` (a Sweep's data), ``root`` (the workspace), ``results`` (where results
    go) and ``workers``."""
    from vexsim.app import results
    from vexsim.app.runspec import RunError, build, check
    from vexsim.workers import default_workers, process_pool

    root = Path(params["root"])
    sweep = Sweep.model_validate(params["sweep"])
    trials = expand(sweep, read_configurations(root))
    runs, combos = len(sweep.runs), len(variations(sweep))
    report(
        f"{sweep.name}: {_count(runs, 'run')} x {_count(combos, 'variation')} x "
        f"{_count(sweep.seeds, 'seed')} = {_count(len(trials), 'trial')}"
    )
    executables: dict[str, str] = {}  # the PROS projects, built once
    checked: set[tuple] = set()
    for trial in trials:
        spec = trial.spec
        key = (spec.robot, spec.field, spec.program, spec.input)
        if key in checked:
            continue
        checked.add(key)
        try:
            prepared = check(spec, root)
        except RunError as exc:
            problems = "; ".join(f"{i.location}: {i.message}" for i in exc.issues[:3])
            detail = f": {problems}" if problems else ""
            raise SweepError(f"{trial.run}: {exc.message}{detail}") from None
        if prepared.project is not None and spec.program not in executables:
            report(f"Building {spec.program}")
            executables[spec.program] = str(build(prepared, log=report))
    store = Path(params["results"])
    result_id, folder = results.new_result(store)
    try:
        started = time.perf_counter()
        workers = max(1, min(params.get("workers") or default_workers(), len(trials)))
        report(f"Running {_count(len(trials), 'trial')} on {_count(workers, 'worker')}")
        report.progress(0, len(trials))
        rows: list[dict | None] = [None] * len(trials)
        jobs = [
            (t.index, t.spec.model_dump(), str(root), executables.get(t.spec.program or ""))
            for t in trials
        ]
        with process_pool(workers) as pool:
            futures = [pool.submit(_run_trial, (*job, sweep.max_seconds)) for job in jobs]
            for done, future in enumerate(as_completed(futures), start=1):
                outcome = future.result()
                trial = trials[outcome["index"]]
                row = {
                    "index": trial.index,
                    "run": trial.run,
                    "variation": label(trial.variation),
                    "env": trial.variation,
                    "seed": trial.seed,
                    "start": list(trial.spec.start),
                    "spec": trial.spec.model_dump(),
                    **outcome,
                }
                rows[trial.index] = row
                report.item(row)
                report.progress(done, len(trials))
                if outcome["error"]:
                    where = f"{trial.run}, {label(trial.variation)}, seed {trial.seed}"
                    report(f"{where}: {outcome['error']}")
        wall = time.perf_counter() - started
        finished = [row for row in rows if row is not None]
        unfinished = sum(not row["finished"] for row in finished)
        _write_csv(folder / "trials.csv", finished)
        about = results.write_result(
            folder,
            "sweeps",
            sweep.name,
            f"{_count(runs, 'run')} x {_count(combos, 'variation')} x "
            f"{_count(sweep.seeds, 'seed')}: {_count(len(finished), 'trial')}"
            + (f" ({unfinished} unfinished)" if unfinished else "")
            + f" in {_duration(wall)}",
            {
                "sweep": sweep.model_dump(),
                "variations": [{"label": label(v), "env": v} for v in variations(sweep)],
                "trace_step_s": TRACE_STEP_MS / 1000,
                "workers": workers,
                "wall_time_s": wall,
                "trials": finished,
                "files": ["trials.csv"],
            },
        )
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    results.prune(store)
    return {"id": about["id"]}


CSV_COLUMNS = [
    "run", "variation", "seed", "start_x_in", "start_y_in", "start_heading_deg", "finished",
    "seconds", "mean_in", "max_in", "final_in", "max_deg", "error",
]  # fmt: skip


def _write_csv(path: Path, rows: list[dict]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for row in rows:
            values = [row["run"], row["variation"], row["seed"], *row["start"], row["finished"]]
            values += [row[k] for k in ("seconds", "mean_in", "max_in", "final_in", "max_deg")]
            values.append(row["error"] or "")
            writer.writerow(_cell(v) for v in values)
    return path


def _cell(value) -> str:
    if value is None:
        return ""
    return f"{value:.4f}" if isinstance(value, float) else str(value)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _duration(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} s"
    return f"{seconds / 60:.0f} min"

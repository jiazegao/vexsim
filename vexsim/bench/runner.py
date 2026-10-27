"""Monte-Carlo benchmark: every seed x localizer x controller, in parallel worker processes."""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable, Sequence
from concurrent.futures import as_completed
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import product
from pathlib import Path

import numpy as np

from vexsim.bench.scenario import LoadedScenario, load_scenario
from vexsim.bench.trial import ROBOT_CODE, available_localizers, run_trial
from vexsim.config.loader import load_robot
from vexsim.workers import default_workers, process_pool

# Metrics summarized per combination, with how to read them.
SUMMARY_METRICS = [
    ("final_error_in", "final position error (in)"),
    ("final_heading_error_deg", "final heading error (deg)"),
    ("completion_time_s", "completion time (s)"),
    ("settle_time_s", "settle time (s)"),
    ("overshoot_in", "overshoot (in)"),
    ("path_rms_in", "path RMS error (in)"),
    ("path_max_in", "path max error (in)"),
    ("loc_error_final_in", "localization error at end (in)"),
    ("loc_error_per_100in", "localization error per 100 in"),
    ("energy_j", "energy (J)"),
    ("peak_motor_temp_c", "peak motor temperature (C)"),
    ("wall_contacts", "wall contacts"),
]


@lru_cache(maxsize=8)
def _loaded(path: str) -> LoadedScenario:
    return load_scenario(path)


def _job(args: tuple[str, int, str, int, str | None]) -> dict:
    """Run one trial in a worker. Top-level so it pickles for spawned processes (Windows)."""
    path, seed, localizer, controller_index, executable = args
    loaded = _loaded(path)
    controller = loaded.controllers[controller_index]
    return run_trial(loaded, seed, localizer, controller, executable=executable).row()


@dataclass
class BenchResult:
    scenario_path: Path
    loaded: LoadedScenario
    seeds: list[int]
    localizers: list[str]
    controllers: list[str]
    rows: list[dict] = field(default_factory=list)
    wall_time_s: float = 0.0
    workers: int = 1
    executables: dict[str, str] = field(default_factory=dict)  # PROS-project controllers, built
    pairs: list[tuple[str, str]] | None = None  # (localizer, controller) combinations run

    def combos(self) -> list[tuple[str, str]]:
        if self.pairs is not None:
            return list(self.pairs)
        return list(product(self.localizers, self.controllers))

    def rows_for(self, localizer: str, controller: str) -> list[dict]:
        return [
            r for r in self.rows if r["localizer"] == localizer and r["controller"] == controller
        ]

    def summary(self) -> list[dict]:
        out = []
        for loc, ctrl in self.combos():
            rows = self.rows_for(loc, ctrl)
            entry = {
                "localizer": loc,
                "controller": ctrl,
                "trials": len(rows),
                "success_rate": float(np.mean([r["success"] for r in rows])) if rows else math.nan,
                "timeouts": int(sum(r["timed_out"] for r in rows)),
            }
            for key, _ in SUMMARY_METRICS:
                values = np.array([r[key] for r in rows], dtype=float)
                values = values[~np.isnan(values)]
                if len(values) == 0:
                    entry[key] = None
                    continue
                entry[key] = {
                    "mean": float(values.mean()),
                    "median": float(np.median(values)),
                    "p95": float(np.percentile(values, 95)),
                    "max": float(values.max()),
                }
            out.append(entry)
        return out

    def worst(self, localizer: str, controller: str) -> dict:
        """The worst trial of a combination: failures first, then the largest final error."""
        rows = self.rows_for(localizer, controller)
        return max(rows, key=lambda r: (not r["success"], r["final_error_in"]))


def run_bench(
    scenario_path: str | os.PathLike[str],
    seeds: Sequence[int],
    *,
    localizers: Sequence[str] | None = None,
    controllers: Sequence[str] | None = None,
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> BenchResult:
    """Run every seed x localizer x controller. ``workers=1`` runs in this process."""
    path = str(Path(scenario_path).resolve())
    loaded = _loaded(path)
    config = load_robot(loaded.path(loaded.scenario.robot))
    all_locs = available_localizers(loaded, config)
    locs = list(localizers) if localizers else all_locs
    unknown = set(locs) - set(all_locs)
    if unknown:
        raise ValueError(f"unknown localizers {sorted(unknown)} (scenario has {all_locs})")
    names = [c.name for c in loaded.controllers]
    ctrls = list(controllers) if controllers else names
    unknown = set(ctrls) - set(names)
    if unknown:
        raise ValueError(f"unknown controllers {sorted(unknown)} (scenario has {names})")

    # PROS-project controllers localize themselves: one combination each, built once here
    # (the workers only run the executable).
    executables = {}
    for c in loaded.controllers:
        if c.native and c.name in ctrls:
            from vexsim.bridge.build import build_project

            executables[c.name] = str(build_project(loaded.path(c.project)).executable)
    pairs = []
    for c in ctrls:
        pairs += [(ROBOT_CODE, c)] if c in executables else [(loc, c) for loc in locs]
    jobs = [(path, s, loc, names.index(c), executables.get(c)) for s in seeds for loc, c in pairs]
    workers = workers or default_workers()
    started = time.perf_counter()
    rows: list[dict] = []
    if workers == 1:
        for i, job in enumerate(jobs):
            rows.append(_job(job))
            if progress:
                progress(i + 1, len(jobs))
    else:
        with process_pool(workers) as pool:
            futures = [pool.submit(_job, job) for job in jobs]
            for i, future in enumerate(as_completed(futures)):
                rows.append(future.result())
                if progress:
                    progress(i + 1, len(jobs))
    order = {
        (s, loc, c): k
        for k, (_, s, loc, c) in enumerate((j[0], j[1], j[2], names[j[3]]) for j in jobs)
    }
    rows.sort(key=lambda r: order[(r["seed"], r["localizer"], r["controller"])])
    return BenchResult(
        scenario_path=Path(path),
        loaded=loaded,
        seeds=list(seeds),
        localizers=locs,
        controllers=ctrls,
        rows=rows,
        wall_time_s=time.perf_counter() - started,
        workers=workers,
        executables=executables,
        pairs=pairs,
    )

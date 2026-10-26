"""Run team 1239E's autonomous routines in vexsim and measure their localization.

Each routine runs twice per seed, from the same slightly-off hand placement and with
the same sensor noise:

- **RCL + MCL**: the robot as configured. LemLib's odometry (drive encoders and IMU)
  is corrected by the team's distance-sensor localization, as on the robot.
- **odometry only**: the same robot with its distance sensors unplugged. RCL and MCL
  get no readings and change nothing, so LemLib's odometry runs alone.

The error is the distance between where LemLib thought the robot was
(chassis.getPose(), read every 10 ms) and where it really was.

    python examples/scripts/evaluate_1239e.py                 # all routines, 3 seeds
    python examples/scripts/evaluate_1239e.py --autons "Left 40,skills" --seeds 1
    python examples/scripts/evaluate_1239e.py --plot errors.png

See docs/porting_1239e.md.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "examples" / "pros_projects" / "1239e_2026-27"
ROBOT = ROOT / "examples" / "robots" / "1239e_2026-27.yaml"
FIELD = ROOT / "examples" / "fields" / "1239e_2026-27.yaml"

# The routines' starting poses in vexsim's frame. LemLib's chassis.setPose(60, 0, 90) is
# x 60, y 0 facing +x: heading 90 - theta = 0 here (docs/conventions.md).
LEFT = (60.0, 0.0, 0.0)
RIGHT = (-60.0, 0.0, 180.0)
AUTONS = {
    "Left 40": LEFT,
    "Right 40": RIGHT,
    "Left 30": LEFT,
    "Right 30": RIGHT,
    "Left 30_10": LEFT,
    "Right 30_10": RIGHT,
    "Right 20_10": RIGHT,
    "alliance1pin": RIGHT,
    "skills": LEFT,
}
CONDITIONS = ("RCL + MCL", "odometry only")
PLACEMENT_SD = (0.5, 0.5, 1.0)  # hand placement error: x in, y in, heading deg (std. dev.)
MAX_SECONDS = 75.0


@dataclass
class Result:
    auton: str
    condition: str
    seed: int
    finished: bool
    seconds: float  # autonomous duration
    mean_in: float
    max_in: float
    final_in: float
    max_deg: float
    trace: list[tuple[float, float]]  # (s since autonomous began, position error in)


def placement(auton: str, seed: int) -> tuple[float, float, float]:
    """Where the robot really starts: the routine's pose plus a hand placement error."""
    x, y, heading = AUTONS[auton]
    dx, dy, dh = np.random.default_rng([seed, 1239]).normal(0.0, PLACEMENT_SD)
    return x + dx, y + dy, heading + dh


def run_one(job: tuple[str, str, int, str]) -> Result:
    from vexsim.algorithms.localization.base import Pose
    from vexsim.bridge.program import CppProgram
    from vexsim.config import load_field, load_robot
    from vexsim.runtime.simulation import Simulation

    auton, condition, seed, executable = job
    config = load_robot(ROBOT)
    if condition == "odometry only":
        config = config.model_copy(
            update={"sensors": tuple(s for s in config.sensors if s.type != "distance")}
        )
    program = CppProgram(executable, env={"VEXSIM_AUTON": auton})
    sim = Simulation(
        config,
        program=program,
        field=load_field(FIELD),
        seed=seed,
        start=Pose(*placement(auton, seed)),
        echo=None,
    )
    try:
        sim.start("autonomous")
        finished = sim.run_until_finished(MAX_SECONDS)
    finally:
        sim.close()
    rows = [r for r in sim.recorder.rows if r[1] == "autonomous" and not math.isnan(r[5])]
    begin = rows[0][0]
    trace = [(r[0] - begin, math.hypot(r[2] - r[5], r[3] - r[6])) for r in rows]
    error = sim.recorder.pose_error("autonomous")
    return Result(
        auton,
        condition,
        seed,
        finished,
        rows[-1][0] - begin,
        error.mean_in,
        error.max_in,
        error.final_in,
        error.max_deg,
        trace,
    )


def table(results: list[Result], autons: list[str]) -> str:
    """Markdown: per routine, each condition's errors averaged over the seeds."""
    lines = [
        "| routine | time (s) | RCL + MCL: mean / max / final (in) "
        "| odometry only: mean / max / final (in) |",
        "|---|---:|---:|---:|",
    ]
    for auton in autons:
        cells = []
        for condition in CONDITIONS:
            rs = [r for r in results if r.auton == auton and r.condition == condition]
            mean, peak, final = (
                np.mean([getattr(r, k) for r in rs]) for k in ("mean_in", "max_in", "final_in")
            )
            unfinished = sum(not r.finished for r in rs)
            note = f" ({unfinished} unfinished)" if unfinished else ""
            cells.append(f"{mean:.1f} / {peak:.1f} / {final:.1f}{note}")
        seconds = np.mean([r.seconds for r in results if r.auton == auton])
        lines.append(f"| {auton} | {seconds:.1f} | {cells[0]} | {cells[1]} |")
    return "\n".join(lines)


def plot(results: list[Result], autons: list[str], path: Path, seed: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from vexsim.viz.odometry import GRID, SERIES, SURFACE, TEXT_PRIMARY, TEXT_SECONDARY

    cols = min(3, len(autons))
    rows = math.ceil(len(autons) / cols)
    fig, axes = plt.subplots(
        rows, cols, figsize=(3.4 * cols, 2.3 * rows + 0.9), sharey=True, facecolor=SURFACE,
        squeeze=False,
    )  # fmt: skip
    for ax in axes.flat[len(autons) :]:
        ax.set_visible(False)
    for ax, auton in zip(axes.flat, autons, strict=False):
        ax.set_facecolor(SURFACE)
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
        ax.tick_params(colors=TEXT_SECONDARY, labelsize=8)
        for condition, color in zip(CONDITIONS, SERIES, strict=False):
            for r in results:
                if r.auton == auton and r.condition == condition and r.seed == seed:
                    t, e = zip(*r.trace, strict=True)
                    ax.plot(t, e, color=color, linewidth=1.6, label=condition)
        ax.set_title(auton, color=TEXT_PRIMARY, fontsize=9, loc="left")
    for ax in axes[:, 0]:
        ax.set_ylabel("position error (in)", color=TEXT_SECONDARY, fontsize=8)
    for ax in axes[-1, :]:
        ax.set_xlabel("time into autonomous (s)", color=TEXT_SECONDARY, fontsize=8)
    fig.suptitle(
        "1239E autonomous routines in vexsim: LemLib's pose vs. the true pose",
        color=TEXT_PRIMARY,
        fontsize=11,
    )
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.95), ncol=2, frameon=False,
        fontsize=9, labelcolor=TEXT_PRIMARY,
    )  # fmt: skip
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    fig.savefig(path, dpi=110, facecolor=SURFACE)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--autons", help="comma-separated routine names (default: all)")
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    p.add_argument("--plot", help="save error-over-time plots (first seed) to this PNG")
    args = p.parse_args(argv)
    autons = [a.strip() for a in args.autons.split(",")] if args.autons else list(AUTONS)
    unknown = [a for a in autons if a not in AUTONS]
    if unknown:
        print(f"unknown routine(s): {', '.join(unknown)}; known: {', '.join(AUTONS)}")
        return 2

    from vexsim.bridge.build import build_project

    build = build_project(PROJECT, log=print)
    jobs = [
        (auton, condition, seed, str(build.executable))
        for auton in autons
        for condition in CONDITIONS
        for seed in range(args.seeds)
    ]
    print(f"running {len(jobs)} simulations on {args.workers} workers...")
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run_one, jobs))
    print()
    print(table(results, autons))
    print(
        f"\nAveraged over {args.seeds} seed(s); each seed has its own placement error "
        f"(std. dev. {PLACEMENT_SD[0]} in, {PLACEMENT_SD[1]} in, {PLACEMENT_SD[2]} deg) "
        "and sensor noise, the same for both conditions."
    )
    if args.plot:
        plot(results, autons, Path(args.plot), seed=0)
        print(f"wrote {args.plot}")
    return 0 if all(r.finished for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

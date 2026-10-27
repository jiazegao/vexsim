"""Replay a real 1239E MCL log in vexsim and compare the real and simulated robots' MCL.

The team's code logs every MCL update to the SD card (/usd/mcl_log<N>.1239e). This script
drives the simulated robot along the path such a log records, and has the simulated robot's
MCL write the same kind of log, so the two can be compared number for number or side by side
in the team's log visualizer.

- MCL starts as the log's first update shows: the pose RCL reset it to, from the same
  sensors (VEXSIM_AUTON="startMcl ...", see the port's README).
- Then a virtual driver holds the joysticks of the team's own opcontrol() tank drive. It
  sees where the simulated robot really is and steers it along the logged MCL estimate, in
  time. That estimate is the only record of where the real robot went: where the real MCL
  was wrong, the simulated robot drives the wrong path.
- The simulated robot's log goes to OUT/<log>_s<seed>/, as mcl_log<N>.1239e, with
  truth.csv beside it (where the robot really was, on the log's clock).

    python examples/scripts/replay_1239e_mcl_log.py mcl_log1040.1239e [more logs]
    python examples/scripts/replay_1239e_mcl_log.py mcl_log1023.1239e --brake coast --seeds 3

See docs/1239e_real_vs_sim.md.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import re
import statistics as st
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from vexsim.mcllog import MclLog, Update
from vexsim.runtime.follow import LoggedPath, PathFollower

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "examples" / "pros_projects" / "1239e_2026-27"
ROBOT = ROOT / "examples" / "robots" / "1239e_2026-27.yaml"
FIELD = ROOT / "examples" / "fields" / "1239e_2026-27.yaml"

SENSORS = ("frontL", "frontR", "left", "back", "right")  # the log's order
HIGH_SENSOR = (True, True, False, True, False)  # MclTracking.hpp: high ones see over bases
NO_READING = 9000  # PROS reads 9999 mm when the sensor sees nothing
MM_PER_IN = 25.4
TRACK_IN = 10.4
MAX_IN_S = 450 / 60 * math.pi * 3.25  # 450 rpm at 3.25 in wheels
GAINS = (4.0, 0.03, 10.0, 0.1)  # virtual driver: kx, ky, ktheta, feedforward lead (s)


# --- the log --------------------------------------------------------------------------------


def parse_log(path: str | Path) -> list[Update]:
    """Every complete update in an MCL log (``vexsim.mcllog``: each sensor's reading and ray,
    the particles, the time, the estimate, as it stood before the update, and the spread); a
    cut-off last one is left out."""
    return MclLog.read(path).updates


# --- the field as MCL models it (MclTracking.hpp) --------------------------------------------

Segment = tuple[tuple[float, float], tuple[float, float]]


def _square(cx: float, cy: float, half: float) -> list[Segment]:
    p = [(cx + half, cy + half), (cx + half, cy - half), (cx - half, cy - half),
         (cx - half, cy + half)]  # fmt: skip
    return [(p[k], p[(k + 1) % 4]) for k in range(4)]


H = 70.2
WALLS: list[Segment] = [
    ((-H, -H), (H, -H)),
    ((H, -H), (H, H)),
    ((H, H), (-H, H)),
    ((-H, H), (-H, -H)),
]
LOADERS: list[Segment] = []
for _sx in (1, -1):
    for _sy in (1, -1):
        _a, _b = (70.5 * _sx, 56.75 * _sy), (66.5 * _sx, 56.75 * _sy)
        _c, _d = (66.5 * _sx, 60.75 * _sy), (70.5 * _sx, 60.75 * _sy)
        LOADERS += [(_a, _b), (_b, _c), (_c, _d)]
LOW_BASES = _square(0, 0, 2.8056165)
for _cx, _cy in ((-47, 23.5), (-23.5, 47), (47, -23.5), (23.5, -47)):
    LOW_BASES += _square(_cx, _cy, 2.5)
POLE = (0.0, 0.0, 1.5937075)  # high_center_base: x, y, radius


@dataclass(frozen=True)
class Hit:
    distance_in: float
    incidence_deg: float  # between the ray and the surface's normal
    what: str  # wall, loader, base or pole


def map_hit(ox: float, oy: float, angle: float, high: bool) -> Hit | None:
    """What MCL's map says a sensor at (ox, oy) facing ``angle`` sees, if anything."""
    c, s = math.cos(angle), math.sin(angle)
    best: Hit | None = None
    segments = [("wall", g) for g in WALLS] + [("loader", g) for g in LOADERS]
    if not high:
        segments += [("base", g) for g in LOW_BASES]
    for what, ((x1, y1), (x2, y2)) in segments:
        ex, ey = x2 - x1, y2 - y1
        den = c * ey - s * ex
        if abs(den) < 1e-9:
            continue
        t = ((x1 - ox) * ey - (y1 - oy) * ex) / den
        u = ((x1 - ox) * s - (y1 - oy) * c) / den
        if t >= 0 and 0 <= u <= 1 and (best is None or t < best.distance_in):
            cos_i = abs(den) / math.hypot(ex, ey)
            best = Hit(t, math.degrees(math.acos(min(1.0, cos_i))), what)
    if high:
        cx, cy, r = POLE
        fx, fy = ox - cx, oy - cy
        b = fx * c + fy * s
        disc = b * b - (fx * fx + fy * fy - r * r)
        if disc >= 0:
            t = -b - math.sqrt(disc)
            if t >= 0 and (best is None or t < best.distance_in):
                nx, ny = (fx + t * c) / r, (fy + t * s) / r
                incidence = math.degrees(math.acos(min(1.0, abs(c * nx + s * ny))))
                best = Hit(t, incidence, "pole")
    return best


# --- driving the logged path ------------------------------------------------------------------

CURVE = (15, 20, 1.05)  # the team's throttle curve: LemLib ExpoDriveCurve(15, 20, 1.05)


class VirtualDriver(PathFollower):
    """The tank-drive driver of ``vexsim run --follow`` (``vexsim.runtime.follow``): it holds
    the joysticks of the team's opcontrol(), through the inverse of their throttle curve, to
    drive along the logged MCL path, and notes where the robot really was."""

    def __init__(self, path: LoggedPath, gains: tuple[float, float, float, float] = GAINS):
        super().__init__(path, track_in=TRACK_IN, top_speed_in_s=MAX_IN_S, curve=CURVE, gains=gains)
        self.truth: list[tuple[float, float, float, float]] = []  # s, x in, y in, theta rad

    def poll(self, time_s: float) -> tuple[dict[str, float], set[str]]:
        sim = self.sim
        if sim is not None and sim.phase == "opcontrol":
            x, y, theta = sim.robot.pose
            self.truth.append((time_s, x / 0.0254, y / 0.0254, theta))
        return super().poll(time_s)


def start_routine(updates: list[Update]) -> tuple[str, tuple[float, float, float]]:
    """VEXSIM_AUTON that starts MCL as the log's first update shows, and vexsim's --start.

    startMcl() logs the pose RCL reset it to. The back sensor sets x; y, when it isn't 0,
    came from whichever side sensor was nearer its wall.
    """
    x, y, theta = updates[0].estimate
    vex = (90 - math.degrees(theta)) % 360
    side = abs(y) > 1e-4
    left = side and updates[0].sensors[2][0] <= updates[0].sensors[4][0]
    right = side and not left
    routine = f"startMcl 60,0,{vex:.0f},0,{int(left)},1,{int(right)}"
    return routine, (x, y, math.degrees(theta))


@dataclass
class Replay:
    real: Path
    seed: int
    sim_log: Path
    truth_csv: Path
    following_in: list[float] = field(default_factory=list)


def replay(job: tuple[str, str, int, str, str]) -> Replay:
    """Drive one real log's path in vexsim (job: log, out dir, seed, executable, brake)."""
    from vexsim.algorithms.localization.base import Pose
    from vexsim.bridge.program import CppProgram
    from vexsim.config import load_field, load_robot
    from vexsim.runtime.simulation import Simulation

    real, out, seed, executable, brake = job
    log = MclLog.read(real)
    path = LoggedPath(*log.path())
    routine, start = start_routine(log.updates)
    folder = Path(out) / f"{Path(real).stem}_s{seed}"
    folder.mkdir(parents=True, exist_ok=True)
    env = {"VEXSIM_AUTON": routine, "VEXSIM_SD_DIR": str(folder.resolve()),
           "VEXSIM_SEED": str(seed), "VEXSIM_BRAKE": brake}  # fmt: skip
    driver = VirtualDriver(path)
    sim = Simulation(
        load_robot(ROBOT),
        program=CppProgram(executable, env=env),
        field=load_field(FIELD),
        seed=seed,
        start=Pose(*start),
        input_source=driver,
        echo=None,
    )
    driver.attach(sim)
    try:
        sim.start("match")  # autonomous starts MCL and returns; opcontrol drives
        limit = path.end + 30.0
        while (driver.start_s is None or sim.world.time < driver.start_s + path.end + 0.3) and (
            sim.world.time < limit
        ):
            sim.run_for(1.0)
    finally:
        sim.close()
    started = [
        re.search(r"initLog: logging MCL to (.*) from (\d+) ms", line) for line in sim.console
    ]
    started = [m for m in started if m]
    if not started or driver.start_s is None:
        raise RuntimeError(
            f"{real}: the simulated robot didn't log MCL:\n" + "\n".join(sim.console[-10:])
        )
    sim_log, init_s = Path(started[-1].group(1)), int(started[-1].group(2)) / 1000
    truth_csv = folder / "truth.csv"
    with truth_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "x", "y", "theta"])
        for t, x, y, theta in driver.truth:
            w.writerow([f"{t - init_s:.4f}", f"{x:.3f}", f"{y:.3f}", f"{theta:.5f}"])
    return Replay(Path(real), seed, sim_log, truth_csv, driver.following)


# --- measuring a log ----------------------------------------------------------------------------


def _quantile(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[min(int(q * len(values)), len(values) - 1)] if values else math.nan


def _still(points: list[tuple[float, float, float, float]], i: int) -> bool:
    """Whether (t, x, y, theta) points show the robot still around point i."""
    a, b = points[max(i - 3, 0)], points[min(i + 3, len(points) - 1)]
    dt = b[0] - a[0]
    if dt <= 0:
        return False
    turn = abs(math.degrees(math.remainder(b[3] - a[3], math.tau)))
    return math.hypot(b[1] - a[1], b[2] - a[2]) / dt < 1.0 and turn / dt < 3.0


def measure(updates: list[Update], truth_csv: Path | None = None) -> dict[str, float]:
    """Numbers to compare a real log and a simulated one by.

    Sensor numbers come from well-localized updates only (at least 3 readings, median
    within 1 in of what MCL's map predicts from the logged estimate), so that a wrong
    estimate doesn't pass for a sensor error. Reading noise is the spread of each sensor's
    readings over stretches of >= 10 updates with the robot still: for a real log judged
    from its estimate, for a simulated one from where the robot really was.
    """
    m: dict[str, float] = {}
    gaps = [(b.t - a.t) * 1000 for a, b in zip(updates, updates[1:], strict=False)]
    m["interval median ms"], m["interval p95 ms"] = st.median(gaps), _quantile(gaps, 0.95)
    m["interval max ms"] = max(gaps)
    m["no reading %"] = 100 * st.fmean(
        r[0] >= NO_READING for u in updates for r in u.sensors
    )  # fmt: skip

    good, misfits = [], []
    for u in updates:
        rows = []
        for k, (mm, ox, oy, angle) in enumerate(u.sensors):
            hit = map_hit(ox, oy, angle, HIGH_SENSOR[k])
            rows.append((mm, hit))
        errors = [abs(mm / MM_PER_IN - h.distance_in) for mm, h in rows
                  if mm < NO_READING and h and h.distance_in * MM_PER_IN < 2000]  # fmt: skip
        if errors:
            misfits.append(st.median(errors))
            if len(errors) >= 3 and st.median(errors) < 1.0:
                good += rows

    def none_rate(rows: list) -> float:
        return 100 * st.fmean(mm >= NO_READING for mm, _ in rows) if len(rows) >= 20 else math.nan

    in_band = [(mm, h) for mm, h in good if h]
    m["no reading %, map says 2.0-2.5 m, facing"] = none_rate(
        [(mm, h) for mm, h in in_band if 2000 <= h.distance_in * MM_PER_IN < 2500
         and h.incidence_deg < 30]
    )  # fmt: skip
    m["no reading %, map says 1.5-2.0 m, glancing (>45 deg)"] = none_rate(
        [(mm, h) for mm, h in in_band if 1500 <= h.distance_in * MM_PER_IN < 2000
         and h.incidence_deg >= 45]
    )  # fmt: skip
    readable = [(mm, h) for mm, h in in_band if 300 <= h.distance_in * MM_PER_IN < 2000
                and mm < NO_READING]  # fmt: skip
    m["readings > 150 mm short of the map %"] = (
        100 * st.fmean(mm < h.distance_in * MM_PER_IN - 150 for mm, h in readable)
        if readable else math.nan
    )  # fmt: skip

    if truth_csv is None:
        points = [(u.t, *u.estimate) for u in updates]
        still_at = [_still(points, i) for i in range(len(updates))]
    else:
        truth = [tuple(map(float, r)) for r in list(csv.reader(truth_csv.open()))[1:]]
        times = [p[0] for p in truth]
        still_at = []
        for u in updates:
            k = min(bisect.bisect_left(times, u.t), len(truth) - 1)
            still_at.append(_still(truth, k))
    spreads = []
    i = 0
    while i < len(updates):
        j = i
        while j < len(updates) and still_at[j]:
            j += 1
        if j - i >= 10:
            for k in range(5):
                mm = [updates[n].sensors[k][0] for n in range(i, j)]
                mm = [v for v in mm if v < NO_READING]
                if len(mm) >= 8 and 200 < st.fmean(mm) < 2000:
                    spreads.append(st.pstdev(mm))
        i = max(j, i + 1)
    m["reading noise, still, mm"] = st.median(spreads) if spreads else math.nan

    spread = [math.hypot(*u.spread) for u in updates]
    m["MCL spread median in"], m["MCL spread p95 in"] = st.median(spread), _quantile(spread, 0.95)
    m["map misfit > 3 in, % of updates"] = 100 * st.fmean(e > 3 for e in misfits)
    if truth_csv is not None:
        truth = [tuple(map(float, r)) for r in list(csv.reader(truth_csv.open()))[1:]]
        times = [p[0] for p in truth]
        errors = []
        for a, b in zip(updates, updates[1:], strict=False):  # b logs a's estimate
            k = bisect.bisect_left(times, a.t)
            if 0 < k < len(truth):
                errors.append(math.hypot(b.estimate[0] - truth[k][1], b.estimate[1] - truth[k][2]))
        m["MCL error median in"], m["MCL error p95 in"] = st.median(errors), _quantile(errors, 0.95)
        m["MCL error max in"] = max(errors)
    return m


def table(real: Path, replays: list[Replay]) -> str:
    """Markdown: one log's numbers, real and simulated (averaged over seeds)."""
    measured = measure(parse_log(real))
    sims = [measure(parse_log(r.sim_log), r.truth_csv) for r in replays]
    following = [e for r in replays for e in r.following_in]
    lines = [
        f"### {real.name}",
        "",
        f"Path followed to {st.median(following):.1f} in (median), "
        f"{_quantile(following, 0.95):.1f} in (95%); {len(replays)} seed(s).",
        "",
        "| | real | simulated |",
        "|---|---:|---:|",
    ]
    for key in list(measured) + [k for k in sims[0] if k not in measured]:
        sim_values = [s[key] for s in sims if not math.isnan(s.get(key, math.nan))]
        real_value = measured.get(key, math.nan)
        sim_text = f"{st.fmean(sim_values):.1f}" if sim_values else "-"
        real_text = "-" if math.isnan(real_value) else f"{real_value:.1f}"
        lines.append(f"| {key} | {real_text} | {sim_text} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("logs", nargs="+", help="real MCL logs (mcl_log<N>.1239e)")
    parser.add_argument("--out", default="replays", help="folder for the simulated logs")
    parser.add_argument("--seeds", type=int, default=1, help="replays per log (sensor noise, MCL)")
    parser.add_argument(
        "--brake",
        choices=("hold", "brake", "coast"),
        default="hold",
        help="drive brake mode while replaying (hold suits autonomous paths)",
    )
    parser.add_argument("--workers", type=int, default=0, help="parallel replays (default: CPUs)")
    args = parser.parse_args(argv)

    from vexsim.bridge.build import build_project

    executable = str(build_project(PROJECT, log=print).executable)
    jobs = [(log, args.out, seed, executable, args.brake)
            for log in args.logs for seed in range(1, args.seeds + 1)]  # fmt: skip
    with ProcessPoolExecutor(max_workers=args.workers or None) as pool:
        replays = list(pool.map(replay, jobs))
    for log in args.logs:
        mine = [r for r in replays if r.real == Path(log)]
        for r in mine:
            print(f"{Path(log).name} seed {r.seed}: simulated log {r.sim_log}")
        print()
        print(table(Path(log), mine))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

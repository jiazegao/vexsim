"""The autonomous check (phase 14.5): the team's real routine against the simulated one.

The competition program, with vexsim's logger in it, runs a routine on the real robot. Before
the robot is moved, tape marks go at two of its corners, and each is measured from two
walls: ``end_pose`` works out where the robot ended from its shape. ``check_auton`` then
runs the same routine in vexsim from where the log's code started it (its first
``setPose``), with a few seeds, each until the robot is still after the period ends (as the
real one was when it was measured), and compares:

- where the robot ended, simulated (the seeds' mean) against measured, as a distance and a
  heading, against the team's pass marks;
- the code's own pose through the run, real against simulated, time from the routine's
  ``setPose``: on average (RMS, over the run and the seeds) within the distance mark, and
  the first moment they part by more than it (over half a second, so a turn a few
  milliseconds early doesn't count);
- heading, wheel travel and distance readings over time, in the report's plots.

The check passes when the end is within both marks and the run within the distance mark:
a routine whose motions and localization correct a robot's errors by its end can end in the
same place on a simulator that drives it differently, and only the run shows that. Several
real runs of one routine are compared each against the seeds, and as a spread against the
seeds' spread.

The pass marks (2 in and 2 degrees, unless the team says) are in ``.vexsim/calibration.yaml``
(``max_distance_in``, ``max_heading_deg``), in the folder vexsim runs in or one above it.
"""

from __future__ import annotations

import dataclasses
import math
import re
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from vexsim.calibration.log import RobotLog
from vexsim.config.field import FieldConfig
from vexsim.config.robot import RobotConfig

Say = Callable[[str], None]

MAX_DISTANCE_IN = 2.0  # the pass marks, unless the team sets its own
MAX_HEADING_DEG = 2.0
TAPE_IN, TAPE_DEG = 0.5, 1.0  # finer than a tape measure can tell
MARKS_FILE = Path(".vexsim") / "calibration.yaml"
SEEDS = 3
MISFIT_IN = 1.0  # two marks further from the robot's corners' spacing than this don't fit it
CLOSE_IN = 6.0  # two corners closer than this don't tell the heading well
STILL_S = 0.3  # the robot is still once it hasn't moved for this long
SETTLE_S = 3.0  # at most this long after the period ends
WINDOW_S = 0.5  # parting means over this long, not a moment
WALLS = ("-x", "+x", "-y", "+y")


class AutonError(Exception):
    """The check can't run (the message says what to fix)."""


# --- the end pose, from tape marks ------------------------------------------------------------


@dataclass(frozen=True)
class Corner:
    """A tape mark at one of the robot's corners: its name, and how far it is from a wall
    across the field's x and from one across its y (in)."""

    name: str  # front-left, front-right, back-left, back-right
    x_wall: str  # -x or +x
    x_in: float
    y_wall: str  # -y or +y
    y_in: float

    def point(self, field: FieldConfig) -> tuple[float, float]:
        """Where the mark is, field inches from the center."""
        hx, hy = field.size_in[0] / 2, field.size_in[1] / 2
        x = self.x_in - hx if self.x_wall == "-x" else hx - self.x_in
        y = self.y_in - hy if self.y_wall == "-y" else hy - self.y_in
        return x, y


_CORNER = re.compile(
    r"\b(?:(front|back)[\s-]*(left|right)|(left|right)[\s-]*(front|back)|(fl|fr|bl|br))\b",
    re.IGNORECASE,
)
_SHORT = {"fl": "front-left", "fr": "front-right", "bl": "back-left", "br": "back-right"}
_TOKEN = re.compile(r"([+-]\s*[xy])\b|(\d+(?:\.\d+)?(?:\s+\d+/\d+)?|\d+/\d+)", re.IGNORECASE)


def _number(text: str) -> float:
    """23.5, 23 1/2 or 1/2."""
    value = 0.0
    for part in text.split():
        if "/" in part:
            top, bottom = part.split("/")
            value += float(top) / float(bottom)
        else:
            value += float(part)
    return value


def _corner_name(match: re.Match) -> str:
    front, side, side2, front2, short = match.groups()
    if short:
        return _SHORT[short.lower()]
    return f"{(front or front2).lower()}-{(side or side2).lower()}"


def parse_end(text: str) -> list[Corner]:
    """Two corners' tape marks, as ``front-left: 23.5 from -x, 40 from +y; back-right:
    35.25 from -x, 52 from +y`` (or ``FL -x 23.5 +y 40, BR -x 35.25 +y 52``; fractions as
    23 1/2): each corner's name, then its distance from an x wall and from a y wall."""
    found = list(_CORNER.finditer(text))
    before = text[: found[0].start()] if found else text
    if _TOKEN.search(before):
        raise AutonError(
            f"{before.strip()!r}: name each corner first: front-left, front-right, back-left or "
            "back-right (FL, FR, BL, BR)"
        )
    corners = []
    for k, match in enumerate(found):
        name = _corner_name(match)
        rest = text[match.end() : found[k + 1].start() if k + 1 < len(found) else len(text)]
        tokens = [
            ("wall", m.group(1).replace(" ", "").lower()) if m.group(1) else ("in", m.group(2))
            for m in _TOKEN.finditer(rest)
        ]
        pairs = []
        for a, b in zip(tokens[::2], tokens[1::2], strict=False):
            if {a[0], b[0]} != {"wall", "in"}:
                break
            wall, inches = (a[1], b[1]) if a[0] == "wall" else (b[1], a[1])
            pairs.append((wall, _number(inches)))
        xs = [w for w, _ in pairs if w[1] == "x"]
        ys = [w for w, _ in pairs if w[1] == "y"]
        if len(pairs) != 2 or len(xs) != 1 or len(ys) != 1 or len(tokens) != 4:
            raise AutonError(
                f"{text[match.start() : match.end() + len(rest)].strip()!r}: give the {name} "
                "corner's distance from one x wall and one y wall (e.g. 23.5 from -x, 40 from +y)"
            )
        by_wall = dict(pairs)
        corners.append(Corner(name, xs[0], by_wall[xs[0]], ys[0], by_wall[ys[0]]))
    if len(corners) != 2 or corners[0].name == corners[1].name:
        raise AutonError(
            "measure two different corners of the robot, each from two walls (e.g. front-left: "
            "23.5 from -x, 40 from +y; back-right: 35.25 from -x, 52 from +y)"
        )
    return corners


def named_corners(config: RobotConfig) -> dict[str, tuple[float, float]]:
    """The robot's four corners by name (robot frame, in): of its outline, the point
    furthest toward each (front-left the furthest forward and left, ...)."""
    points = np.array(config.body.outline.corners, dtype=float)
    out = {}
    for name, (sx, sy) in {
        "front-left": (1, 1),
        "front-right": (1, -1),
        "back-left": (-1, 1),
        "back-right": (-1, -1),
    }.items():
        best = points[int(np.argmax(sx * points[:, 0] + sy * points[:, 1]))]
        out[name] = (float(best[0]), float(best[1]))
    return out


@dataclass(frozen=True)
class EndPose:
    """Where the robot ended (x, y in, heading degrees counter-clockwise from +x), from two
    tape marks, and how far their spacing is from the corners' (in)."""

    x: float
    y: float
    heading: float
    misfit_in: float
    corners: tuple[Corner, ...]

    @property
    def pose(self) -> tuple[float, float, float]:
        return self.x, self.y, self.heading


def end_pose(config: RobotConfig, field: FieldConfig, corners: Sequence[Corner]) -> EndPose:
    """The pose that puts the robot's two corners on their tape marks (as near as the marks
    allow). Raises AutonError when they can't tell it."""
    body = named_corners(config)
    c1, c2 = (np.array(body[c.name]) for c in corners)
    p1, p2 = (np.array(c.point(field)) for c in corners)
    if np.hypot(*(c2 - c1)) < CLOSE_IN:
        raise AutonError(
            f"the {corners[0].name} and {corners[1].name} corners are too close together to tell "
            "the robot's heading: measure two corners further apart (front-left and back-right)"
        )
    heading = math.atan2(*(p2 - p1)[::-1]) - math.atan2(*(c2 - c1)[::-1])
    c, s = math.cos(heading), math.sin(heading)
    rot = np.array([[c, -s], [s, c]])
    origin = ((p1 - rot @ c1) + (p2 - rot @ c2)) / 2
    misfit = abs(float(np.hypot(*(p2 - p1)) - np.hypot(*(c2 - c1))))
    return EndPose(
        float(origin[0]), float(origin[1]), math.degrees(heading) % 360, misfit, tuple(corners)
    )


def tape_marks(
    config: RobotConfig,
    field: FieldConfig,
    pose: Sequence[float],
    names: Sequence[str] = ("front-left", "back-right"),
    step: float = 0.25,
) -> str:
    """The tape measurements a person would take of a robot at ``pose``: each corner from
    the nearer x wall and the nearer y wall, to ``step`` in (the inverse of ``end_pose``)."""
    x, y, heading = pose
    c, s = math.cos(math.radians(heading)), math.sin(math.radians(heading))
    hx, hy = field.size_in[0] / 2, field.size_in[1] / 2
    parts = []
    for name in names:
        bx, by = named_corners(config)[name]
        px, py = x + c * bx - s * by, y + s * bx + c * by
        xw, xd = ("-x", px + hx) if px < 0 else ("+x", hx - px)
        yw, yd = ("-y", py + hy) if py < 0 else ("+y", hy - py)
        parts.append(
            f"{name}: {round(xd / step) * step:g} from {xw}, {round(yd / step) * step:g} from {yw}"
        )
    return "; ".join(parts)


# --- the pass marks ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Marks:
    """How close a simulated run must come to the real one to pass."""

    max_distance_in: float = MAX_DISTANCE_IN
    max_heading_deg: float = MAX_HEADING_DEG
    source: str = "vexsim's defaults"

    def warnings(self) -> list[str]:
        out = []
        if self.max_distance_in < TAPE_IN:
            out.append(
                f"a {self.max_distance_in:g} in mark is finer than a tape measure tells "
                f"({TAPE_IN:g} in): the check can fail on how the marks were measured"
            )
        if self.max_heading_deg < TAPE_DEG:
            out.append(
                f"a {self.max_heading_deg:g} degree mark is finer than two tape marks tell "
                f"({TAPE_DEG:g} degree): the check can fail on how they were measured"
            )
        return out


def marks_file(start: str | Path | None = None) -> Path | None:
    """The team's ``.vexsim/calibration.yaml``: in ``start`` (the folder vexsim runs in) or
    the nearest folder above it that has one."""
    folder = Path(start or Path.cwd()).resolve()
    for place in (folder, *folder.parents):
        if (place / MARKS_FILE).is_file():
            return place / MARKS_FILE
    return None


def load_marks(
    start: str | Path | None = None,
    *,
    max_distance_in: float | None = None,
    max_heading_deg: float | None = None,
) -> Marks:
    """The pass marks: as given, else the team's (``marks_file``), else vexsim's."""
    distance, heading, sources = MAX_DISTANCE_IN, MAX_HEADING_DEG, []
    path = marks_file(start)
    if path is not None:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise AutonError(f"{path}: {exc}") from None
        if not isinstance(data, dict):
            raise AutonError(f"{path}: expected max_distance_in and max_heading_deg")
        for key in ("max_distance_in", "max_heading_deg"):
            value = data.get(key)
            if value is not None and not (
                isinstance(value, int | float) and not isinstance(value, bool) and value > 0
            ):
                raise AutonError(f"{path}: {key} must be a number above 0, got {value!r}")
        distance = float(data.get("max_distance_in", distance))
        heading = float(data.get("max_heading_deg", heading))
        sources.append(str(path))
    if max_distance_in is not None:
        distance = max_distance_in
        sources.append("--max-distance")
    if max_heading_deg is not None:
        heading = max_heading_deg
        sources.append("--max-heading")
    for value in (distance, heading):
        if not (math.isfinite(value) and value > 0):
            raise AutonError("pass marks are distances and angles above 0")
    return Marks(distance, heading, ", ".join(sources) or "vexsim's defaults")


# --- the simulated runs -----------------------------------------------------------------------


@dataclass
class SimRun:
    """One simulated run of the routine."""

    seed: int
    end: tuple[float, float, float]  # at rest after the period: x, y (in), heading (deg)
    buzzer: tuple[float, float, float]  # when the period ended
    log: RobotLog | None  # the code's own log of the run (from its card), if it logs
    path: np.ndarray  # the robot's true pose every 10 ms: time (s), x, y (in), heading (deg)


def _pose(sim) -> tuple[float, float, float]:
    x, y, heading = sim.robot.pose
    return x / 0.0254, y / 0.0254, math.degrees(heading) % 360


def settle(sim, still_s: float = STILL_S, limit_s: float = SETTLE_S) -> None:
    """Run on, the robot disabled, until it has been still for ``still_s`` (or ``limit_s``):
    where a tape measure finds it."""
    still = waited = 0.0
    while still < still_s and waited < limit_s:
        vx, vy = sim.robot.field_velocity
        moving = math.hypot(vx, vy) > 0.001 or abs(sim.robot.body_velocity[2]) > 0.01
        still = 0.0 if moving else still + 0.05
        sim.run_for(0.05)
        waited += 0.05


def _simulate(job: tuple[dict, str, int, str]) -> dict:
    """One seed's run, in a worker process: the run's spec (as a dict), the program's robot
    host, the seed, and the folder that stands in for its card."""
    from vexsim.app.runspec import RunSpec, check, program_factory, simulation_factory

    data, executable, seed, card = job
    spec = RunSpec.model_validate(data).model_copy(update={"seed": seed, "sd": card})
    prepared = check(spec)
    make, mode = program_factory(prepared, executable)
    sim = simulation_factory(prepared, make, mode, echo=None)()
    path: list[tuple[float, float, float, float]] = []
    sim.world.every(10, lambda w: path.append((w.time, *_pose(sim))), name="auton check")
    try:
        sim.run_until_finished(60.0)
        buzzer = _pose(sim)
        settle(sim)
        end = _pose(sim)
    finally:
        sim.close()
    logs = sorted(Path(card).glob("vexsim_*.csv"))
    text = logs[-1].read_text(encoding="utf-8") if logs else None
    return {"seed": seed, "end": end, "buzzer": buzzer, "log": text, "path": path}


def simulate_routine(
    spec, seeds: Sequence[int], *, workers: int = 1, say: Say | None = None
) -> list[SimRun]:
    """The run ``spec`` (a ``RunSpec``: a PROS project, its routine, the start) once per seed,
    each until the robot is still after the period ends; in parallel with ``workers`` > 1."""
    from vexsim.app.runspec import build, check
    from vexsim.workers import clean_start, process_pool

    say = say or (lambda text: None)
    spec = spec.resolved(Path.cwd())
    prepared = check(spec)
    if prepared.project is None:
        raise AutonError("the program must be the PROS project the real robot ran")
    executable = build(prepared, log=lambda line: None)
    with tempfile.TemporaryDirectory(prefix="vexsim-auton-") as folder:
        jobs = [
            (spec.model_dump(), str(executable), seed, str(Path(folder) / f"card_{seed}"))
            for seed in seeds
        ]
        if workers > 1 and len(jobs) > 1:
            with process_pool(min(workers, len(jobs)), clean_start()) as pool:
                done = list(pool.map(_simulate, jobs))
        else:
            done = [_simulate(job) for job in jobs]
    runs = []
    for result in done:
        log = RobotLog.parse(result["log"]) if result["log"] else None
        runs.append(
            SimRun(result["seed"], result["end"], result["buzzer"], log, np.array(result["path"]))
        )
        x, y, h = result["end"]
        say(f"seed {result['seed']}: ended at {x:.2f}, {y:.2f}, {h:.1f} deg")
    return runs


def routine_for(project: str | Path, name: str) -> str:
    """The project's routine a log is named for: its function, as the log's name reads
    without spaces and case (Left 40: left40). Raises AutonError if none or several."""
    from vexsim.bridge.routines import AUTON_HEADER, find_routines

    found = find_routines(project)
    if found is None:
        raise AutonError(f"{project} has no {AUTON_HEADER}: say which routine with --routine")
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    matches = [r.name for r in found.routines if re.sub(r"[^a-z0-9]", "", r.name.lower()) == key]
    if len(matches) != 1:
        names = ", ".join(r.name for r in found.routines) or "none"
        raise AutonError(
            f"which of the project's routines ran as {name!r}? Say with --routine (its "
            f"routines: {names})"
        )
    return matches[0]


# --- comparing --------------------------------------------------------------------------------


def code_path(log: RobotLog, name: str | None = None) -> tuple[np.ndarray, np.ndarray] | None:
    """The code's own pose through a run (``robot_log_path``): times from its first setPose
    (s), and x, y (in) and heading (radians counter-clockwise, unwrapped) at each; None if
    the log has no pose."""
    from vexsim.runtime.follow import robot_log_path

    try:
        times, poses = robot_log_path(log, name)
    except ValueError:
        return None
    return np.array(times), np.array(poses)


def _at(path: tuple[np.ndarray, np.ndarray], t: np.ndarray) -> np.ndarray:
    times, poses = path
    return np.column_stack([np.interp(t, times, poses[:, k]) for k in range(3)])


def run_rms(real: tuple[np.ndarray, np.ndarray], sim: tuple[np.ndarray, np.ndarray]) -> float:
    """How far apart two runs' code poses are, RMS through the time both cover (in)."""
    times, poses = real
    keep = times <= sim[0][-1]
    d = np.hypot(*(poses[keep, :2] - _at(sim, times[keep])[:, :2]).T)
    return float(np.sqrt(np.mean(d**2))) if len(d) else math.nan


def parted_at(
    real: tuple[np.ndarray, np.ndarray], sims: Sequence[tuple[np.ndarray, np.ndarray]], mark: float
) -> float | None:
    """The first moment the real code pose is further than ``mark`` (in) from the simulated
    runs' (their mean), and stays that far on average for ``WINDOW_S`` (s from the real run's
    setPose); None if never. A turn a few milliseconds early is apart for a moment only."""
    times, poses = real
    end = min(s[0][-1] for s in sims)
    keep = times <= end
    t = times[keep]
    if len(t) < 2:
        return None
    mean = np.mean([_at(s, t) for s in sims], axis=0)
    d = np.hypot(*(poses[keep, :2] - mean[:, :2]).T)
    step = float(np.median(np.diff(t))) or 0.01
    n = max(1, round(WINDOW_S / step))
    ahead = np.convolve(d, np.ones(n) / n, mode="valid")  # the mean over the next WINDOW_S
    over = np.flatnonzero((d[: len(ahead)] > mark) & (ahead > mark))
    return float(t[over[0]]) if len(over) else None


def _heading_gap(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def _mean_pose(poses: Sequence[Sequence[float]]) -> tuple[float, float, float]:
    xs, ys, hs = zip(*poses, strict=True)
    h = math.degrees(math.atan2(np.mean(np.sin(np.radians(hs))), np.mean(np.cos(np.radians(hs)))))
    return float(np.mean(xs)), float(np.mean(ys)), h % 360


def spread(poses: Sequence[Sequence[float]]) -> tuple[float, float]:
    """How far apart poses are: the furthest any is from their mean (in), and in heading
    (degrees)."""
    if len(poses) < 2:
        return 0.0, 0.0
    mx, my, mh = _mean_pose(poses)
    return (
        max(math.dist((x, y), (mx, my)) for x, y, _ in poses),
        max(abs(_heading_gap(h, mh)) for _, _, h in poses),
    )


@dataclass
class RealRun:
    """One real run, against the simulated ones."""

    file: str
    log: RobotLog
    end: EndPose | None  # where it was measured to end
    end_off: tuple[float, float] | None = None  # from the seeds' mean end: in, degrees
    run_rms_in: float | None = None  # its code's pose against each seed's, RMS, their mean
    parted_s: float | None = None  # the first moment it parts from them by over the mark
    path: tuple[np.ndarray, np.ndarray] | None = None  # its code's pose through the run


@dataclass
class AutonCheck:
    """What the check found."""

    routine: str
    start: tuple[float, float, float]
    marks: Marks
    runs: list[RealRun]
    sims: list[SimRun]
    end_off: tuple[float, float] | None  # the real end (their mean) from the seeds' mean end
    run_rms_in: float | None  # the real runs' code pose against the seeds', RMS (their mean)
    sim_spread: tuple[float, float]
    real_spread: tuple[float, float] | None
    warnings: list[str] = dataclasses.field(default_factory=list)
    failures: list[str] = dataclasses.field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def apart(self, run: RealRun) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]] | None:
        """How far a real run's code pose is from each simulated run's through the run: the
        times (s from its setPose), their mean's distance, and each one's (in)."""
        if run.path is None:
            return None
        sims = [p for s in self.sims if s.log is not None and (p := code_path(s.log))]
        if not sims:
            return None
        times, poses = run.path
        t = times[times <= min(s[0][-1] for s in sims)]
        each = [np.hypot(*(poses[: len(t), :2] - _at(s, t)[:, :2]).T) for s in sims]
        mean = np.mean([_at(s, t) for s in sims], axis=0)
        return t, np.hypot(*(poses[: len(t), :2] - mean[:, :2]).T), each

    @property
    def sim_end(self) -> tuple[float, float, float]:
        return _mean_pose([s.end for s in self.sims])


def compare(
    routine: str,
    start: tuple[float, float, float],
    marks: Marks,
    runs: Sequence[RealRun],
    sims: Sequence[SimRun],
    pose_name: str | None = None,
) -> AutonCheck:
    """The real runs against the simulated ones, and the verdict."""
    warnings = list(marks.warnings())
    sim_end = _mean_pose([s.end for s in sims])
    sim_paths = [p for s in sims if s.log is not None and (p := code_path(s.log, pose_name))]
    for run in runs:
        if run.end is not None:
            x, y, h = run.end.pose
            run.end_off = (math.dist((x, y), sim_end[:2]), _heading_gap(h, sim_end[2]))
            if run.end.misfit_in > MISFIT_IN:
                warnings.append(
                    f"{run.file}: its two tape marks are {run.end.misfit_in:.1f} in further from "
                    "each other, or nearer, than those corners are: re-measure them, or check "
                    "which corners they are"
                )
        run.path = code_path(run.log, pose_name)
        if run.path is None:
            warnings.append(
                f"{run.file} has no pose of its code's (vexsim_log::pose): only its end is compared"
            )
        elif sim_paths:
            run.run_rms_in = float(np.mean([run_rms(run.path, s) for s in sim_paths]))
            run.parted_s = parted_at(run.path, sim_paths, marks.max_distance_in)
    measured = [r.end.pose for r in runs if r.end is not None]
    end_off = None
    if measured:
        mean = _mean_pose(measured)
        end_off = (math.dist(mean[:2], sim_end[:2]), _heading_gap(mean[2], sim_end[2]))
    rms_values = [r.run_rms_in for r in runs if r.run_rms_in is not None]
    rms = float(np.mean(rms_values)) if rms_values else None
    sim_spread = spread([s.end for s in sims])
    real_spread = spread(measured) if len(measured) > 1 else None
    if sim_spread[0] > marks.max_distance_in or sim_spread[1] > marks.max_heading_deg:
        warnings.append(
            f"the simulated runs alone end up to {sim_spread[0]:.1f} in and {sim_spread[1]:.1f} "
            f"degrees from their mean: marks tighter than that ({marks.max_distance_in:g} in, "
            f"{marks.max_heading_deg:g} degrees) can fail a run vexsim can't tell from its own"
        )
    if real_spread is not None and (
        real_spread[0] > 2 * max(sim_spread[0], TAPE_IN)
        or real_spread[1] > 2 * max(sim_spread[1], TAPE_DEG)
    ):
        warnings.append(
            f"the real runs end up to {real_spread[0]:.1f} in and {real_spread[1]:.1f} degrees "
            f"from their mean, the simulated ones {sim_spread[0]:.1f} in and "
            f"{sim_spread[1]:.1f}: something varies on the real robot that the simulation "
            "doesn't have (how it was placed, the battery, the field)"
        )
    failures = []
    if end_off is None:
        failures.append("no end was measured: put tape at two corners, measure them (--end)")
    else:
        if end_off[0] > marks.max_distance_in:
            failures.append(
                f"it ends {end_off[0]:.1f} in from the simulated end (the mark: "
                f"{marks.max_distance_in:g} in)"
            )
        if abs(end_off[1]) > marks.max_heading_deg:
            failures.append(
                f"it ends turned {abs(end_off[1]):.1f} degrees from the simulated end (the "
                f"mark: {marks.max_heading_deg:g} degrees)"
            )
    if rms is not None and rms > marks.max_distance_in:
        failures.append(
            f"through the run, its code's pose is {rms:.1f} in from the simulated runs' (RMS; the "
            f"mark: {marks.max_distance_in:g} in)"
        )
    return AutonCheck(
        routine,
        start,
        marks,
        list(runs),
        list(sims),
        end_off,
        rms,
        sim_spread,
        real_spread,
        warnings,
        failures,
    )


def check_auton(
    robot: str | Path,
    field: str | Path,
    project: str | Path,
    logs: Sequence[str | Path],
    ends: Sequence[str | None],
    *,
    marks: Marks | None = None,
    routine: str | None = None,
    seeds: int = SEEDS,
    env: dict[str, str] | None = None,
    workers: int = 1,
    say: Say | None = None,
) -> AutonCheck:
    """The whole check: each real ``logs``' run (its end measured as ``ends`` say, in
    ``parse_end``'s words) against the routine simulated from where they started."""
    from vexsim.app.runspec import RunError, RunSpec, routine_start
    from vexsim.config import load_field, load_robot

    say = say or (lambda text: None)
    if len(ends) != len(logs):
        raise AutonError("give one --end for each log: where each run's robot ended")
    config, field_config = load_robot(robot), load_field(field)
    names = [Path(p).name for p in logs]
    runs = []
    for path, end in zip(logs, ends, strict=True):
        try:
            log = RobotLog.read(path)
        except (OSError, ValueError) as exc:
            raise AutonError(f"{path}: {exc}") from None
        pose = end_pose(config, field_config, parse_end(end)) if end else None
        shown = Path(path).name
        if names.count(shown) > 1:  # each card numbers its logs from 1: say which card's
            shown = f"{Path(path).parent.name}/{shown}"
        runs.append(RealRun(shown, log, pose))
    named = {run.log.info.get("name", "") for run in runs}
    if len(named) > 1:
        raise AutonError(
            "the logs are of different routines (" + ", ".join(sorted(named)) + "): check one "
            "routine at a time"
        )
    first = code_path(runs[0].log)
    if first is None:
        raise AutonError(
            f"{runs[0].file} has no pose of its code's (vexsim_log::pose): vexsim can't tell "
            "where the routine started"
        )
    x, y, theta = first[1][0]
    start = (round(float(x), 2), round(float(y), 2), round(math.degrees(theta) % 360, 2))
    name = runs[0].log.info.get("name", "")
    routine = routine or routine_for(project, name)
    exact = routine_start(str(project), routine)  # its setPose, as the code says it
    if exact is not None and (
        math.dist(exact[:2], start[:2]) <= 2.0 and abs(_heading_gap(exact[2], start[2])) <= 5.0
    ):
        start = exact
    marks = marks or Marks()
    say(f"{routine}, from {start[0]:g}, {start[1]:g}, {start[2]:g} deg; {seeds} seeds")
    spec = RunSpec(
        robot=str(robot),
        program=str(project),
        routine=routine,
        field=str(field),
        mode="autonomous",
        start=start,
        env=dict(env or {}),
    )
    try:
        sims = simulate_routine(spec, list(range(seeds)), workers=workers, say=say)
    except RunError as exc:
        raise AutonError(exc.message) from None
    return compare(routine, start, marks, runs, sims)


# --- the report -------------------------------------------------------------------------------


def _pose_text(pose: Sequence[float]) -> str:
    x, y, h = pose
    return f"x {x:.2f} in, y {y:.2f} in, heading {h:.1f} degrees"


def report_text(check: AutonCheck, plots: Sequence[Path] = ()) -> str:
    """The check, in words (Markdown)."""
    m = check.marks
    verdict = "**passes**" if check.passed else "**fails**"
    lines = [
        f"# Autonomous check: {check.routine}",
        "",
        f"The simulated routine {verdict} against {len(check.runs)} real run"
        f"{'s' if len(check.runs) > 1 else ''}, at the pass marks {m.max_distance_in:g} in and "
        f"{m.max_heading_deg:g} degrees ({m.source}).",
        "",
    ]
    if check.failures:
        lines += [f"- {f}" for f in check.failures] + [""]
    if check.warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in check.warnings] + [""]
    lines += [
        "## Where it ended",
        "",
        f"Simulated from {_pose_text(check.start)} (the routine's setPose), {len(check.sims)} "
        "times (seeds), each until the robot was still after the period ended.",
        "",
        "| Run | Ended at | From the simulated end |",
        "|---|---|---|",
    ]
    for run in check.runs:
        off = "" if run.end_off is None else f"{run.end_off[0]:.2f} in, {run.end_off[1]:+.1f} deg"
        where = "not measured" if run.end is None else _pose_text(run.end.pose)
        lines.append(f"| {run.file} (measured) | {where} | {off} |")
    for sim in check.sims:
        lines.append(f"| seed {sim.seed} (simulated) | {_pose_text(sim.end)} | |")
    lines.append(f"| the seeds' mean | {_pose_text(check.sim_end)} | |")
    lines.append("")
    if check.end_off is not None:
        lines.append(
            f"The real end is {check.end_off[0]:.2f} in and {check.end_off[1]:+.1f} degrees from "
            "the simulated one."
        )
    spread_text = f"The simulated runs end within {check.sim_spread[0]:.2f} in and "
    spread_text += f"{check.sim_spread[1]:.1f} degrees of their mean"
    if check.real_spread is not None:
        spread_text += (
            f"; the real ones within {check.real_spread[0]:.2f} in and "
            f"{check.real_spread[1]:.1f} degrees of theirs"
        )
    lines += [spread_text + ".", ""]
    lines += ["## Through the run", ""]
    for run in check.runs:
        apart = check.apart(run)
        if apart is None:
            lines.append(f"- {run.file}: no pose of its code's to compare.")
            continue
        t, mean, _ = apart
        worst = int(np.argmax(mean))
        over = float(np.mean(mean > m.max_distance_in)) if len(mean) else 0.0
        parted = (
            "never more than the mark apart for half a second"
            if run.parted_s is None
            else f"first more than the mark apart (for half a second) at {run.parted_s:.1f} s"
        )
        lines.append(
            f"- {run.file}: its code's pose is {run.run_rms_in:.2f} in from the simulated runs' "
            f"(RMS); furthest at {t[worst]:.1f} s ({mean[worst]:.1f} in); over the mark "
            f"{over:.0%} of the time; it parts {parted}."
        )
    lines.append("")
    for path in plots:
        lines += [f"![{path.stem}]({path.name})", ""]
    return "\n".join(lines).rstrip() + "\n"


def write_report(
    check: AutonCheck, config: RobotConfig, field: FieldConfig, folder: str | Path
) -> Path:
    """report.md and its plots (with matplotlib) in ``folder``."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    plots: list[Path] = []
    try:
        import matplotlib  # noqa: F401
    except ModuleNotFoundError:
        pass
    else:
        plots = [
            _plot_paths(check, config, field, folder / "paths.png"),
            _plot_apart(check, folder / "apart.png"),
        ]
        readings = _plot_readings(check, config, folder / "readings.png")
        if readings is not None:
            plots.append(readings)
    path = folder / "report.md"
    path.write_text(report_text(check, plots), encoding="utf-8", newline="\n")
    return path


REAL_COLOR, SIM_COLOR, MARK_COLOR = "#222222", "#2f6db5", "#c0392b"


def _outline(ax, config: RobotConfig, pose: Sequence[float], **style) -> None:
    from matplotlib.patches import Polygon

    x, y, h = pose
    c, s = math.cos(math.radians(h)), math.sin(math.radians(h))
    for loop in config.body.outline.loops():
        points = np.array([(x + c * px - s * py, y + s * px + c * py) for px, py in loop])
        ax.add_patch(Polygon(points, fill=False, **style))


def _plot_paths(check: AutonCheck, config: RobotConfig, field: FieldConfig, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from vexsim.calibration.plan import draw_field

    fig = plt.figure(figsize=(7.2, 7.6), dpi=110)
    ax = fig.add_axes((0.02, 0.02, 0.96, 0.9))
    ax.set_axis_off()
    draw_field(ax, field)
    _outline(ax, config, check.start, ec="#888888", lw=1.0, ls="--", zorder=4)
    for k, sim in enumerate(check.sims):
        found = code_path(sim.log) if sim.log is not None else None
        if found is not None:
            _, poses = found
            label = "simulated (the code's pose)" if k == 0 else None
            ax.plot(poses[:, 0], poses[:, 1], color=SIM_COLOR, lw=0.9, alpha=0.8, label=label)
        _outline(ax, config, sim.end, ec=SIM_COLOR, lw=1.0, zorder=5)
    for k, run in enumerate(check.runs):
        if run.path is not None:
            label = "real (the code's pose)" if k == 0 else None
            ax.plot(run.path[1][:, 0], run.path[1][:, 1], color=REAL_COLOR, lw=1.4, label=label)
        if run.end is not None:
            _outline(ax, config, run.end.pose, ec=REAL_COLOR, lw=1.8, zorder=6)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.06), ncol=2, frameon=False, fontsize=8)
    ax.set_title(f"{check.routine}: the real run and the simulated ones", fontsize=11, pad=24)
    fig.savefig(path)
    plt.close(fig)
    return path


def _plot_apart(check: AutonCheck, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.0, 3.2), dpi=110)
    for run in check.runs:
        apart = check.apart(run)
        if apart is None:
            continue
        t, mean, each = apart
        for d in each:
            ax.plot(t, d, color=SIM_COLOR, lw=0.6, alpha=0.5)
        ax.plot(t, mean, color=REAL_COLOR, lw=1.4, label=f"{run.file}: from the seeds' mean")
        if run.parted_s is not None:
            ax.axvline(run.parted_s, color=MARK_COLOR, lw=0.8, ls=":")
    ax.axhline(check.marks.max_distance_in, color=MARK_COLOR, lw=1.0, ls="--", label="the mark")
    ax.set_xlabel("time from the routine's setPose (s)")
    ax.set_ylabel("in apart")
    ax.set_title("The code's pose, real against simulated (thin: each seed)", fontsize=10)
    ax.grid(True, color="#dddddd")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _aligned(log: RobotLog) -> np.ndarray | None:
    from vexsim.runtime.follow import set_pose_time

    t0 = set_pose_time(log)
    return None if t0 is None else log.time_s - t0


def _plot_readings(check: AutonCheck, config: RobotConfig, path: Path) -> Path | None:
    """The IMU's turn, each drive side's wheel travel and each distance sensor's readings
    over time, real against simulated."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    logs = [(run.file, run.log, REAL_COLOR, 1.3) for run in check.runs] + [
        (f"seed {s.seed}", s.log, SIM_COLOR, 0.8) for s in check.sims if s.log is not None
    ]
    if not logs:
        return None
    panels: list[tuple[str, Callable[[RobotLog], np.ndarray | None]]] = []
    imus = [s.port for s in config.sensors if s.type == "imu"]
    if imus:
        port = imus[0]

        def turn(log: RobotLog, port=port) -> np.ndarray | None:
            column, t = f"imu{port}_deg", _aligned(log)
            if column not in log or t is None:
                return None
            at = int(np.argmin(np.abs(t)))
            return log[column] - log[column][at]

        panels.append(("IMU: turned since the setPose (deg, clockwise +)", turn))
    for name, group in config.drivetrain.gearing.items():
        ports = [abs(p) for p in group.motors]
        diameter = config.drivetrain.wheel(group.wheels[0]).diameter_in
        per_deg = group.speed_ratio * math.pi * diameter / 360.0
        signs = {abs(p): (1.0 if p > 0 else -1.0) for p in group.motors}

        def travel(log: RobotLog, ports=ports, per_deg=per_deg, signs=signs):
            t = _aligned(log)
            columns = [signs[p] * log[f"m{p}_deg"] for p in ports if f"m{p}_deg" in log]
            if not columns or t is None:
                return None
            moved = np.nanmean(columns, axis=0)
            at = int(np.argmin(np.abs(t)))
            return (moved - moved[at]) * per_deg

        panels.append((f"{name} wheels: travel since the setPose (in)", travel))
    for s in config.sensors:
        if s.type == "distance":
            panels.append(
                (
                    f"distance sensor {s.port} (mm)",
                    lambda log, port=s.port: log[f"d{port}_mm"] if f"d{port}_mm" in log else None,
                )
            )
    fig, axes = plt.subplots(len(panels), 1, figsize=(8.0, 1.7 * len(panels) + 0.6), sharex=True)
    axes = [axes] if len(panels) == 1 else list(axes)
    for ax, (title, values) in zip(axes, panels, strict=True):
        for name, log, color, width in logs:
            t, v = _aligned(log), values(log)
            if t is None or v is None:
                continue
            ax.plot(t, v, color=color, lw=width, label=name if ax is axes[0] else None)
        ax.set_title(title, fontsize=9, loc="left")
        ax.grid(True, color="#dddddd")
        ax.set_xlim(left=0)
    axes[-1].set_xlabel("time from the routine's setPose (s)")
    axes[0].legend(fontsize=7, frameon=False, ncol=4)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path

"""A run of the simulator, as ``vexsim run`` takes it, and how to get it ready to start.

``RunSpec`` holds what decides what is simulated: the robot, program (and for a PROS
project, the autonomous routine picked), field, start pose, mode, seed, noise, scripted
input or a log to follow, and the program's environment. It
converts to and from ``vexsim run``'s arguments, so the UI can show any run as a command.

Getting a run ready takes three steps, which the CLI runs one after another and the UI
spreads over its server, a build job and a worker process:
1. ``check`` loads and validates the configs and finds the program (no user code runs);
2. ``build`` compiles a PROS project (a ``Job`` in the UI);
3. ``program_factory`` and ``simulation_factory`` make the program and the simulation.
"""

from __future__ import annotations

import argparse
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vexsim.config.field import FieldConfig
from vexsim.config.issues import ConfigIssue
from vexsim.config.robot import RobotConfig

Mode = Literal["autonomous", "driver", "match", "skills"]
Noise = Literal["ideal", "default", "harsh"]
Sticks = Literal["tank", "arcade"]
MODES: tuple[str, ...] = ("autonomous", "driver", "match", "skills")
NOISE_PRESETS: tuple[str, ...] = ("ideal", "default", "harsh")
DEFAULT_BUSY_TIMEOUT_S = 5.0


class RunError(Exception):
    """A run can't start: a config error, a missing file, a bad argument or a failed build.

    ``issues`` holds config problems (printed one per line); ``message`` says what's wrong
    otherwise.
    """

    def __init__(self, message: str, issues: list[ConfigIssue] | None = None, *, source: str = ""):
        self.message = message
        self.issues = list(issues or [])
        self.source = source
        super().__init__(message)


class Follow(BaseModel):
    """A virtual driver that drives the robot along a log's path (``vexsim.runtime.follow``):
    the program's driver control, through its own sticks and drive curve."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    log: str | None = None  # an MCL log; a saved run leaves it out, for any log to follow
    sticks: Sticks = "tank"  # tank: both sticks' y; arcade: left y forward, right x turning
    # the program's LemLib ExpoDriveCurve(deadband, min output, curve), if it has one
    curve: tuple[float, float, float] | None = None


class RunSpec(BaseModel):
    """Everything ``vexsim run`` takes that decides what is simulated.

    Paths are as given: relative to the working directory for the CLI, to the workspace
    for the UI (``resolved`` makes them absolute). ``start`` is x, y (inches) and heading
    (degrees, counter-clockwise from +x).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    robot: str
    program: str | None = None
    routine: str | None = None  # a PROS project's, run inside autonomous() (bridge/routines.py)
    field: str | None = None
    mode: Mode | None = None
    start: tuple[float, float, float] = (0.0, 0.0, 0.0)
    seed: int = 0
    noise: Noise | None = None
    input: str | None = None
    follow: Follow | None = None
    env: dict[str, str] = Field(default_factory=dict)
    busy_timeout: float = DEFAULT_BUSY_TIMEOUT_S

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> RunSpec:
        """The spec of a parsed ``vexsim run`` command line. A run that follows a log
        starts where the log does, and one with a routine where its setPose puts it, unless
        ``--start`` says otherwise."""
        follow = None
        if getattr(args, "follow", None):
            curve = parse_curve(args.curve) if args.curve else None
            follow = Follow(log=args.follow, sticks=args.sticks or "tank", curve=curve)
        elif getattr(args, "sticks", None) or getattr(args, "curve", None):
            raise RunError("--sticks and --curve go with --follow")
        routine = getattr(args, "routine", None)
        if args.start is not None:
            start = (args.start.x, args.start.y, args.start.heading)
        elif follow is not None:
            start = log_start(follow.log)
        else:
            start = routine_start(args.program, routine) or (0.0, 0.0, 0.0)
        return cls(
            robot=args.robot,
            program=args.program,
            routine=routine,
            field=args.field,
            mode=args.mode,
            start=start,
            seed=args.seed,
            noise=args.noise,
            input=args.input,
            follow=follow,
            env=parse_env(args.env or ()),
            busy_timeout=args.busy_timeout,
        )

    def to_args(self) -> list[str]:
        """``vexsim run``'s arguments for this spec (defaults left out)."""
        args = ["run", self.robot]
        for flag, value in (
            ("--program", self.program),
            ("--routine", self.routine),
            ("--field", self.field),
        ):
            if value:
                args += [flag, value]
        if self.mode:
            args += ["--mode", self.mode]
        if any(self.start):
            args.append("--start=" + ",".join(_number(v) for v in self.start))
        if self.seed:
            args += ["--seed", str(self.seed)]
        if self.noise:
            args += ["--noise", self.noise]
        if self.input:
            args += ["--input", self.input]
        if self.follow is not None:
            if self.follow.log:
                args += ["--follow", self.follow.log]
            if self.follow.sticks != "tank":
                args += ["--sticks", self.follow.sticks]
            if self.follow.curve:
                args.append("--curve=" + ",".join(_number(v) for v in self.follow.curve))
        for key, value in self.env.items():
            args += ["--env", f"{key}={value}"]
        if self.busy_timeout != DEFAULT_BUSY_TIMEOUT_S:
            args += ["--busy-timeout", _number(self.busy_timeout)]
        return args

    def command_line(self) -> str:
        """The command that runs this spec, as typed in a terminal."""
        return " ".join(["vexsim", *(quote_arg(a) for a in self.to_args())])

    def resolved(self, base: str | os.PathLike[str] | None) -> RunSpec:
        """A copy with every relative path made absolute against ``base`` (None: as is)."""
        if base is None:
            return self
        root = Path(base)

        def absolute(path: str | None) -> str | None:
            if path is None or Path(path).is_absolute():
                return path
            return str(root / path)

        follow = self.follow
        if follow is not None and follow.log:
            follow = follow.model_copy(update={"log": absolute(follow.log)})
        return self.model_copy(
            update={
                "robot": absolute(self.robot),
                "program": absolute(self.program),
                "field": absolute(self.field),
                "input": absolute(self.input),
                "follow": follow,
            }
        )


def routine_start(project: str | None, routine: str | None) -> tuple[float, float, float] | None:
    """Where a PROS project's routine starts (its setPose), if it says."""
    from vexsim.bridge.routines import find_routines

    if not project or not routine or not Path(project).is_dir():
        return None
    found = find_routines(project)
    picked = found.named(routine) if found else None
    return picked.start_pose() if picked else None


def parse_curve(text: str) -> tuple[float, float, float]:
    """``--curve DEADBAND,MIN_OUTPUT,CURVE`` (LemLib's ExpoDriveCurve) as numbers."""
    import math

    try:
        values = tuple(float(v) for v in text.split(","))
    except ValueError:
        values = ()
    if len(values) != 3 or not all(math.isfinite(v) for v in values):
        raise RunError(f"--curve needs DEADBAND,MIN_OUTPUT,CURVE (e.g. 15,20,1.05), got {text!r}")
    return values  # type: ignore[return-value]


def log_start(path: str | os.PathLike[str]) -> tuple[float, float, float]:
    """Where a log to follow starts: x, y (in) and heading (degrees counter-clockwise
    from +x), rounded as a start pose is typed. Raises RunError if it doesn't read."""
    from vexsim.mcllog import MclLog, MclLogError

    try:
        x, y, heading = MclLog.read(path).start
    except MclLogError as exc:
        raise RunError(f"{path}: {exc}") from None
    return (round(x, 2), round(y, 2), round(heading % 360, 2))


def parse_env(items) -> dict[str, str]:
    """``KEY=VALUE`` strings (``--env``) as a dict; raises RunError on anything else."""
    env: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise RunError(f"--env needs KEY=VALUE, got {item!r}")
        env[key] = value
    return env


_SAFE = re.compile(r"^[A-Za-z0-9_\-./:=,+@%]+$")


def quote_arg(arg: str) -> str:
    """An argument as typed in a terminal: quoted when it has spaces or shell characters."""
    if _SAFE.match(arg):
        return arg
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _number(value: float) -> str:
    return f"{value:.10g}"


def is_pros_project(path: str | os.PathLike[str]) -> bool:
    """Whether ``--program`` names a PROS project (its folder, or its project.pros)."""
    p = Path(path)
    return p.is_dir() or p.name == "project.pros"


@dataclass
class Prepared:
    """A checked spec: its configs loaded, its program found (but not loaded or built)."""

    spec: RunSpec
    config: RobotConfig
    field: FieldConfig | None
    project: Path | None = None  # the PROS project folder, if the program is one
    program_file: Path | None = None  # the Python program, if the program is one
    follow: Any = None  # the path to follow (vexsim.runtime.follow.LoggedPath), if any
    warnings: list[ConfigIssue] = field(default_factory=list)


def check(spec: RunSpec, base: str | os.PathLike[str] | None = None) -> Prepared:
    """Load and validate what ``spec`` names, relative to ``base``. No robot code runs.

    Raises RunError: the robot's or the field's config issues, or a missing file.
    """
    from vexsim.config.loader import validate_field, validate_robot

    named, spec = spec, spec.resolved(base)  # messages name files as the spec does
    robot = validate_robot(spec.robot)
    if not robot.ok or robot.config is None:
        raise RunError(f"{named.robot}: invalid robot config", robot.issues, source=named.robot)
    warnings = list(robot.warnings)
    field_config = None
    if spec.field:
        report = validate_field(spec.field)
        if not report.ok:
            message = f"{named.field}: invalid field config"
            raise RunError(message, report.issues, source=named.field or "")
        field_config = report.config
        warnings += report.warnings
    prepared = Prepared(spec, robot.config, field_config, warnings=warnings)
    if spec.program:
        if is_pros_project(spec.program):
            project = Path(spec.program)
            prepared.project = project if project.is_dir() else project.parent
        elif Path(spec.program).is_file():
            prepared.program_file = Path(spec.program)
        else:
            raise RunError(f"program not found: {named.program}")
    if spec.routine:
        _check_routine(prepared, named)
    if spec.input and not Path(spec.input).is_file():
        raise RunError(f"input not found: {named.input}")
    if spec.follow is not None:
        prepared.follow = _path_to_follow(spec, named)
    for where in start_blocked(robot.config, field_config, spec.start):
        message = (
            "the robot starts partly outside the walls; move its start in"
            if where == WALLS
            else f"the robot starts on top of {where}; move its start"
        )
        prepared.warnings.append(ConfigIssue("warning", "start", message))
    return prepared


def _check_routine(prepared: Prepared, named: RunSpec) -> None:
    """The routine picked is one of the PROS project's (bridge/routines.py)."""
    from vexsim.bridge.routines import AUTON_HEADER, find_routines

    routine = prepared.spec.routine
    if prepared.project is None:
        raise RunError(f"{routine}() is a PROS project's routine, but the program isn't one")
    found = find_routines(prepared.project)
    if found is None:
        raise RunError(f"{named.program} has no {AUTON_HEADER}, so no routines to pick from")
    picked = found.named(routine)
    if picked is None:
        other = next((o for o in found.others if o.name == routine), None)
        if other is not None:
            raise RunError(f"{routine}() {other.why}, so it isn't a routine ({AUTON_HEADER})")
        names = ", ".join(r.name for r in found.routines) or "none"
        raise RunError(f"there's no routine {routine}() in {AUTON_HEADER} (its routines: {names})")
    if picked.source is None:
        raise RunError(
            f"{routine}() is declared in {AUTON_HEADER}, but vexsim can't tell which file "
            "defines it, so a run can't pick it"
        )
    if prepared.spec.mode == "driver":
        message = "a routine runs in the autonomous period: in autonomous, match or skills mode"
        prepared.warnings.append(ConfigIssue("warning", "routine", message))


def _path_to_follow(spec: RunSpec, named: RunSpec):
    from vexsim.mcllog import MclLog, MclLogError
    from vexsim.runtime.follow import LoggedPath

    if spec.input:
        raise RunError("a run follows a log or takes scripted input, not both")
    if not spec.follow.log:
        raise RunError("pick the log to follow")
    shown = named.follow.log
    if not Path(spec.follow.log).is_file():
        raise RunError(f"log not found: {shown}")
    try:
        return LoggedPath(*MclLog.read(spec.follow.log).path())
    except MclLogError as exc:
        raise RunError(f"{shown}: {exc}") from None


WALLS = "the walls"


def start_blocked(
    config: RobotConfig, field: FieldConfig | None, start: tuple[float, float, float]
) -> list[str]:
    """What the robot would start on top of: solid field elements its footprint overlaps,
    and the walls if it sticks out past them. The physics can't untangle that well."""
    import math

    from vexsim.physics.arena import Arena
    from vexsim.physics.params import resolve_params
    from vexsim.units import in_to_m

    field = field or FieldConfig()
    x, y, heading = in_to_m(start[0]), in_to_m(start[1]), math.radians(start[2])
    if config.body.shape is not None:
        return _shape_blocked(config, field, (x, y, heading))
    length, width = (in_to_m(v) / 2 for v in config.body.footprint_in)
    c, s = math.cos(heading), math.sin(heading)
    box = [(length, width), (-length, width), (-length, -width), (length, -width)]
    corners = [(x + c * u - s * v, y + s * u + c * v) for u, v in box]
    blocked = []
    room_x, room_y = (in_to_m(v) / 2 for v in field.size_in)
    if any(abs(px) > room_x + 1e-4 or abs(py) > room_y + 1e-4 for px, py in corners):
        blocked.append(WALLS)
    if field.elements:
        for shape in Arena.of(field, resolve_params(config.overrides).field).obstacles:
            if shape.solid and _overlaps(corners, (x, y, heading, length, width), shape):
                blocked.append(shape.name)
    return blocked


def _shape_blocked(
    config: RobotConfig, field: FieldConfig, pose: tuple[float, float, float]
) -> list[str]:
    """``start_blocked`` for a robot with a ``body.shape``: in its own frame, meters."""
    import math

    from vexsim.geometry import Polygon
    from vexsim.physics.arena import Arena
    from vexsim.physics.params import resolve_params
    from vexsim.units import in_to_m

    tolerance = 1e-4  # touching isn't overlapping
    outline = config.body.outline.mapped(in_to_m(1.0))
    x, y, heading = pose
    c, s = math.cos(heading), math.sin(heading)
    blocked = []
    room = [in_to_m(v) / 2 for v in field.size_in]
    for axis, sign in ((0, 1.0), (0, -1.0), (1, 1.0), (1, -1.0)):
        # how far the robot reaches toward this wall: the wall's direction in its frame
        toward = (sign * c, -sign * s) if axis == 0 else (sign * s, sign * c)
        if sign * (x, y)[axis] + outline.extreme(toward) > room[axis] + tolerance:
            blocked.append(WALLS)
            break
    if field.elements:
        for shape in Arena.of(field, resolve_params(config.overrides).field).obstacles:
            if not shape.solid:
                continue
            dx, dy = shape.center[0] - x, shape.center[1] - y
            center = (c * dx + s * dy, -s * dx + c * dy)
            if shape.circle:
                inside = outline.signed_distance(center)[0] < shape.half[0] - tolerance
            else:
                half = (shape.half[0] - tolerance, shape.half[1] - tolerance)
                inside = min(half) > 0 and outline.overlaps(
                    Polygon.rect(center, (2 * half[0], 2 * half[1]), shape.heading - heading)
                )
            if inside:
                blocked.append(shape.name)
    return blocked


def _overlaps(corners, box, shape, tolerance: float = 1e-4) -> bool:
    """Whether a rectangle (its corners, and center, heading, half sizes) overlaps a field
    obstacle by more than ``tolerance`` meters (touching isn't overlapping)."""
    import math

    x, y, heading, half_x, half_y = box
    if shape.circle:  # the circle's center, in the box's frame, to the box's nearest point
        c, s = math.cos(heading), math.sin(heading)
        dx, dy = shape.center[0] - x, shape.center[1] - y
        u, v = c * dx + s * dy, -s * dx + c * dy
        nearest = math.hypot(u - max(-half_x, min(half_x, u)), v - max(-half_y, min(half_y, v)))
        return nearest < shape.half[0] - tolerance
    other = [tuple(p) for p in shape.corners()]
    for angle in (heading, heading + math.pi / 2, shape.heading, shape.heading + math.pi / 2):
        axis = (math.cos(angle), math.sin(angle))  # separating axis test
        a = [px * axis[0] + py * axis[1] for px, py in corners]
        b = [px * axis[0] + py * axis[1] for px, py in other]
        if min(max(a), max(b)) - max(min(a), min(b)) <= tolerance:
            return False
    return True


def build(prepared: Prepared, log: Callable[[str], None] | None = print) -> Path:
    """Compile the PROS project (incrementally); returns the robot host executable."""
    from vexsim.bridge.build import BuildError, build_project

    if prepared.project is None:
        raise ValueError("this run's program isn't a PROS project")
    try:
        result = build_project(prepared.project, log=log)
    except BuildError as exc:
        raise RunError(str(exc)) from None
    routine = prepared.spec.routine
    if routine and routine not in result.routines:
        why = next((n for n in result.notes if n.startswith(f"{routine}() ")), None)
        raise RunError(why or f"the build has no routine {routine}() to pick")
    return result.executable


def program_factory(
    prepared: Prepared, executable: str | os.PathLike[str] | None = None
) -> tuple[Callable[[], Any], str]:
    """A function that makes the program for each simulation, and the competition mode.

    A Python program is imported here, in this process, with the spec's environment
    variables set; a PROS project needs its ``executable`` (see ``build``) and gets them
    through its robot host process.
    """
    spec = prepared.spec
    if prepared.project is not None:
        from vexsim.bridge.program import CppProgram

        if executable is None:
            raise ValueError("a PROS project needs its executable: build it first")
        name = prepared.project.resolve().name

        def make_cpp():
            return CppProgram(
                executable,
                name=name,
                busy_timeout_s=spec.busy_timeout,
                env=dict(spec.env),
                routine=spec.routine,
            )

        return make_cpp, spec.mode or "autonomous"

    from vexsim.runtime.program import load_program

    os.environ.update(spec.env)  # a Python program runs in this process
    module = load_program(prepared.program_file) if prepared.program_file else None
    mode = spec.mode or ("autonomous" if hasattr(module, "autonomous") else "driver")
    if mode in ("autonomous", "skills") and not hasattr(module, "autonomous"):
        what = f"{prepared.program_file.name} has none" if module else "there's no program"
        raise RunError(
            f"{mode} mode runs the program's autonomous(), and {what}: "
            "pick a program that has one, or driver or match mode"
        )
    return (lambda: module), mode


def simulation_factory(
    prepared: Prepared,
    make_program: Callable[[], Any],
    mode: str,
    *,
    input_source=None,
    echo: Callable[[str], None] | None = print,
    on_create: Callable[[Any], None] | None = None,
) -> Callable[[], Any]:
    """A function that makes a fresh Simulation of the run, started in ``mode``.

    ``on_create(sim)`` runs before the mode starts (e.g. to attach a logger). A run that
    follows a log gets a new ``PathFollower`` each time, as its input, not ``input_source``.
    """
    from vexsim.algorithms.localization.base import Pose
    from vexsim.runtime.follow import PathFollower, drive_geometry
    from vexsim.runtime.simulation import Simulation

    spec = prepared.spec

    def factory():
        source = input_source
        if prepared.follow is not None:
            track, top_speed = drive_geometry(prepared.config)
            source = PathFollower(
                prepared.follow,
                track_in=track,
                top_speed_in_s=top_speed,
                sticks=spec.follow.sticks,
                curve=spec.follow.curve,
            )
        sim = Simulation(
            prepared.config,
            program=make_program(),
            field=prepared.field,
            seed=spec.seed,
            noise=spec.noise,
            start=Pose(*spec.start),
            input_source=source,
            echo=echo,
        )
        if prepared.follow is not None:
            source.attach(sim)
        if on_create is not None:
            on_create(sim)
        sim.start(mode)
        return sim

    return factory

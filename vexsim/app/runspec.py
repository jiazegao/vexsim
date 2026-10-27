"""A run of the simulator, as ``vexsim run`` takes it, and how to get it ready to start.

``RunSpec`` holds what decides what is simulated: the robot, program, field, start pose,
mode, seed, noise, scripted input and the program's environment. It converts to and from
``vexsim run``'s arguments, so the UI can show any run as a command.

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


class RunSpec(BaseModel):
    """Everything ``vexsim run`` takes that decides what is simulated.

    Paths are as given: relative to the working directory for the CLI, to the workspace
    for the UI (``resolved`` makes them absolute). ``start`` is x, y (inches) and heading
    (degrees, counter-clockwise from +x).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    robot: str
    program: str | None = None
    field: str | None = None
    mode: Mode | None = None
    start: tuple[float, float, float] = (0.0, 0.0, 0.0)
    seed: int = 0
    noise: Noise | None = None
    input: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    busy_timeout: float = DEFAULT_BUSY_TIMEOUT_S

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> RunSpec:
        """The spec of a parsed ``vexsim run`` command line."""
        start = args.start
        return cls(
            robot=args.robot,
            program=args.program,
            field=args.field,
            mode=args.mode,
            start=(start.x, start.y, start.heading),
            seed=args.seed,
            noise=args.noise,
            input=args.input,
            env=parse_env(args.env or ()),
            busy_timeout=args.busy_timeout,
        )

    def to_args(self) -> list[str]:
        """``vexsim run``'s arguments for this spec (defaults left out)."""
        args = ["run", self.robot]
        for flag, value in (("--program", self.program), ("--field", self.field)):
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

        return self.model_copy(
            update={
                "robot": absolute(self.robot),
                "program": absolute(self.program),
                "field": absolute(self.field),
                "input": absolute(self.input),
            }
        )


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
    if spec.input and not Path(spec.input).is_file():
        raise RunError(f"input not found: {named.input}")
    for where in start_blocked(robot.config, field_config, spec.start):
        message = (
            "the robot starts partly outside the walls; move its start in"
            if where == WALLS
            else f"the robot starts on top of {where}; move its start"
        )
        prepared.warnings.append(ConfigIssue("warning", "start", message))
    return prepared


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
        return build_project(prepared.project, log=log).executable
    except BuildError as exc:
        raise RunError(str(exc)) from None


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
                executable, name=name, busy_timeout_s=spec.busy_timeout, env=dict(spec.env)
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

    ``on_create(sim)`` runs before the mode starts (e.g. to attach a logger).
    """
    from vexsim.algorithms.localization.base import Pose
    from vexsim.runtime.simulation import Simulation

    spec = prepared.spec

    def factory():
        sim = Simulation(
            prepared.config,
            program=make_program(),
            field=prepared.field,
            seed=spec.seed,
            noise=spec.noise,
            start=Pose(*spec.start),
            input_source=input_source,
            echo=echo,
        )
        if on_create is not None:
            on_create(sim)
        sim.start(mode)
        return sim

    return factory

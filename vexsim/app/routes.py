"""Autonomous routes (phase 13): a route file, read and checked, and what its runner reads.

A route is a YAML file in a PROS project's ``routes/`` folder (PLAN.md section 15): its
name, the robot and field it's drawn and simulated with (paths relative to the file), its
start pose (the routine's ``chassis.setPose``), the headers its functions come from, and
its steps. Numbers are in LemLib's convention, as the robot's code has them: inches, and
theta in degrees clockwise from +y.

```yaml
version: 1
name: Left 40
robot: ../../../robots/1239e_2026-27.yaml
start: [60, 0, 90]
functions: [include/custom/util_funcs.hpp, include/custom/lift_control.hpp]
steps:
  - {call: moveForward, args: {inches: -10, timeout: 800}}
  - {turn_to_heading: 270, timeout: 800, max_speed: 100, async: true}
  - {move_to_point: [14, 0], timeout: 1000, max_speed: 60}
  - {call: startFrontIntake}
  - {wait: 100}
```

A step is a LemLib 0.5 motion (``MOTIONS``, with its timeout, ``OPTIONS`` and ``async``), one
of vexsim's own (bridge/cpp/motions: ``move_arc`` and ``ramsete``, which drive with a model of
the drive that the route's ``drive:`` section may give, else vexsim's for the robot), a
pause (``wait`` ms, ``wait_until`` inches or degrees along the motion before it,
``wait_until_done``) or a ``call`` of one of the team's functions (bridge/functions.py),
its arguments by parameter name.

```yaml
  - {move_arc: [18, 90], timeout: 1500}           # 90 degrees clockwise, on an 18 in radius
  - {ramsete: [[24, 24], [48, 0]], timeout: 3000, end_heading: 90, max_velocity: 50}
```

``read_route`` reads a route's data, each problem at its place (a dotted location, as
configs have them: ``steps[2].timeout``); ``check_route`` checks it against its project,
robot and field; ``check_text`` does both for the browser's editor, each issue at its line;
``runner_input`` writes the steps as vexsim's route runner reads them (bridge/runner.py).
"""

from __future__ import annotations

import dataclasses
import difflib
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vexsim.config.issues import ConfigIssue

VERSION = 1
FOLDER = "routes"  # a project's routes are in <project>/routes/*.yaml
AUTONOMOUS_S = 15.0  # a match's autonomous period, which a route's time is measured against
PATH_MS = 20  # how often a route's run notes where the robot is

Value = int | float | bool | str


@dataclass(frozen=True)
class Option:
    lemlib: str  # the field of LemLib's params struct (vexsim's, for its own motions)
    kind: str  # "bool", "number", "speed", "direction", "positive" or "angle"
    default: Value | None  # LemLib's; None: the drive model's, or the path's own


# A motion's options, in the order LemLib's params structs declare them (an export writes
# them as designated initializers, which must keep that order)
OPTIONS: dict[str, Option] = {
    "forwards": Option("forwards", "bool", True),
    "horizontal_drift": Option("horizontalDrift", "number", 0),
    "lead": Option("lead", "number", 0.6),
    "direction": Option("direction", "direction", "auto"),
    "max_speed": Option("maxSpeed", "speed", 127),
    "min_speed": Option("minSpeed", "speed", 0),
    "early_exit": Option("earlyExitRange", "number", 0),
    # vexsim's own motions': the speed (in/s) and acceleration (in/s^2) they plan within, and
    # the heading a path ends at (degrees)
    "max_velocity": Option("maxVelocity", "positive", None),
    "max_accel": Option("maxAccel", "positive", None),
    "end_heading": Option("endHeading", "angle", None),
}
DIRECTIONS = {"cw": "CW_CLOCKWISE", "ccw": "CCW_COUNTERCLOCKWISE", "auto": "AUTO"}
SIDES = {"left": "LEFT", "right": "RIGHT"}


@dataclass(frozen=True)
class Motion:
    lemlib: str  # the Chassis method (vexsim::Motions', for its own)
    target: tuple[str, ...]  # what the step's own key holds: x, y (and theta), or theta...
    options: tuple[str, ...]
    swing: bool = False  # it takes a locked side
    whole_speeds: bool = False  # its params struct takes speeds as ints
    own: bool = False  # one of vexsim's own (bridge/cpp/motions), not LemLib's


_SPEEDS = ("max_speed", "min_speed", "early_exit")
MOTIONS: dict[str, Motion] = {
    "move_to_point": Motion("moveToPoint", ("x", "y"), ("forwards", *_SPEEDS)),
    "move_to_pose": Motion(
        "moveToPose", ("x", "y", "theta"), ("forwards", "horizontal_drift", "lead", *_SPEEDS)
    ),
    "turn_to_heading": Motion(
        "turnToHeading", ("theta",), ("direction", *_SPEEDS), whole_speeds=True
    ),
    "turn_to_point": Motion(
        "turnToPoint", ("x", "y"), ("forwards", "direction", *_SPEEDS), whole_speeds=True
    ),
    "swing_to_heading": Motion("swingToHeading", ("theta",), ("direction", *_SPEEDS), swing=True),
    "swing_to_point": Motion(
        "swingToPoint", ("x", "y"), ("forwards", "direction", *_SPEEDS), swing=True
    ),
    # vexsim's own, on a speed profile: an arc of a radius (in) through an angle (degrees,
    # clockwise positive), and RAMSETE along a smooth path through points ([[x, y], ...],
    # kept as x1, y1, x2, y2...)
    "move_arc": Motion(
        "moveArc", ("radius", "degrees"), ("forwards", "max_velocity", "max_accel"), own=True
    ),
    "ramsete": Motion(
        "ramsete", ("points",), ("forwards", "max_velocity", "max_accel", "end_heading"), own=True
    ),
}
PAUSES = ("wait", "wait_until", "wait_until_done")
INVALID = "invalid"  # a step that doesn't read (the editor's routes keep its place)
_FUNCTION = re.compile(r"(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*")  # a function's name, with namespaces
KINDS = (*MOTIONS, *PAUSES, "call")
TOP_KEYS = ("version", "name", "robot", "field", "start", "functions", "drive", "steps")
# A route's drive: section, the model of the drive vexsim's own motions drive with
# (calibration/feedforward.py): its keys, and the fields of vexsim::Drive they set. One left
# out is vexsim's, worked out from the robot's config.
DRIVE: dict[str, str] = {
    "kS": "kS", "kV": "kV", "kA": "kA", "kT": "kT", "kP": "kP", "max_velocity": "maxVelocity",
    "max_accel": "maxAccel", "max_lateral_accel": "maxLateralAccel",
}  # fmt: skip


@dataclass(frozen=True)
class Step:
    """One step: ``kind`` is a motion's name (``MOTIONS``), a pause's or ``call``."""

    kind: str
    target: tuple[float, ...] = ()  # a motion's x, y (theta) or theta; a wait's ms or distance
    timeout: int | None = None  # a motion's, ms
    side: str | None = None  # a swing's locked side: left or right
    options: tuple[tuple[str, Value], ...] = ()  # a motion's, as written (and async)
    function: str | None = None  # call: the function's name
    args: tuple[tuple[str, Value], ...] = ()  # call: by parameter name, as written

    def option(self, name: str, default: Value | None = None) -> Value | None:
        return dict(self.options).get(name, default)

    @property
    def motion(self) -> Motion | None:
        return MOTIONS.get(self.kind)

    @property
    def is_async(self) -> bool | None:
        """Whether a motion starts and goes on (LemLib's default); None for other steps."""
        return bool(self.option("async", True)) if self.kind in MOTIONS else None

    @property
    def points(self) -> list[tuple[float, float]]:
        """A ramsete step's points, each (x, y)."""
        return [(self.target[k], self.target[k + 1]) for k in range(0, len(self.target) - 1, 2)]


@dataclass
class Route:
    name: str
    start: tuple[float, float, float]  # LemLib's x, y (in) and theta (degrees, clockwise from +y)
    robot: str | None = None  # relative to the route's file
    field: str | None = None
    functions: tuple[str, ...] = ()  # headers, relative to the project
    steps: list[Step] = dataclasses.field(default_factory=list)
    version: int = VERSION
    drive: dict[str, float] = dataclasses.field(default_factory=dict)  # its drive: section

    @property
    def own_motions(self) -> bool:
        """Whether a step is one of vexsim's own motions, which need a drive model."""
        return any(step.motion is not None and step.motion.own for step in self.steps)

    def start_pose(self) -> tuple[float, float, float]:
        """The start as vexsim has poses: x, y (in) and heading (degrees, counter-clockwise
        from +x)."""
        return lemlib_to_vexsim(self.start)


def lemlib_to_vexsim(pose: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, theta = pose
    heading = (90.0 - theta) % 360.0
    return (x, y, heading - 360.0 if heading > 180.0 else heading)


def project_of(path: str | os.PathLike[str]) -> Path | None:
    """The PROS project a route's file is in (``<project>/routes/name.yaml``), if it is."""
    from vexsim.bridge.build import is_pros_project

    path = Path(path)
    if path.parent.name != FOLDER or not is_pros_project(path.parent.parent):
        return None
    return path.parent.parent


# --- reading -----------------------------------------------------------------------------------


class _Reader:
    """Reads a route's data, noting each problem where it is."""

    def __init__(self) -> None:
        self.issues: list[ConfigIssue] = []

    def error(self, location: str, message: str) -> None:
        self.issues.append(ConfigIssue("error", location, message))

    def number(self, value: Any, location: str, *, whole: bool = False) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            self.error(location, "must be a number" if not whole else "must be a whole number")
            return None
        if not math.isfinite(value):
            self.error(location, "must be a finite number")
            return None
        if whole and value != int(value):
            self.error(location, "must be a whole number")
            return None
        return value

    def numbers(self, value: Any, location: str, count: int, what: str) -> tuple[float, ...] | None:
        if not isinstance(value, list) or len(value) != count:
            self.error(location, f"must be {what}")
            return None
        read = [self.number(v, f"{location}[{k}]") for k, v in enumerate(value)]
        return None if any(v is None for v in read) else tuple(read)

    def word(
        self, value: Any, location: str, choices: Mapping[str, Any] | tuple[str, ...]
    ) -> str | None:
        if not isinstance(value, str) or value not in choices:
            self.error(location, "must be one of: " + ", ".join(choices))
            return None
        return value

    def boolean(self, value: Any, location: str) -> bool | None:
        if not isinstance(value, bool):
            self.error(location, "must be true or false")
            return None
        return value


def read_route(
    data: Any, default_name: str = "", *, partial: bool = False
) -> tuple[Route | None, list[ConfigIssue]]:
    """A route from its YAML data, and the problems with it (an error leaves it None).
    ``partial``: for the editor, a route even when some steps don't read, each of those an
    ``invalid`` step in its place (None only when its name, start or paths don't read)."""
    reader = _Reader()
    if not isinstance(data, Mapping):
        reader.error("", "the top level of the file must be a mapping of keys")
        return None, reader.issues
    for key in data:
        if key not in TOP_KEYS:
            reader.error(str(key), _unknown(key, TOP_KEYS))
    version = data.get("version", VERSION)
    if version != VERSION or isinstance(version, bool):
        reader.error("version", f"vexsim reads version {VERSION} routes")
    name = data.get("name", default_name)
    if not isinstance(name, str) or not name.strip():
        reader.error("name", "must be the route's name")
    paths = {}
    for key in ("robot", "field"):
        value = data.get(key)
        if value is not None and (not isinstance(value, str) or not value):
            reader.error(key, f"must be the {key} config's path, relative to this file")
        paths[key] = value if isinstance(value, str) and value else None
    if "robot" not in data:
        reader.error("robot", "required key is missing: the robot config the route runs with")
    start = None
    if "start" not in data:
        reader.error(
            "start", "required key is missing: [x, y, theta], as chassis.setPose takes them"
        )
    else:
        start = reader.numbers(data["start"], "start", 3, "[x, y, theta] (inches, degrees)")
    functions: list[str] = []
    headers = data.get("functions", [])
    if not isinstance(headers, list) or not all(isinstance(h, str) and h for h in headers):
        reader.error("functions", "must be a list of headers, relative to the project")
    else:
        functions = [h.replace("\\", "/") for h in headers]
    drive = _read_drive(reader, data.get("drive"))
    steps: list[Step] = []
    raw = data.get("steps", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        reader.error("steps", "must be a list of steps")
        raw = []
    for k, item in enumerate(raw):
        step = _read_step(reader, item, f"steps[{k}]")
        if step is not None:
            steps.append(step)
        elif partial:
            steps.append(Step(INVALID))
    errors = [i for i in reader.issues if i.severity == "error"]
    if partial:
        errors = [i for i in errors if not i.location.startswith("steps[")]
    if errors:
        return None, reader.issues
    route = Route(
        name=name.strip(), start=start, robot=paths["robot"], field=paths["field"],
        functions=tuple(functions), steps=steps, version=version, drive=drive,
    )  # fmt: skip
    return route, reader.issues


def _read_drive(reader: _Reader, value: Any) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        reader.error(
            "drive", "must map the drive model's numbers to their values: " + ", ".join(DRIVE)
        )
        return {}
    drive = {}
    for key, given in value.items():
        place = f"drive.{key}"
        if key not in DRIVE:
            reader.error(place, _unknown(key, tuple(DRIVE)))
            continue
        read = reader.number(given, place)
        if read is None:
            continue
        if key in ("kS", "kA", "kT") and read < 0:
            reader.error(place, "must be 0 or more")
        elif key not in ("kS", "kA", "kT") and read <= 0:
            reader.error(place, "must be more than 0")
        else:
            drive[key] = read
    return drive


def _unknown(key: Any, known: tuple[str, ...]) -> str:
    message = f"unknown key {key!r}"
    close = difflib.get_close_matches(str(key), known, n=1)
    return message + (f" (did you mean {close[0]!r}?)" if close else "")


def _read_step(reader: _Reader, item: Any, where: str) -> Step | None:
    if item == "wait_until_done":
        return Step("wait_until_done")
    if not isinstance(item, Mapping):
        reader.error(where, "must be a step: a mapping such as {wait: 100}")
        return None
    kinds = [k for k in item if k in KINDS]
    if len(kinds) != 1:
        message = (
            "has more than one of " + ", ".join(kinds)
            if kinds
            else "must say what it does: " + ", ".join(KINDS)
        )
        reader.error(where, message)
        return None
    kind = kinds[0]
    value = item[kind]
    at = f"{where}.{kind}"
    if kind in MOTIONS:
        return _read_motion(reader, item, where, kind)
    allowed = ("call", "args") if kind == "call" else (kind,)
    for key in item:
        if key not in allowed:
            reader.error(f"{where}.{key}", _unknown(key, allowed) + f" for a {kind} step")
    if kind == "wait":
        ms = reader.number(value, at, whole=True)
        if ms is not None and ms < 0:
            reader.error(at, "must be 0 or more (ms)")
        return Step(kind, (int(ms),)) if ms is not None and ms >= 0 else None
    if kind == "wait_until":
        distance = reader.number(value, at)
        return Step(kind, (distance,)) if distance is not None else None
    if kind == "wait_until_done":
        if value not in (True, None):
            reader.error(at, "must be true (or write the step as just wait_until_done)")
            return None
        return Step(kind)
    # call
    if not isinstance(value, str) or not _FUNCTION.fullmatch(value):
        reader.error(at, "must be the name of one of the team's functions")
        return None
    args = item.get("args") or {}
    if not isinstance(args, Mapping):
        reader.error(f"{where}.args", "must map the function's parameters to their values")
        return None
    good = True
    for name, arg in args.items():
        if isinstance(arg, bool | int | float | str) and not (
            isinstance(arg, float) and not math.isfinite(arg)
        ):
            continue
        reader.error(f"{where}.args.{name}", "must be a number, true or false, or an enum's value")
        good = False
    return (
        Step("call", function=value, args=tuple((str(k), v) for k, v in args.items()))
        if good
        else None
    )


def _read_motion(reader: _Reader, item: Mapping, where: str, kind: str) -> Step | None:
    motion = MOTIONS[kind]
    at = f"{where}.{kind}"
    before = len(reader.issues)
    allowed = (
        kind,
        "timeout",
        *motion.options,
        *(("locked_side",) if motion.swing else ()),
        "async",
    )
    for key in item:
        if key not in allowed:
            reader.error(f"{where}.{key}", _unknown(key, allowed) + f" for {kind}")
    if kind == "move_arc":
        target = reader.numbers(item[kind], at, 2, "[radius, degrees] (inches, degrees clockwise)")
        if target is not None and target[0] <= 0:
            reader.error(f"{at}[0]", "the radius must be more than 0 (inches)")
        if target is not None and target[1] == 0:
            reader.error(f"{at}[1]", "must turn some way: degrees, clockwise positive")
    elif kind == "ramsete":
        target = _points(reader, item[kind], at)
    elif len(motion.target) == 1:
        value = reader.number(item[kind], at)
        target = None if value is None else (value,)
    else:
        what = "[x, y]" if len(motion.target) == 2 else "[x, y, theta]"
        target = reader.numbers(item[kind], at, len(motion.target), what + " (inches, degrees)")
    timeout = None
    if "timeout" not in item:
        reader.error(f"{where}.timeout", "required key is missing: how long it may take (ms)")
    else:
        timeout = reader.number(item["timeout"], f"{where}.timeout", whole=True)
        if timeout is not None and timeout <= 0:
            reader.error(f"{where}.timeout", "must be more than 0 (ms)")
    side = None
    if motion.swing:
        if "locked_side" not in item:
            reader.error(f"{where}.locked_side", "required key is missing: left or right")
        else:
            side = reader.word(item["locked_side"], f"{where}.locked_side", SIDES)
    options: list[tuple[str, Value]] = []
    for name in (*motion.options, "async"):
        if name not in item:
            continue
        value, place = item[name], f"{where}.{name}"
        kind_of = "bool" if name == "async" else OPTIONS[name].kind
        if kind_of == "bool":
            read = reader.boolean(value, place)
        elif kind_of == "direction":
            read = reader.word(value, place, DIRECTIONS)
        else:
            read = reader.number(value, place, whole=kind_of == "speed" and motion.whole_speeds)
            if read is None or kind_of == "angle":
                pass
            elif kind_of == "positive" and read <= 0:
                reader.error(place, "must be more than 0")
            elif read < 0:
                reader.error(place, "must be 0 or more")
            elif kind_of == "speed" and read > 127:
                reader.error(place, "must be 127 or less (LemLib's full speed)")
        if read is not None:
            options.append((name, read))
    speeds = dict(options)
    if speeds.get("min_speed", 0) > speeds.get("max_speed", 127):
        reader.error(f"{where}.min_speed", "must be at most max_speed")
    if len(reader.issues) > before and any(i.severity == "error" for i in reader.issues[before:]):
        return None
    return Step(kind, target, int(timeout), side, tuple(options))


def _points(reader: _Reader, value: Any, at: str) -> tuple[float, ...] | None:
    """A path's points, [[x, y], ...], one after another: x1, y1, x2, y2..."""
    if not isinstance(value, list) or not value:
        reader.error(at, "must be the points it goes through: [[x, y], ...] (inches)")
        return None
    read = [
        reader.numbers(point, f"{at}[{k}]", 2, "a point: [x, y] (inches)")
        for k, point in enumerate(value)
    ]
    return None if any(p is None for p in read) else tuple(v for p in read for v in p)


# --- checking it against its project, robot and field -----------------------------------------


@dataclass
class CheckedRoute:
    route: Route | None
    issues: list[ConfigIssue]
    project: Path | None = None
    functions: Any = None  # bridge.functions.Functions, once the headers are read
    robot: Any = None  # RobotConfig
    field: Any = None  # FieldConfig, or None for the empty field
    drive: Any = None  # the DriveModel its own motions drive with (``route_drive``), if any

    @property
    def errors(self) -> list[ConfigIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def ok(self) -> bool:
        return self.route is not None and not self.errors


def check_route(route: Route, path: str | os.PathLike[str]) -> CheckedRoute:
    """``route`` (from the file ``path``) against its project, robot, field and functions."""
    from vexsim.bridge import lemlib
    from vexsim.bridge.build import BuildError, project_templates
    from vexsim.bridge.functions import find_functions
    from vexsim.bridge.runner import find_chassis

    path = Path(path)
    checked = CheckedRoute(route, [])
    issues = checked.issues

    def error(location: str, message: str) -> None:
        issues.append(ConfigIssue("error", location, message))

    def warning(location: str, message: str) -> None:
        issues.append(ConfigIssue("warning", location, message))

    project = project_of(path)
    if project is None:
        error("", f"a route is a file in a PROS project's {FOLDER}/ folder")
    else:
        try:
            version = lemlib.find_version(project, project_templates(project))
        except BuildError as exc:
            version, why = None, str(exc)
        else:
            why = f"a route runs LemLib's motions, and {project.name} doesn't use LemLib"
        if not version:
            error("", why)
            project = None
    checked.project = project
    _check_configs(checked, path, error)
    if project is not None:
        chassis = find_chassis(project)
        if isinstance(chassis, str):
            error("", chassis)
        inside = []
        for k, header in enumerate(route.functions):
            target = (project / header).resolve()
            if not target.is_relative_to(project.resolve()):
                error(f"functions[{k}]", f"{header} isn't in the project")
                continue
            if not target.is_file():
                error(f"functions[{k}]", f"the project has no {header}")
            inside.append(header)
        checked.functions = find_functions(project, inside)
    for k, step in enumerate(route.steps):
        where = f"steps[{k}]"
        if step.kind == INVALID:
            continue
        if step.kind == "call":
            _check_call(checked, step, where, error)
        elif step.kind == "ramsete":
            for k, point in enumerate(step.points):
                _check_on_field(checked, point, f"{where}.ramsete[{k}]", warning)
        elif (
            step.motion is not None
            and len(step.target) == 3
            or step.motion
            and step.kind.endswith("point")
        ):
            _check_on_field(checked, step.target[:2], f"{where}.{step.kind}", warning)
        if step.kind == "wait_until" and k and route.steps[k - 1].is_async is False:
            warning(
                f"{where}.wait_until",
                "the motion before it isn't async, so it has ended: wait_until goes on at once",
            )
    if checked.robot is not None:
        from vexsim.app.runspec import WALLS, start_blocked

        for where in start_blocked(checked.robot, checked.field, route.start_pose()):
            message = (
                "the robot starts partly outside the walls; move its start in"
                if where == WALLS
                else f"the robot starts on top of {where}; move its start"
            )
            warning("start", message)
        _check_drive(checked, error)
    return checked


def _check_drive(checked: CheckedRoute, error) -> None:
    """vexsim's own motions drive a differential drive's two sides, with ``route_drive``."""
    route = checked.route
    own = [k for k, step in enumerate(route.steps) if step.motion and step.motion.own]
    if not own:
        return
    kind = checked.robot.drivetrain.type
    if kind not in ("differential", "hdrive"):
        for k in own:
            step = route.steps[k]
            error(
                f"steps[{k}].{step.kind}",
                f"{step.kind} drives a differential drive's left and right sides, and this "
                f"robot's drivetrain is {kind}",
            )
        return
    checked.drive = route_drive(route, checked.robot)


def route_drive(route: Route, robot) -> Any:
    """The model of the drive ``route``'s own motions drive with (a ``DriveModel``): what its
    drive: section gives, and for the rest vexsim's, from the robot's config
    (calibration/feedforward.py)."""
    from vexsim.calibration.feedforward import characterize, model

    given = route.drive
    constants = ("kS", "kV", "kA", "kT")
    if all(k in given for k in constants):
        found = model(robot, *(given[k] for k in constants))
    else:
        found = characterize(robot)
        if any(k in given for k in constants):
            found = model(robot, *(given.get(k, getattr(found, k)) for k in constants))
    rest = ("kP", "max_velocity", "max_accel", "max_lateral_accel")
    return dataclasses.replace(found, **{k: given[k] for k in rest if k in given})


def _check_configs(checked: CheckedRoute, path: Path, error) -> None:
    from vexsim.config.loader import validate_field, validate_robot

    route = checked.route
    for key, validate in (("robot", validate_robot), ("field", validate_field)):
        written = getattr(route, key)
        if written is None:
            continue
        target = path.parent / written
        if not target.is_file():
            error(key, f"there's no {written} (the path is relative to this route's file)")
            continue
        report = validate(target)
        if not report.ok or report.config is None:
            first = report.errors[0] if report.errors else None
            why = f": {first}" if first else ""
            error(key, f"{written} isn't a valid {key} config{why}")
            continue
        setattr(checked, key, report.config)


def _check_call(checked: CheckedRoute, step: Step, where: str, error) -> None:
    functions = checked.functions
    if functions is None:
        return
    at = f"{where}.call"
    fn = functions.named(step.function)
    if fn is None:
        why = functions.why_not(step.function)
        if why:
            error(at, f"{step.function}() {why}, so a route can't call it")
            return
        names = [f.name for f in functions.functions]
        close = difflib.get_close_matches(step.function, names, n=1)
        hint = f" (did you mean {close[0]}?)" if close else ""
        listed = ", ".join(checked.route.functions) or "none: list them under functions"
        error(at, f"the route's headers don't declare {step.function}(){hint} (headers: {listed})")
        return
    given = dict(step.args)
    for name, value in given.items():
        param = fn.param(name)
        if param is None:
            names = ", ".join(p.name for p in fn.params) or "none"
            error(
                f"{where}.args.{name}",
                f"{fn.name}() has no parameter {name} (its parameters: {names})",
            )
            continue
        why = _wrong_argument(param, value, functions)
        if why:
            error(f"{where}.args.{name}", why)
    missing = [p.name for p in fn.params[: fn.required] if p.name not in given]
    if missing:
        place = f"{where}.args" if step.args else at
        error(place, f"{fn.name}() needs {', '.join(missing)}")
        return
    last = max((k for k, p in enumerate(fn.params) if p.name in given), default=-1)
    for param in fn.params[:last]:
        if param.name in given or param.default is None:
            continue
        values = functions.enums[param.enum].values if param.enum else ()
        if param.literal(values) is None:
            error(
                f"{where}.args",
                f"give {param.name} too: its default ({param.default}) isn't a value vexsim can "
                "pass on, and a later argument is given",
            )


def _wrong_argument(param, value: Value, functions) -> str | None:
    """Why ``value`` can't be passed as ``param``, if it can't."""
    if param.kind == "bool":
        return None if isinstance(value, bool) else f"{param.name} is a bool: true or false"
    if param.kind in ("integer", "number"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            return f"{param.name} is a number ({param.type})"
        if param.kind == "integer" and value != int(value):
            return f"{param.name} is a whole number ({param.type})"
        return None
    values = functions.enums[param.enum].values
    if not isinstance(value, str) or value.split("::")[-1] not in values:
        return f"{param.name} is a {param.enum}: one of {', '.join(values)}"
    return None


def _check_on_field(checked: CheckedRoute, point, where: str, warning) -> None:
    from vexsim.config.field import FieldConfig

    field_config = checked.field or FieldConfig()
    half_x, half_y = (v / 2 for v in field_config.size_in)
    x, y = point
    if abs(x) > half_x or abs(y) > half_y:
        warning(where, f"({x:g}, {y:g}) is off the field")


# --- the text, as the browser's editor checks it ----------------------------------------------


def check_text(text: str, path: str | os.PathLike[str]) -> tuple[CheckedRoute, list]:
    """A route's text read and checked, and its issues at their places in the text
    (``configs.LocatedIssue``)."""
    import yaml

    from vexsim.app.configs import LocatedIssue, Span, _compose, locate
    from vexsim.config.yaml_io import parse_yaml

    path = Path(path)
    try:
        root, _ = _compose(text)
        data = parse_yaml(text)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        span = (
            None
            if mark is None
            else Span(mark.line + 1, mark.column + 1, mark.line + 1, mark.column + 2)
        )
        problem = exc.problem or exc.context or "invalid YAML"
        return CheckedRoute(None, [ConfigIssue("error", "", problem)]), [
            LocatedIssue("error", "", problem, span)
        ]
    except yaml.YAMLError as exc:
        issue = ConfigIssue("error", "", f"invalid YAML: {exc}")
        return CheckedRoute(None, [issue]), [LocatedIssue("error", "", issue.message, None)]
    route, issues = read_route(data, path.stem, partial=True)
    checked = check_route(route, path) if route is not None else CheckedRoute(None, [])
    checked.issues[:0] = issues
    located = [
        LocatedIssue(i.severity, i.location, i.message, locate(root, i.location, text))
        for i in checked.issues
    ]
    return checked, located


def load_route(path: str | os.PathLike[str], text: str | None = None) -> CheckedRoute:
    """A route's file read and checked (a missing or unreadable file is an error); with
    ``text``, that text as the file at ``path`` (the editor's, not saved yet)."""
    import yaml

    from vexsim.config.issues import ConfigError
    from vexsim.config.yaml_io import load_yaml_file, parse_yaml

    path = Path(path)
    try:
        data = load_yaml_file(path) if text is None else parse_yaml(text)
    except ConfigError as exc:
        return CheckedRoute(None, exc.issues)
    except yaml.YAMLError as exc:
        return CheckedRoute(None, [ConfigIssue("error", "", f"invalid YAML: {exc}")])
    route, issues = read_route(data, path.stem)
    if route is None:
        return CheckedRoute(None, issues)
    checked = check_route(route, path)
    checked.issues[:0] = issues
    return checked


# --- what the runner reads ----------------------------------------------------------------------


def call_arguments(step: Step, functions) -> list[Value]:
    """A call's arguments in order, up to the last one given; one left out before it takes its
    default (``check_route`` says when that can't be done)."""
    fn = functions.named(step.function)
    given = dict(step.args)
    last = max((k for k, p in enumerate(fn.params) if p.name in given), default=-1)
    values: list[Value] = []
    for param in fn.params[: last + 1]:
        if param.name in given:
            value = given[param.name]
            values.append(value.split("::")[-1] if param.kind == "enum" else value)
        else:
            enum = functions.enums[param.enum].values if param.enum else ()
            values.append(param.literal(enum))
    return values


def runner_input(route: Route, functions, drive=None) -> str:
    """The route as vexsim's route runner reads it (bridge/runner.py): a line for its start,
    one for the ``drive`` model its own motions drive with (``route_drive``), then one for
    each step, numbered from 1."""
    if any(step.kind == INVALID for step in route.steps):
        raise ValueError("a route with steps that don't read can't run")
    lines = [f"vexsim-route {VERSION}", "start " + " ".join(_text(v) for v in route.start)]
    if route.own_motions:
        if drive is None:
            raise ValueError("a route's arcs and RAMSETE paths need the drive model to run")
        lines.append("drive " + " ".join(_text(getattr(drive, k)) for k in DRIVE))
    for number, step in enumerate(route.steps, 1):
        words = [str(number), step.kind]
        if step.kind == "call":
            words += [step.function, *(_text(v) for v in call_arguments(step, functions))]
        elif step.kind in MOTIONS:
            words += [_text(v) for v in step.target]
            if step.side is not None:
                words.append(step.side)
            words.append(str(step.timeout))
            words += [f"{name}={_text(value)}" for name, value in step.options]
        else:
            words += [_text(v) for v in step.target]
        lines.append(" ".join(words))
    return "\n".join(lines) + "\n"


def _text(value: Value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return f"{value:.10g}"
    return str(value)


# --- running it -----------------------------------------------------------------------------------


def label(step: Step) -> str:
    """A step in a few words: ``move_to_point (14, 0) max_speed 60``, ``wait 100 ms``."""
    if step.kind == INVALID:
        return "a step that doesn't read"
    if step.kind == "call":
        args = ", ".join(f"{name}={_text(value)}" for name, value in step.args)
        return f"{step.function}({args})"
    if step.kind == "wait":
        return f"wait {_text(step.target[0])} ms"
    if step.kind == "wait_until":
        return f"wait_until {_text(step.target[0])}"
    if step.kind == "wait_until_done":
        return "wait_until_done"
    if step.kind == "move_arc":
        words = [f"move_arc {_text(step.target[1])}°, radius {_text(step.target[0])} in"]
    elif step.kind == "ramsete":
        words = ["ramsete", " ".join(f"({_text(x)}, {_text(y)})" for x, y in step.points)]
    else:
        target = ", ".join(_text(v) for v in step.target)
        words = [step.kind, f"({target})" if len(step.target) > 1 else target]
    if step.side:
        words.append(f"{step.side} side")
    words += [f"{name} {_text(value)}" for name, value in step.options if name != "async"]
    if step.is_async is False:
        words.append("not async")
    return " ".join(words)


def run_route(
    path: str | os.PathLike[str],
    root: str | os.PathLike[str] | None = None,
    *,
    seed: int = 0,
    noise: str | None = None,
    log=None,
    max_seconds: float = 120.0,
    text: str | None = None,
) -> dict:
    """Run a route headless until each step it started has ended (or the autonomous period
    is over), and say where each step ended: where the robot really was, and where LemLib
    thought it was (LemLib's convention), when (seconds into the autonomous period), and
    whether a motion used up its timeout; and the path the robot drove. ``path`` is relative
    to ``root``; ``text``: the route as the editor has it, not saved yet."""
    from vexsim.app.runspec import (
        RunSpec,
        build,
        check,
        program_factory,
        route_defaults,
        simulation_factory,
    )
    from vexsim.bridge.host import HostError
    from vexsim.runtime.simulation import MODES

    given = route_defaults(str(path), root, text)
    spec = RunSpec(
        robot=given.get("robot") or "", program=given.get("program"), route=str(path),
        field=given.get("field"), start=given.get("start", (0.0, 0.0, 0.0)), seed=seed,
        noise=noise,
    )  # fmt: skip
    prepared = check(spec, root, route_text=text)
    executable = build(prepared, log=log)
    make_program, mode = program_factory(prepared, executable)
    sim = simulation_factory(prepared, make_program, mode, echo=None)()
    program = sim.program
    record = program.route_record
    driven: list[list[float]] = []

    def sample(world) -> None:  # where the robot is, from the autonomous period's start
        if program.autonomous_us is None:
            return
        x, y, heading = (*_inches(sim.robot.pose[:2]), math.degrees(sim.robot.pose[2]))
        time_s = (world.clock.us - program.autonomous_us) / 1e6
        driven.append([round(time_s, 3), round(x, 2), round(y, 2), round((90 - heading) % 360, 1)])

    sim.world.every(PATH_MS, sample, name="route path")
    try:  # autonomous() may return while the last motion goes on: wait for it
        sim.world.run_until(lambda w: record.done, timeout_s=max_seconds)
    except HostError as exc:  # where the steps before it ended still counts
        record.error = record.error or f"the robot code stopped: {exc}"
    finally:
        sim.close()
    period = dict(MODES[mode]).get("autonomous") or AUTONOMOUS_S
    return {**endpoints(prepared.route.route, record, period), "path": driven}


def _inches(xy) -> tuple[float, float]:
    from vexsim.units import m_to_in

    return m_to_in(xy[0]), m_to_in(xy[1])


def endpoints(route: Route, record, period_s: float | None = None) -> dict:
    """Where each step of ``route`` ended, from its run's ``RouteRecord``."""

    def seconds(value: float | None) -> float | None:
        return None if value is None else round(value, 3)  # the simulation's ticks are 1 ms

    def pose(value) -> list[float] | None:  # LemLib's theta isn't kept in [0, 360)
        return (
            None
            if value is None
            else [round(value[0], 3), round(value[1], 3), round(value[2] % 360, 3)]
        )

    steps = []
    for number, step in enumerate(route.steps, 1):
        seen = record.steps.get(number)
        started = None if seen is None or seen.started is None else seen.started.time_s
        end = record.step_end(number)
        timed_out = None
        if step.kind in MOTIONS:
            moving = record.motion_time(number)
            timed_out = None if moving is None else round(moving * 1000) >= step.timeout
        steps.append(
            {
                "number": number,
                "kind": step.kind,
                "label": label(step),
                "started_s": seconds(started),
                "ended_s": seconds(None if end is None else end.time_s),
                "duration_s": seconds(
                    None if end is None or started is None else end.time_s - started
                ),
                "pose": pose(None if end is None else end.pose),
                "lemlib": pose(None if end is None else end.lemlib),
                "timed_out": timed_out,
            }
        )
    ended = [s["ended_s"] for s in steps if s["ended_s"] is not None]
    return {
        "name": route.name,
        "error": record.error,
        "started": record.started is not None,
        "finished": record.ended is not None and len(ended) == len(steps),
        "ended_s": max(ended) if ended else None,
        "period_s": period_s,
        "steps": steps,
    }


def route_job(params: dict, report) -> dict:
    """A ``route`` job: ``run_route`` on ``params["route"]`` (relative to ``params["root"]``),
    or on ``params["text"]`` as that file, when the editor's text isn't saved."""
    return run_route(
        params["route"], params.get("root"), seed=params.get("seed", 0),
        noise=params.get("noise"), log=report, text=params.get("text"),
    )  # fmt: skip


# --- for the editor ------------------------------------------------------------------------------


def project_headers(project: str | os.PathLike[str]) -> list[str]:
    """The project's own headers, relative to it, for a route's ``functions``: those under
    include/ that aren't a template's (PROS, LemLib...)."""
    from vexsim.bridge.functions import TEMPLATE_DIRS

    include = Path(project) / "include"
    found = []
    for path in sorted(include.rglob("*")) if include.is_dir() else []:
        rel = path.relative_to(include)
        if path.suffix in (".h", ".hpp", ".hh", ".hxx") and rel.parts[0] not in TEMPLATE_DIRS:
            found.append(f"include/{rel.as_posix()}")
    return [h for h in found if h != "include/main.h" and h != "include/api.h"]


def new_route_text(
    name: str,
    robot: str | None,
    field: str | None,
    start: tuple[float, float, float],
) -> str:
    """A new route's YAML: no steps yet. ``robot`` and ``field`` are relative to the route's
    file; ``start`` is LemLib's x, y, theta."""
    words = [_text(round(v, 2)) for v in start]
    lines = [
        "# An autonomous route, for vexsim (its README: Autonomous routes). Numbers are",
        "# LemLib's: inches, and theta in degrees clockwise from +y.",
        f"version: {VERSION}",
        f"name: {json_word(name)}",
    ]
    if robot:
        lines.append(f"robot: {json_word(robot)}   # relative to this file")
    if field:
        lines.append(f"field: {json_word(field)}")
    lines += [
        f"start: [{', '.join(words)}]   # chassis.setPose(x, y, theta)",
        "functions: []   # headers whose functions steps can call",
        "steps: []",
    ]
    return "\n".join(lines) + "\n"


def json_word(text: str) -> str:
    """A word as YAML reads it back: plain when it can be, else quoted."""
    from vexsim.app.yamledit import _word

    return _word(text)


def route_file_name(name: str) -> str:
    """A route's file name from its name: ``Left 40`` is ``left_40.yaml``."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return (slug or "route") + ".yaml"


# --- mirroring ------------------------------------------------------------------------------------


def mirror_changes(route: Route, functions, axis: str) -> tuple[list, list[str]]:
    """The changes that make ``route`` the one for the other side of the field: mirrored
    across its middle line x = 0 (``axis`` "x": x becomes -x) or y = 0 ("y"). Turns go the
    other way and swings lock the other side; the team's functions are mirrored as their
    ``// vexsim:`` comments say. Also, what it can't mirror."""
    from vexsim.app.yamledit import Change

    if axis not in ("x", "y"):
        raise ValueError("mirror across x = 0 (axis x) or y = 0 (axis y)")

    def point(x: float, y: float) -> list[float]:
        return [-x, y] if axis == "x" else [x, -y]

    def heading(theta: float) -> float:
        mirrored = (-theta if axis == "x" else 180.0 - theta) % 360.0
        return 0.0 if abs(mirrored - 360.0) < 1e-9 else mirrored

    def tidy(values: list[float]) -> list[float]:
        return [round(v, 6) + 0.0 for v in values]

    x, y, theta = route.start
    changes = [Change("set", "start", tidy([*point(x, y), heading(theta)]))]
    notes: list[str] = []
    for k, step in enumerate(route.steps):
        where = f"steps[{k}]"
        if step.kind == "move_arc":  # the other way round
            changes.append(
                Change("set", f"{where}.move_arc", tidy([step.target[0], -step.target[1]]))
            )
        elif step.kind == "ramsete":
            points = [tidy(point(x, y)) for x, y in step.points]
            changes.append(Change("set", f"{where}.ramsete", points))
            end = step.option("end_heading")
            if end is not None:
                changes.append(Change("set", f"{where}.end_heading", tidy([heading(end)])[0]))
        elif step.motion is not None:
            target = step.target
            if len(target) == 1:
                value = tidy([heading(target[0])])[0]
            elif len(target) == 2:
                value = tidy(point(*target))
            else:
                value = tidy([*point(target[0], target[1]), heading(target[2])])
            changes.append(Change("set", f"{where}.{step.kind}", value))
            direction = step.option("direction")
            if direction in ("cw", "ccw"):
                changes.append(
                    Change("set", f"{where}.direction", "ccw" if direction == "cw" else "cw")
                )
            if step.side is not None:
                other = "right" if step.side == "left" else "left"
                changes.append(Change("set", f"{where}.locked_side", other))
        elif step.kind == "call" and functions is not None:
            changes += _mirror_call(step, where, functions, axis, notes, point, heading)
    return changes, notes


def _mirror_call(step: Step, where: str, functions, axis: str, notes: list[str], point, heading):
    from vexsim.app.yamledit import Change

    fn = functions.named(step.function)
    hint = fn.hint if fn is not None else None
    number = int(where.removeprefix("steps[").rstrip("]")) + 1
    if hint is None:
        notes.append(
            f"step {number}: {step.function}() is as it was: nothing says how it moves the "
            "robot (a // vexsim: comment above it would)"
        )
        return []
    given = dict(step.args)

    def value(arg) -> float | None:
        if not isinstance(arg, str):
            return None
        if arg in given:
            return given[arg]
        param = fn.param(arg)
        literal = param.literal() if param is not None else None
        return (
            literal if isinstance(literal, int | float) and not isinstance(literal, bool) else None
        )

    changes = []

    def put(arg, mirrored: float) -> None:
        changes.append(Change("set", f"{where}.args.{arg}", round(mirrored, 6) + 0.0))

    angles = {"turn_by": [0], "arc": [1], "pose": [2]}.get(hint.motion, [])
    for index in angles:
        arg = hint.args[index]
        current = value(arg)
        if current is None:
            notes.append(
                f"step {number}: {step.function}() turns by a fixed angle, so its mirror image "
                "is another function: change that step by hand"
            )  # (its own step stays as it was)
            return []
        put(arg, -current if hint.motion != "pose" else heading(current))
    if hint.motion in ("point", "pose"):
        xs, ys = hint.args[0], hint.args[1]
        px, py = value(xs), value(ys)
        if px is None or py is None:
            notes.append(
                f"step {number}: {step.function}()'s point is fixed, so it can't be mirrored: "
                "change that step by hand"
            )
            return []
        mx, my = point(px, py)
        if mx != px:
            put(xs, mx)
        if my != py:
            put(ys, my)
    return changes


def mirror_text(text: str, path: str | os.PathLike[str], axis: str) -> tuple[str, list[str]]:
    """A route's text mirrored (``mirror_changes``), named as the mirror image, and what
    couldn't be mirrored."""
    from vexsim.app.yamledit import Change, apply

    checked = load_route(path, text)
    if checked.route is None:
        raise ValueError("the route doesn't read: fix it before mirroring it")
    changes, notes = mirror_changes(checked.route, checked.functions, axis)
    changes.append(Change("set", "name", f"{checked.route.name} (mirrored)"))
    return apply(text, changes), notes

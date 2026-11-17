"""Autonomous routes in the maker: the team's functions, a route's text checked and patched, new
routes, mirroring, export; and a project's routines."""

from __future__ import annotations

from typing import Any, Literal

from vexsim.ui.protocol.base import _Message
from vexsim.ui.protocol.configs import PlacedIssue, TextSpan
from vexsim.ui.protocol.workspace import Preview


class RouteStepEnd(_Message):
    """Where a step of a route ended in a run (LemLib's convention: x, y in inches, theta in
    degrees clockwise from +y); times are seconds into the autonomous period."""

    number: int  # from 1
    kind: str
    label: str
    started_s: float | None
    ended_s: float | None  # None: it didn't end before the run did
    duration_s: float | None
    pose: tuple[float, float, float] | None  # where the robot really was
    lemlib: tuple[float, float, float] | None  # where LemLib's odometry put it
    timed_out: bool | None  # a motion that used up its timeout; None: not a motion


class RouteRun(_Message):
    """A route run headless: where each step ended."""

    name: str
    error: str | None  # why the route couldn't run, or stopped
    started: bool
    finished: bool  # every step ended
    ended_s: float | None  # when the last step ended
    period_s: float  # the autonomous period it's measured against
    steps: list[RouteStepEnd]
    path: list[tuple[float, float, float, float]] = []  # where it drove: time, x, y, theta


class RoutineInfo(_Message):
    """A PROS project's routine (``vexsim.bridge.routines``): a function its
    include/custom/auton.hpp declares that takes no arguments."""

    name: str  # as C++ calls it: left40, or auton::left40
    line: int  # its declaration's, in the header
    source: str | None  # the file that defines it; None: vexsim can't tell, so it can't be picked
    start: tuple[float, float, float] | None  # where its setPose puts the robot: x, y, heading


class NotRoutineInfo(_Message):
    name: str
    line: int
    why: str  # it takes arguments, returns a value, ...


class RouteInfo(_Message):
    """A route in a PROS project's routes/ folder (``vexsim.app.routes``), to run it."""

    path: str  # its file, in the workspace
    name: str
    robot: str | None  # workspace paths of the configs it names
    field: str | None
    start: tuple[float, float, float] | None  # where it starts: x, y, heading
    problem: str | None  # why it can't run as it is


class ProjectRoutines(_Message):
    """A PROS project's routines, to pick one for a run, and its routes."""

    header: str  # where they're declared, in the project
    found: bool  # whether the project has that header
    routines: list[RoutineInfo]
    others: list[NotRoutineInfo]  # functions the header declares that can't be routines
    routes: list[RouteInfo] = []


class RouteParamInfo(_Message):
    name: str
    type: str  # as C++ has it
    kind: Literal["integer", "number", "bool", "enum"]
    default: str | None  # as written
    value: float | bool | str | None  # the default as a value a route can pass, if it's plain
    values: list[str] = []  # an enum's values


class MotionHintInfo(_Message):
    """How a function moves the robot, as the ``// vexsim:`` comment above it says."""

    motion: Literal["drive", "turn_by", "arc", "point", "pose", "none"]
    args: list[str | float]  # each a parameter's name, or a number


class RouteFunctionInfo(_Message):
    """One of the team's functions a route can call (``vexsim.bridge.functions``)."""

    name: str
    header: str
    line: int
    declaration: str
    params: list[RouteParamInfo]
    required: int  # how many arguments a call needs
    hint: MotionHintInfo | None
    hint_problem: str | None  # why its vexsim: comment doesn't read


class NotRouteFunctionInfo(_Message):
    name: str
    header: str
    line: int
    why: str


class RouteStepData(_Message):
    """A step as the route's file has it: `kind` is a motion's (move_to_point...), a pause's,
    `call`, or `invalid` (it doesn't read)."""

    kind: str
    target: list[float]  # a motion's x, y (and theta), or theta; a wait's ms or distance
    timeout: int | None
    side: Literal["left", "right"] | None
    options: dict[str, float | bool | str]
    function: str | None
    args: dict[str, float | bool | str]
    label: str


class RouteData(_Message):
    """A route (``vexsim.app.routes.Route``), its numbers in LemLib's convention."""

    name: str
    start: tuple[float, float, float]
    robot: str | None  # as written, relative to its file
    field: str | None
    functions: list[str]
    steps: list[RouteStepData]
    drive: dict[str, float] = {}  # its drive: section, as written


class RouteDriveInfo(_Message):
    """The model of the drive a route's arcs and RAMSETE paths drive with, and the limits
    they're planned within (``vexsim.calibration.feedforward.DriveModel``): what the route's
    drive: section gives, and vexsim's for the rest, from its robot's config."""

    kS: float  # V
    kV: float  # V per in/s
    kA: float  # V per in/s^2
    kT: float  # V, against the scrub in a turn
    kP: float  # V per in/s the wheels are behind
    max_velocity: float  # in/s
    max_accel: float  # in/s^2
    max_lateral_accel: float  # in/s^2
    top_speed: float  # in/s, at 12 V


class RouteCheck(_Message):
    """A route's text, checked: its issues where they're written, and when it reads, the
    route, the functions its headers declare, its robot and field to draw, and where each
    step is written (`steps[3]`)."""

    issues: list[PlacedIssue]
    route: RouteData | None
    functions: list[RouteFunctionInfo]
    # the functions of the project's other headers: adding one as a step lists its header too
    more_functions: list[RouteFunctionInfo] = []
    others: list[NotRouteFunctionInfo]
    headers: list[str]  # the project's own headers, any of which `functions` can list
    preview: Preview | None
    track: float | None  # the drive's track width (in): a swing turns about one side
    drive: RouteDriveInfo | None = None  # what its arcs and RAMSETE paths drive with (or would)
    places: dict[str, TextSpan]
    project: str | None  # workspace paths: its project, robot and field
    robot_path: str | None
    field_path: str | None


class RouteFile(_Message):
    """A route, opened for editing. `version` is of the bytes on disk."""

    path: str
    text: str
    version: str
    check: RouteCheck


class RouteCheckRequest(_Message):
    path: str  # the route's file in the workspace, which its paths are relative to
    text: str


class RouteEdit(_Message):
    """A change to a route's text: `set` a value at `location`, `add` one to the end of the
    list there, `remove` the item or key there, `insert` one as the list item at `location`
    (`steps[2]`), or `move` the item there to the index `value` (``vexsim.app.yamledit``)."""

    op: Literal["set", "add", "remove", "rename", "insert", "move"]
    location: str
    value: Any = None


class RoutePatchRequest(_Message):
    path: str
    text: str
    edits: list[RouteEdit]


class RoutePatched(_Message):
    """The text with the edits made in place (nothing else in it changed), checked."""

    text: str
    check: RouteCheck


class NewRouteRequest(_Message):
    """A new route in a PROS project's routes/ folder (never over a file), with the robot and
    field given (workspace paths) and its start where the run bar has it (x, y, heading)."""

    project: str
    name: str
    robot: str | None = None
    field: str | None = None
    start: tuple[float, float, float] = (0.0, 0.0, 0.0)


class NewRoute(_Message):
    path: str


class MirrorRouteRequest(_Message):
    """A mirrored copy of a route: across x = 0 (`x`: x becomes -x) or y = 0 (`y`)."""

    path: str
    text: str
    axis: Literal["x", "y"]


class MirroredRoute(_Message):
    path: str  # the copy
    notes: list[str]  # what it couldn't mirror


class RoutesExportRequest(_Message):
    """Write a PROS project's routes into it as routines (``POST /api/routes/export``)."""

    project: str


class ExportedRoutine(_Message):
    """A route as a routine: ``name()``, from ``route`` (relative to the project), starting at
    LemLib's x, y, theta."""

    name: str
    route: str
    start: tuple[float, float, float]


class ExportedFile(_Message):
    """A file an export writes (relative to the project), and its change as a unified diff."""

    path: str
    state: Literal["new", "changed", "unchanged"]
    diff: str


class RoutesExport(_Message):
    """A project's routes as routines (`vexsim.app.autons`): what an export would write
    (``GET``), or wrote (``POST``); the routes it leaves out, and why."""

    project: str
    routines: list[ExportedRoutine]
    files: list[ExportedFile]
    left_out: list[str]
    notes: list[str]

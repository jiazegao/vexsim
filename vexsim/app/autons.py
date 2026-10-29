"""A PROS project's routes exported into its own code (PLAN.md 13.3): each route as a C++
routine in ``src/vexsim_autons.cpp``, a file vexsim writes whole, declared in
``include/custom/auton.hpp`` between two marker comments, so vexsim's routine list (12.1)
and the team's own selector can call them. Each step is written as the route runner makes
its call (bridge/runner.py), so the routine drives as the route did; exporting the same
routes again changes nothing. A route with vexsim's own motions (arcs, RAMSETE paths) brings
their library along (``LIBRARY``), the same files the simulation ran, unless the project has
its own copies."""

from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from vexsim.app.routes import (
    DIRECTIONS,
    DRIVE,
    FOLDER,
    MOTIONS,
    OPTIONS,
    SIDES,
    Route,
    Step,
    Value,
    call_arguments,
    load_route,
    project_headers,
)
from vexsim.bridge.routines import AUTON_HEADER

GENERATED = "src/vexsim_autons.cpp"
BEGIN = "// vexsim routes: begin"
END = "// vexsim routes: end"
INDENT = "    "
OWN_MOTIONS = "motions"  # the vexsim::Motions a routine with vexsim's own motions makes
# vexsim's motion library (bridge/cpp/motions), where an export puts it in the project
LIBRARY = ("include/vexsim/motions.hpp", "include/vexsim/trajectory.hpp", "src/vexsim/motions.cpp")

# Words a routine can't be named (C++'s keywords, and the names PROS gives its own functions)
_RESERVED = set(
    """alignas alignof and and_eq asm auto bitand bitor bool break case catch char char8_t char16_t
    char32_t class compl concept const consteval constexpr constinit const_cast continue co_await
    co_return co_yield decltype default delete do double dynamic_cast else enum explicit export
    extern false float for friend goto if inline int long mutable namespace new noexcept not
    not_eq nullptr operator or or_eq private protected public register reinterpret_cast requires
    return short signed sizeof static static_assert static_cast struct switch template this
    thread_local throw true try typedef typeid typename union unsigned using virtual void
    volatile wchar_t while xor xor_eq main initialize disabled competition_initialize
    autonomous opcontrol""".split()
)


@dataclass(frozen=True)
class Routine:
    """A route as a routine: ``name()``, from ``route`` (relative to the project)."""

    name: str
    route: str
    start: tuple[float, float, float]  # LemLib's x, y, theta: its setPose


@dataclass(frozen=True)
class FileChange:
    """A file an export writes: ``before`` is None if it's new."""

    path: str  # relative to the project, with /
    before: str | None
    after: str

    @property
    def state(self) -> str:
        if self.before is None:
            return "new"
        return "unchanged" if self.before == self.after else "changed"

    def diff(self) -> str:
        """What changes, as a unified diff (the whole file, for a new one)."""
        if self.state == "unchanged":
            return ""
        before = [] if self.before is None else self.before.splitlines(keepends=True)
        lines = difflib.unified_diff(
            before, self.after.splitlines(keepends=True), f"a/{self.path}", f"b/{self.path}"
        )
        return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


@dataclass
class Export:
    """What exporting a project's routes writes, or wrote."""

    project: Path
    routines: list[Routine] = field(default_factory=list)
    files: list[FileChange] = field(default_factory=list)
    left_out: list[str] = field(default_factory=list)  # routes it can't export, and why
    notes: list[str] = field(default_factory=list)

    @property
    def changes(self) -> bool:
        return any(f.state != "unchanged" for f in self.files)


class ExportError(ValueError):
    """Why a project's routes can't be exported at all."""


def routine_name(route_name: str) -> str:
    """The C++ name a route's routine gets from the route's name: ``Left 40`` is
    ``left_40``."""
    name = re.sub(r"[^a-z0-9]+", "_", route_name.lower()).strip("_") or "route"
    if name[0].isdigit():
        name = "route_" + name
    return name + "_route" if name in _RESERVED else name


def plan_export(project: str | os.PathLike[str]) -> Export:
    """What exporting ``project``'s routes would write, without writing it."""
    from vexsim.bridge.build import is_pros_project
    from vexsim.bridge.runner import find_chassis

    project = Path(project)
    if not is_pros_project(project):
        raise ExportError(f"{project} isn't a PROS project")
    files = sorted((project / FOLDER).glob("*.yaml")) if (project / FOLDER).is_dir() else []
    if not files:
        raise ExportError(f"{project.name} has no routes to export (in its {FOLDER}/ folder)")
    chassis = find_chassis(project)
    if isinstance(chassis, str):
        raise ExportError(chassis)
    plan = Export(project)
    header = project / AUTON_HEADER
    before = header.read_text(encoding="utf-8") if header.is_file() else None
    theirs = _names_taken(project, before)
    exported: list[tuple[Routine, Route, object, object]] = []
    for path in files:
        rel = path.relative_to(project).as_posix()
        checked = load_route(path)
        if not checked.ok:
            errors = checked.errors
            first = errors[0] if errors else None
            where = f"{first.location}: " if first and first.location else ""
            why = f"{where}{first.message}" if first else "it doesn't read"
            more = len(errors) - 1
            if more > 0:
                why += f" (and {more} more error{'s' if more > 1 else ''})"
            plan.left_out.append(f"{rel}: {why}")
            continue
        name = routine_name(checked.route.name)
        twin = next((r for r in plan.routines if r.name == name), None)
        if twin is not None:
            plan.left_out.append(
                f"{rel}: its routine would be {name}(), as {twin.route}'s is: rename one of them"
            )
            continue
        if name in theirs:
            plan.left_out.append(
                f"{rel}: the project has a {name}() of its own: rename the route "
                f"({checked.route.name})"
            )
            continue
        routine = Routine(name, rel, checked.route.start)
        plan.routines.append(routine)
        exported.append((routine, checked.route, checked.functions, checked.drive))
    if not exported:
        raise ExportError("no route can be exported: " + "; ".join(plan.left_out))
    source = project / GENERATED
    plan.files.append(
        FileChange(
            GENERATED,
            source.read_text(encoding="utf-8") if source.is_file() else None,
            generated_source(project, exported, chassis),
        )
    )
    plan.files.append(FileChange(AUTON_HEADER, before, declarations(before, plan.routines)))
    if any(route.own_motions for _, route, _, _ in exported):
        _library(plan)
    if before is None:
        plan.notes.append(
            f"{AUTON_HEADER} is new: call the routines from autonomous() (or the team's "
            "selector) for the robot to run them; vexsim's routine list runs one in place of "
            "the first routine autonomous() calls"
        )
    return plan


def export(project: str | os.PathLike[str]) -> Export:
    """Write ``project``'s routes into it (``plan_export``): only the files that change."""
    plan = plan_export(project)
    for change in plan.files:
        if change.state == "unchanged":
            continue
        path = plan.project / change.path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as out:
            out.write(change.after)
    return plan


# --- the generated file ---------------------------------------------------------------------------


def _library(plan: Export) -> None:
    """vexsim's motion library, copied into the project: a file it has already is left as it
    is (and said so, when it differs from vexsim's)."""
    from vexsim.bridge.build import CPP_DIR

    for rel in LIBRARY:
        where = "include" if rel.startswith("include/") else "src"
        ours = (CPP_DIR / "motions" / where / rel.removeprefix(f"{where}/")).read_text("utf-8")
        path = plan.project / rel
        theirs = path.read_text(encoding="utf-8") if path.is_file() else None
        if theirs is None or theirs == ours:
            plan.files.append(FileChange(rel, theirs, ours))
        else:
            plan.notes.append(
                f"{rel} isn't vexsim's: the export leaves it as it is, and the routines and the "
                "simulation run it (to have vexsim's again, delete it and export again)"
            )


def generated_source(project: Path, exported: list, chassis) -> str:
    """``src/vexsim_autons.cpp``: each route as a routine, the headers its calls need."""
    headers = list(dict.fromkeys(h for _, route, _, _ in exported for h in route.functions))
    if chassis.header:
        headers.append(chassis.file)
    own = any(route.own_motions for _, route, _, _ in exported)
    includes = (["main.h"] if (project / "include" / "main.h").is_file() else []) + [
        "lemlib/api.hpp",
        *(["vexsim/motions.hpp"] if own else []),
        *(_include(h) for h in headers),
        _include(AUTON_HEADER),
    ]
    lines = [
        f"// Generated by vexsim from this project's routes ({FOLDER}/*.yaml): each route as a",
        f"// routine, declared in {AUTON_HEADER}. vexsim rewrites this file whole when the",
        "// routes are exported again: change the routes, not this file.",
        *(f'#include "{h}"' for h in dict.fromkeys(includes)),
    ]
    if not chassis.header:
        *scope, base = chassis.name.split("::")
        text = f"extern lemlib::Chassis {base};"
        for space in reversed(scope):
            text = f"namespace {space} {{ {text} }}"
        lines.append(text)
    for routine, route, functions, drive in exported:
        lines += ["", *routine_source(routine, route, functions, chassis.name, drive)]
    return "\n".join(lines) + "\n"


def routine_source(
    routine: Routine, route: Route, functions, chassis: str, drive=None
) -> list[str]:
    """One routine: the route's start as its setPose, then each step's call. A route with
    vexsim's own motions makes their ``vexsim::Motions`` first, with its ``drive`` model."""
    x, y, theta = (_number(v) for v in route.start)
    body = []
    if route.own_motions:
        model = ", ".join(
            f".{field} = {_number(getattr(drive, key))}" for key, field in DRIVE.items()
        )
        body += [
            "// vexsim's own motions, with the model of the drive the route was simulated with",
            f"static vexsim::Motions {OWN_MOTIONS}({chassis}, {{{model}}});",
        ]
    body.append(f"{chassis}.setPose({x}, {y}, {theta});")
    body += [step_call(step, functions, chassis) for step in route.steps]
    return [
        f"// {route.name} ({routine.route})",
        f"void {routine.name}() {{",
        *(INDENT + line for line in body),
        "}",
    ]


def step_call(step: Step, functions, chassis: str) -> str:
    """A step as the C++ call the route runner makes for it."""
    if step.kind == "wait":
        return f"pros::delay({_number(step.target[0])});"
    if step.kind == "wait_until":
        return f"{chassis}.waitUntil({_number(step.target[0])});"
    if step.kind == "wait_until_done":
        return f"{chassis}.waitUntilDone();"
    if step.kind == "call":
        fn = functions.named(step.function)
        values = call_arguments(step, functions)
        args = [
            _argument(param, value, functions)
            for param, value in zip(fn.params[: len(values)], values, strict=True)
        ]
        return f"{step.function}({', '.join(args)});"
    motion = MOTIONS[step.kind]
    args = [_number(v) for v in step.target]
    if step.kind == "ramsete":  # a std::vector<vexsim::Waypoint>
        args = ["{" + ", ".join(f"{{{_number(x)}, {_number(y)}}}" for x, y in step.points) + "}"]
    if motion.swing:
        args.append(f"lemlib::DriveSide::{SIDES[step.side]}")
    args.append(str(step.timeout))
    given = dict(step.options)
    params = [  # designated initializers, in the order LemLib's params struct declares them
        f".{OPTIONS[name].lemlib} = {_option(name, given[name])}"
        for name in OPTIONS
        if name in given
    ]
    if params or not step.is_async:
        args.append("{" + ", ".join(params) + "}")
    if not step.is_async:
        args.append("false")
    return f"{OWN_MOTIONS if motion.own else chassis}.{motion.lemlib}({', '.join(args)});"


def _option(name: str, value: Value) -> str:
    if name == "direction":
        return f"lemlib::AngularDirection::{DIRECTIONS[str(value)]}"
    return _number(value)


def _argument(param, value: Value, functions) -> str:
    if param.kind == "enum":
        return f"{functions.enums[param.enum].name}::{value}"
    return _number(value)


def _number(value: Value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value:.10g}" if isinstance(value, float) else str(value)


def _include(header: str) -> str:
    """How ``src/vexsim_autons.cpp`` includes a header (relative to the project)."""
    if header.startswith("include/"):
        return header.removeprefix("include/")
    return Path(os.path.relpath(header, "src")).as_posix()


# --- the declarations ---------------------------------------------------------------------------


def declarations(header: str | None, routines: list[Routine]) -> str:
    """auton.hpp (``header``'s text, or None if there's none yet) with the routines declared
    between the marker comments: in place of the ones there, or at its end."""
    newline = "\r\n" if header is not None and "\r\n" in header else "\n"
    block = [
        f"{BEGIN} (vexsim writes these from {FOLDER}/ when it exports the routes)",
        *(f"void {r.name}();  // {r.route}" for r in routines),
        END,
    ]
    if header is None:
        return newline.join(["#pragma once", "", *block]) + newline
    lines = header.splitlines()
    begin = next((k for k, line in enumerate(lines) if line.strip().startswith(BEGIN)), None)
    end = next((k for k, line in enumerate(lines) if line.strip().startswith(END)), None)
    if begin is not None and end is not None and begin < end:
        lines[begin : end + 1] = block
    elif begin is None and end is None:
        at = len(lines)
        while at > 0 and not lines[at - 1].strip():
            at -= 1
        if at > 0 and lines[at - 1].strip().startswith("#endif"):
            at -= 1  # inside its include guard
            while at > 0 and not lines[at - 1].strip():
                at -= 1
        apart = at < len(lines) and lines[at].strip()  # (from the #endif, if it's right after)
        lines[at:at] = ["", *block, *([""] if apart else [])]
    else:
        raise ExportError(
            f"{AUTON_HEADER} has one of the comments {BEGIN} and {END} but not the other, in "
            "that order: fix it by hand, or take both out"
        )
    return newline.join(lines) + newline


def _names_taken(project: Path, header: str | None) -> set[str]:
    """The functions the project's own headers declare, outside the exported block: names a
    routine can't take."""
    from vexsim.bridge.functions import find_functions
    from vexsim.bridge.routines import _functions, _statements, _tokens

    others = [h for h in project_headers(project) if h != AUTON_HEADER]
    found = find_functions(project, others)
    taken = {f.name for f in found.functions} | {o.name for o in found.others}
    if header is not None:
        lines = header.splitlines()
        begin = next((k for k, line in enumerate(lines) if line.strip().startswith(BEGIN)), None)
        end = next((k for k, line in enumerate(lines) if line.strip().startswith(END)), None)
        if begin is not None and end is not None and begin < end:
            lines[begin : end + 1] = [""] * (end + 1 - begin)  # (the lines stay numbered)
        for statement in _statements(_tokens("\n".join(lines))):
            taken |= {fn.name for fn in _functions(statement)}
    return taken

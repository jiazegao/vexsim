"""vexsim's route runner (phase 13), generated into a route build of a PROS project.

A route build (``build_project(..., route=headers)``) adds one file to the project's build,
in vexsim's build cache, so the project doesn't change: the project's headers, included as
its own files include them; the runner (cpp/route/runner.cpp); and after it the table of
the team's functions those headers declare (functions.py) and the project's own LemLib
chassis (``find_chassis``). The runner reads the route's steps when it runs, from the file
``VEXSIM_ROUTE`` names, which app/routes.py writes from the route's YAML as the run starts:
so a changed step reruns without a rebuild, and only a change to the headers rebuilds.

It runs as 12.1's routines do, inside autonomous(): the routine switch (routines.py) runs
it in place of the first routine autonomous() calls, and in a project without routines the
robot host runs it in place of autonomous(). It says what it does on the console (each step
as it starts and as its call returns, each LemLib motion as it starts and ends), which
``RouteRecord`` reads into where, and when, each step ended.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from vexsim.bridge.functions import TEMPLATE_DIRS, Function, Functions
from vexsim.bridge.routines import _statements, _tokens

ENV = "VEXSIM_ROUTE"
EVENT = "vexsim: route "  # how the runner's console lines begin
CORE = Path(__file__).parent / "cpp" / "route" / "runner.cpp"
HEADER_SUFFIXES = (".h", ".hpp", ".hh", ".hxx")
_NAME = re.compile(r"[A-Za-z_]\w*")


@dataclass(frozen=True)
class Chassis:
    """The project's ``lemlib::Chassis``: ``name`` as C++ code calls it, and where it's
    declared (relative to the project)."""

    name: str
    file: str
    line: int
    header: bool  # declared in a header, which the runner includes; else defined in a source


def find_chassis(project: str | Path) -> Chassis | str:
    """The project's LemLib chassis, or why vexsim can't drive it from a route."""
    from vexsim.bridge.build import SOURCE_SUFFIXES

    project = Path(project)
    found: list[Chassis] = []
    hidden: list[str] = []
    for top, suffixes in (("include", HEADER_SUFFIXES), ("src", SOURCE_SUFFIXES)):
        folder = project / top
        for path in sorted(folder.rglob("*")) if folder.is_dir() else []:
            rel = path.relative_to(project)
            if path.suffix not in suffixes or not path.is_file():
                continue
            if top == "include" and len(rel.parts) > 2 and rel.parts[1] in TEMPLATE_DIRS:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "Chassis" not in text:
                continue
            for statement in _statements(_tokens(text)):
                declared = _declared(statement)
                if declared is None:
                    continue
                name, specifiers, line = declared
                qualified = "::".join([*[s for s in statement.scope if s], name])
                header = top == "include"
                if "static" in specifiers or "" in statement.scope:
                    if not header:
                        hidden.append(f"{qualified} in {rel.as_posix()}")
                    continue
                if not header and "extern" in specifiers:
                    continue  # declared here, defined elsewhere
                found.append(Chassis(qualified, rel.as_posix(), line, header))
    names = list(dict.fromkeys(c.name for c in found))
    if len(names) == 1:
        return next((c for c in found if c.header), found[0])
    if names:
        return (
            f"the project declares more than one lemlib::Chassis ({', '.join(names)}), so "
            "vexsim can't tell which one a route drives"
        )
    if hidden:
        return (
            f"the project's lemlib::Chassis ({hidden[0]}) is static, so only its own file can "
            "reach it, and a route can't drive it"
        )
    return (
        "vexsim can't find the project's lemlib::Chassis (a declaration such as "
        "lemlib::Chassis chassis(...); in a header or a source file)"
    )


def _declared(statement) -> tuple[str, set[str], int] | None:
    """The name a statement declares a ``lemlib::Chassis`` by, its specifiers and line."""
    tokens = statement.tokens
    words = [t.text for t in tokens]
    k, specifiers = 0, set()
    while k < len(words) and words[k] in ("extern", "inline", "static", "constinit"):
        specifiers.add(words[k])
        k += 1
    rest = words[k:]
    for prefix in (["::", "lemlib", "::", "Chassis"], ["lemlib", "::", "Chassis"], ["Chassis"]):
        if rest[: len(prefix)] == prefix:
            at = k + len(prefix)
            break
    else:
        return None
    if at >= len(words) or not _NAME.fullmatch(words[at]):
        return None
    if at + 1 < len(words) and words[at + 1] not in ("(", "="):
        return None
    return words[at], specifiers, tokens[at].line


# --- the generated source -----------------------------------------------------------------------


def runner_source(
    project: str | Path,
    headers: list[str],
    functions: Functions,
    chassis: Chassis,
    stage: Path,
    left_out: dict[str, str] | None = None,
) -> str:
    """The route build's extra file: ``headers`` (relative to the project; the staged copies
    under ``stage``), the runner, the team's ``functions`` (and why it can't call those
    ``left_out``) and the ``chassis``."""
    project = Path(project)
    lines = [
        "// Generated by vexsim (vexsim/bridge/runner.py) for a route build: the route runner,",
        "// the team's functions from the route's headers, and the project's LemLib chassis.",
    ]
    if (project / "include" / "main.h").is_file():
        lines.append('#include "main.h"')
    lines.append('#include "lemlib/api.hpp"')
    included = list(dict.fromkeys([*headers, *([chassis.file] if chassis.header else [])]))
    lines += [f'#include "{_include(h, stage)}"' for h in included]
    if not chassis.header:
        lines.append(_namespaced(chassis.name, lambda base: f"extern lemlib::Chassis {base};"))
    lines += ["", CORE.read_text(encoding="utf-8").rstrip("\n"), ""]
    enums = {e.name: f"enum_{k}" for k, e in enumerate(functions.used_enums())}
    lines += [
        "namespace vexsim_route {",
        "",
        f"lemlib::Chassis& chassis() {{ return ::{chassis.name}; }}",
    ]
    if enums:
        lines += ["", "// the enums the functions take, by their values' names"]
    for enum in functions.used_enums():
        values = ", ".join(f'{{"{v}", ::{enum.name}::{v}}}' for v in enum.values)
        lines.append(f"const Named<::{enum.name}> {enums[enum.name]}[] = {{{values}}};")
    for k, fn in enumerate(functions.functions):
        lines += _wrapper(k, fn, enums)
    lines += ["", "const char* call(const std::string& name, const Args& args) {"]
    lines += [
        f'\tif (name == "{fn.name}") return call_{k}(args);'
        for k, fn in enumerate(functions.functions)
    ]
    lines += [f'\tif (name == "{name}") return "{why}";' for name, why in (left_out or {}).items()]
    lines += [
        "\treturn \"isn't one of the functions the route's headers declare in this build\";",
        "}",
        "",
        "}  // namespace vexsim_route",
    ]
    return "\n".join(lines) + "\n"


def _include(header: str, stage: Path) -> str:
    return (
        header.removeprefix("include/")
        if header.startswith("include/")
        else (stage / header).as_posix()
    )


def _namespaced(name: str, declaration) -> str:
    *scope, base = name.split("::")
    text = declaration(base)
    for space in reversed(scope):
        text = f"namespace {space} {{ {text} }}"
    return text


def _wrapper(k: int, fn: Function, enums: dict[str, str]) -> list[str]:
    """A function that calls ``fn`` with a route's arguments: as many as were given."""
    lines = [
        "",
        f"// {fn.declaration()} ({fn.header}:{fn.line})",
        f"const char* call_{k}(const Args& a) {{",
    ]
    if fn.params:
        lines.append("\t" + " ".join(f"{_type(p)} p{i}{{}};" for i, p in enumerate(fn.params)))
        reads = " || ".join(
            f"!a.get({i}, p{i}" + (f", {enums[p.enum]})" if p.enum else ")")
            for i, p in enumerate(fn.params)
        )
        lines.append(f"\tif ({reads}) return a.why();")
    lines.append("\tswitch (a.size()) {")
    for count in range(fn.required, len(fn.params) + 1):
        args = ", ".join(f"p{i}" for i in range(count))
        lines.append(f"\t\tcase {count}: ::{fn.name}({args}); return nullptr;")
    lines.append("\t}")
    takes = (
        f"{fn.required}" if fn.required == len(fn.params) else f"{fn.required} to {len(fn.params)}"
    )
    lines += [f'\treturn "takes {takes} argument(s)";', "}"]
    return lines


def _type(param) -> str:
    return f"::{param.enum}" if param.kind == "enum" else param.type


# --- what the runner says ------------------------------------------------------------------------


@dataclass(frozen=True)
class Moment:
    """When something happened, where the robot was (LemLib's convention: x, y in inches,
    theta clockwise from +y) and where LemLib's odometry put it."""

    time_s: float
    pose: tuple[float, float, float]
    lemlib: tuple[float, float, float] | None = None


@dataclass
class StepRecord:
    number: int
    started: Moment | None = None
    called: Moment | None = None  # its call returned
    first_motion: int = 0  # the motions it started: first_motion up to (not with) last_motion
    last_motion: int | None = None

    @property
    def motions(self) -> range:
        return range(
            self.first_motion, self.first_motion if self.last_motion is None else self.last_motion
        )


@dataclass
class MotionRecord:
    started: Moment | None = None
    ended: Moment | None = None


@dataclass
class RouteRecord:
    """What a route's run said, line by line (``CppProgram`` hands it the console's)."""

    started: Moment | None = None
    ended: Moment | None = None
    error: str | None = None
    steps: dict[int, StepRecord] = field(default_factory=dict)
    motions: dict[int, MotionRecord] = field(default_factory=dict)

    def read(self, text: str, time_s: float, pose: tuple[float, float, float]) -> bool:
        """Note one console line of the run; False if it isn't the runner's."""
        if not text.startswith(EVENT):
            return False
        words = text[len(EVENT) :].split()
        lemlib = _pose(words[-3:]) if len(words) >= 3 else None
        moment = Moment(time_s, pose, lemlib)
        if text.startswith(EVENT + "can't run: "):
            self.error = text[len(EVENT + "can't run: ") :]
        elif words == ["starts"]:
            self.started = moment
        elif words == ["ends"]:
            self.ended = moment
        elif len(words) >= 4 and words[0] == "step" and words[1].isdigit():
            step = self.steps.setdefault(int(words[1]), StepRecord(int(words[1])))
            if words[2] == "starts":
                step.started, step.first_motion = Moment(time_s, pose), int(words[3])
            elif words[2] == "called":
                step.called, step.last_motion = moment, int(words[3])
        elif len(words) >= 3 and words[0] == "motion" and words[1].isdigit():
            motion = self.motions.setdefault(int(words[1]), MotionRecord())
            if words[2] == "starts":
                motion.started = Moment(time_s, pose)
            elif words[2] == "ends":
                motion.ended = moment
        else:
            return False
        return True

    @property
    def done(self) -> bool:
        """Whether there's nothing more to learn: the route can't run, or it ran and every
        motion it started has ended."""
        if self.error is not None:
            return True
        return self.ended is not None and all(m.ended is not None for m in self.motions.values())

    def step_end(self, number: int) -> Moment | None:
        """When step ``number`` ended: its call returned and every motion it started ended
        (None if it didn't, before the run stopped)."""
        step = self.steps.get(number)
        if step is None or step.called is None:
            return None
        end = step.called
        for k in step.motions:
            motion = self.motions.get(k)
            if motion is None or motion.ended is None:
                return None
            if motion.ended.time_s > end.time_s:
                end = motion.ended
        return end

    def motion_time(self, number: int) -> float | None:
        """How long step ``number``'s own motion took (s): from when it started (after the
        motions queued before it) to when it ended."""
        step = self.steps.get(number)
        if step is None or step.started is None:
            return None
        if len(step.motions) == 1:  # an async motion: its task's life
            motion = self.motions.get(step.first_motion)
            if motion and motion.started and motion.ended:
                return motion.ended.time_s - motion.started.time_s
            return None
        end = self.step_end(number)
        if end is None:
            return None
        before = [
            m.ended.time_s
            for k, m in self.motions.items()
            if k < step.first_motion and m.ended is not None
        ]
        begin = max([step.started.time_s, *before])  # a motion waits for the ones before it
        return end.time_s - begin


def _pose(words: list[str]) -> tuple[float, float, float] | None:
    try:
        x, y, theta = (float(w) for w in words)
    except ValueError:
        return None
    return (x, y, theta)

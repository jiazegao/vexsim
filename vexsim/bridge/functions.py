"""The team's own functions, as steps of a route (phase 13): read from a PROS project's headers.

A route calls the functions its headers declare: each one that returns ``void`` and takes
numbers, ``bool``s or values of an enum (with or without defaults), such as 1239E's
``void moveForward(float inches, int timeout, float maxSpeed=127, float minSpeed=1,
bool async=true);`` or ``void startFrontIntake(int velocity = 127);``. ``find_functions``
reads them with 12.1's tokenizer (routines.py), with their parameters' names, types and
defaults (as written), and says why each other function can't be a step. The enums a
parameter can take are the ones the headers declare, or the project headers they include
(and LemLib's two, which a project's headers may not hold).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

from vexsim.bridge.routines import _arguments, _functions, _Statement, _statements, _Token, _tokens

# Parameter types that are numbers: integral ones take whole numbers
INTEGRAL = {
    "char", "short", "int", "long", "signed", "unsigned", "size_t", "int8_t", "int16_t",
    "int32_t", "int64_t", "uint8_t", "uint16_t", "uint32_t", "uint64_t",
}  # fmt: skip
FLOATING = {"float", "double"}
_KEYWORDS = INTEGRAL | FLOATING | {"bool", "void", "auto"}
# LemLib 0.5's enums, which a project's own headers may not declare
LEMLIB_ENUMS = {
    "lemlib::DriveSide": ("LEFT", "RIGHT"),
    "lemlib::AngularDirection": ("CW_CLOCKWISE", "CCW_COUNTERCLOCKWISE", "AUTO"),
}
# headers of the templates a PROS project holds, never the team's own
TEMPLATE_DIRS = ("pros", "lemlib", "liblvgl", "fmt", "display", "okapi")
_INCLUDE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*[<"]([^>"\n]+)[>"]', re.M)
# A comment just above a function's declaration that says how it moves the robot, for the
# maker's plan (PLAN.md 13.2): `// vexsim: drive(inches)`, each argument one of the
# function's parameters or a number
HINTS = {
    "drive": ("inches",),  # straight along the heading (back, if negative)
    "turn_by": ("degrees",),  # in place, clockwise (LemLib's sense)
    "arc": ("radius", "degrees"),  # along an arc, turning clockwise through the angle
    "point": ("x", "y"),  # as move_to_point
    "pose": ("x", "y", "theta"),  # as move_to_pose
    "none": (),  # it doesn't move the robot
}
_HINT = re.compile(r"//\s*vexsim:\s*(.*?)\s*$")
_HINT_CALL = re.compile(r"([A-Za-z_]\w*)\s*(?:\((.*)\))?")
_HEX = re.compile(r"([-+]?)0[xX]([0-9a-fA-F]+)[uUlL]*")
_DECIMAL = re.compile(r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)[fFlLuU]*")


@dataclass(frozen=True)
class Param:
    name: str
    type: (
        str  # the C++ type as written, without const: "float", "std::uint8_t", "lemlib::DriveSide"
    )
    kind: str  # "integer", "number", "bool" or "enum"
    default: str | None = None  # as written: "127", "true", "lemlib::AngularDirection::AUTO"
    enum: str | None = None  # an enum parameter's enum, qualified

    def literal(self, values: tuple[str, ...] = ()) -> int | float | bool | str | None:
        """The default as a value a route passes: a number, a bool, or (given the enum's
        ``values``) an enumerator's name; None if there's none, or it's an expression."""
        text = (self.default or "").replace("'", "")
        if self.kind == "enum":
            name = text.split("::")[-1]
            return name if name in values else None
        if text in ("true", "false"):
            return text == "true" if self.kind == "bool" else int(text == "true")
        hexadecimal = _HEX.fullmatch(text)
        decimal = _DECIMAL.fullmatch(text)
        if hexadecimal:
            value: float = int(hexadecimal[1] + hexadecimal[2], 16)
        elif decimal:
            value = float(decimal[1])
            if self.kind == "integer" or re.fullmatch(r"[-+]?\d+", decimal[1]):
                value = int(value)
        else:
            return None
        return bool(value) if self.kind == "bool" else value


@dataclass(frozen=True)
class Hint:
    """How a function moves the robot, as its ``// vexsim:`` comment says: one of ``HINTS``,
    each argument a parameter's name or a number."""

    motion: str
    args: tuple[str | float, ...] = ()


@dataclass(frozen=True)
class Function:
    """A function a route can call: ``name`` as C++ calls it (``moveForward``,
    ``auton::wiggle``)."""

    name: str
    header: str  # where it's declared, relative to the project, with /
    line: int
    params: tuple[Param, ...] = ()
    defined: bool = False  # the header defines it too (so every file that includes it can call it)
    hint: Hint | None = None  # how it moves the robot, if a comment says
    hint_problem: str | None = None  # why its vexsim: comment doesn't read

    @property
    def required(self) -> int:
        """How many arguments a call needs (the parameters before the first default)."""
        return next(
            (k for k, p in enumerate(self.params) if p.default is not None), len(self.params)
        )

    def param(self, name: str) -> Param | None:
        return next((p for p in self.params if p.name == name), None)

    def declaration(self) -> str:
        """``void moveForward(float inches, int timeout, float maxSpeed = 127)``."""
        params = ", ".join(
            f"{p.type} {p.name}" + ("" if p.default is None else f" = {p.default}")
            for p in self.params
        )
        return f"void {self.name}({params})"


@dataclass(frozen=True)
class NotFunction:
    """A function a header declares that a route can't call, and why."""

    name: str
    header: str
    line: int
    why: str


@dataclass(frozen=True)
class Enum:
    name: str  # qualified
    values: tuple[str, ...]  # its enumerators, in order


@dataclass
class Functions:
    functions: list[Function] = field(default_factory=list)
    others: list[NotFunction] = field(default_factory=list)
    enums: dict[str, Enum] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)  # headers that aren't there

    def named(self, name: str) -> Function | None:
        return next((f for f in self.functions if f.name == name), None)

    def why_not(self, name: str) -> str | None:
        """Why ``name`` can't be called, if a header declares it."""
        return next((o.why for o in self.others if o.name == name), None)

    def used_enums(self) -> list[Enum]:
        """The enums the functions' parameters take, in order of first use."""
        names = dict.fromkeys(p.enum for f in self.functions for p in f.params if p.enum)
        return [self.enums[n] for n in names if n in self.enums]


def find_functions(project: str | Path, headers: Iterable[str]) -> Functions:
    """The functions ``headers`` (relative to the project) declare, and the enums they take."""
    project = Path(project)
    headers = list(dict.fromkeys(headers))
    found = Functions()
    found.missing = [h for h in headers if not (project / h).is_file()]
    found.enums = find_enums(project, [h for h in headers if h not in found.missing])
    seen: dict[str, Function | NotFunction] = {}
    overloaded: set[str] = set()
    for header in headers:
        if header in found.missing:
            continue
        statements, lines = _read_header(project / header)
        for statement in statements:
            for fn in _functions(statement):
                if fn.deleted or fn.name.split("::")[-1].startswith("vexsim"):
                    continue
                made = _read(fn, header, found.enums)
                if isinstance(made, Function):
                    made = _hinted(made, lines)
                before = seen.get(fn.name)
                if before is None:
                    seen[fn.name] = made
                elif _signature(before) != _signature(made):
                    overloaded.add(fn.name)
    for name, made in seen.items():
        if name in overloaded:
            found.others.append(NotFunction(name, made.header, made.line, "is overloaded"))
        elif isinstance(made, Function):
            found.functions.append(made)
        else:
            found.others.append(made)
    return found


def _hinted(fn: Function, lines: list[str]) -> Function:
    """``fn`` with what the ``// vexsim:`` comment just above its declaration says."""
    line = fn.line - 2  # the line above, from 0
    while line >= 0 and lines[line].strip().startswith("//"):
        match = _HINT.search(lines[line])
        if match:
            hint = read_hint(match.group(1), fn)
            if isinstance(hint, str):
                return replace(fn, hint_problem=hint)
            return replace(fn, hint=hint)
        line -= 1
    return fn


def read_hint(text: str, fn: Function) -> Hint | str:
    """A ``// vexsim:`` comment's words (``drive(inches)``) for ``fn``, or why they don't read."""
    call = _HINT_CALL.fullmatch(text.strip())
    if not call or call.group(1) not in HINTS:
        known = (f"{k}({', '.join(v)})" if v else k for k, v in HINTS.items())
        return f"vexsim: {text} isn't one of " + ", ".join(known)
    motion, wanted = call.group(1), HINTS[call.group(1)]
    words = [w.strip() for w in (call.group(2) or "").split(",") if w.strip()]
    if len(words) != len(wanted):
        return f"vexsim: {motion} takes {len(wanted)} argument(s): " + ", ".join(wanted)
    args: list[str | float] = []
    for word in words:
        param = fn.param(word)
        if param is not None and param.kind in ("integer", "number"):
            args.append(word)
            continue
        try:
            args.append(float(word))
        except ValueError:
            return f"vexsim: {word} isn't a number, or one of {fn.name}()'s number parameters"
    return Hint(motion, tuple(args))


def _signature(made: Function | NotFunction) -> object:
    return tuple(p.type for p in made.params) if isinstance(made, Function) else made.why


def _read(fn, header: str, enums: dict[str, Enum]) -> Function | NotFunction:
    """A declaration as a step a route can call, or why it can't be one."""
    if fn.returns != ["void"]:
        return NotFunction(fn.name, header, fn.line, "returns a value")
    if "static" in fn.specifiers or fn.anonymous:
        return NotFunction(fn.name, header, fn.line, "is static: only its own file can call it")
    params: list[Param] = []
    group = [_Token("punct", "(", 0), *fn.param_tokens, _Token("punct", ")", 0)]
    for piece in [] if fn.params in ([], ["void"]) else _arguments(group):
        param = _param(piece, enums)
        if isinstance(param, str):
            return NotFunction(fn.name, header, fn.line, param)
        params.append(param)
    return Function(fn.name, header, fn.line, tuple(params), fn.defined)


def _param(tokens: list[_Token], enums: dict[str, Enum]) -> Param | str:
    """A parameter, or why it isn't one a route can pass."""
    words = [t.text for t in tokens]
    default = None
    if "=" in words:
        at = words.index("=")
        default = _spelled(tokens[at + 1 :])
        tokens, words = tokens[:at], words[:at]
    if "." in words:
        return "takes any number of arguments"
    if any(w in ("*", "&", "[", "<", "(") for w in words):
        return "takes a pointer, a reference, an array, a template or a function"
    kept = [t for t in tokens if t.text not in ("const", "volatile", "enum", "struct", "class")]
    if (
        len(kept) < 2
        or kept[-1].kind != "id"
        or kept[-1].text in _KEYWORDS
        or kept[-2].text == "::"
    ):
        return "has a parameter without a name, which a route's arguments go by"
    name, type_tokens = kept[-1].text, kept[:-1]
    spelled = _spelled(type_tokens).removeprefix("::")
    words = [t.text for t in type_tokens if t.text not in ("std", "::")]
    if words == ["bool"]:
        return Param(name, spelled, "bool", default)
    if all(w in INTEGRAL for w in words) and words != ["char"]:
        return Param(name, spelled, "integer", default)
    if all(w in FLOATING or w == "long" for w in words) and FLOATING & set(words):
        return Param(name, spelled, "number", default)
    enum = _enum_named(spelled, enums)
    if enum is None:
        return f"takes a {spelled}, which a route can't pass (it passes numbers, bools and enums)"
    return Param(name, spelled, "enum", default, enum.name)


def _spelled(tokens: list[_Token]) -> str:
    """Tokens as C++ text: a space only between two words."""
    text = ""
    for k, t in enumerate(tokens):
        if k and t.kind in ("id", "num") and tokens[k - 1].kind in ("id", "num"):
            text += " "
        text += t.text
    return text


def _enum_named(spelled: str, enums: dict[str, Enum]) -> Enum | None:
    if spelled in enums:
        return enums[spelled]
    tail = spelled.split("::")[-1]
    matches = [e for n, e in enums.items() if n == tail or n.endswith("::" + tail)]
    return matches[0] if len(matches) == 1 else None


# --- the enums ----------------------------------------------------------------------------------


def find_enums(project: str | Path, headers: Iterable[str]) -> dict[str, Enum]:
    """The enums ``headers`` declare, and the project headers they include (LemLib's too), by
    qualified name."""
    project = Path(project)
    enums = {name: Enum(name, values) for name, values in LEMLIB_ENUMS.items()}
    for path in included(project, headers):
        for statement in _read_statements(path):
            enum = _enum(statement)
            if enum is not None:
                enums[enum.name] = enum
    return enums


def _enum(statement: _Statement) -> Enum | None:
    words = [t.text for t in statement.tokens]
    if not words or words[0] != "enum" or statement.body is None:
        return None
    names = [w for w in words[1:] if w not in ("class", "struct") and w.isidentifier()]
    if not names:
        return None  # an anonymous enum
    group = [_Token("punct", "{", 0), *statement.body, _Token("punct", "}", 0)]
    values = tuple(p[0].text for p in _arguments(group) if p and p[0].kind == "id")
    return Enum("::".join([*[s for s in statement.scope if s], names[0]]), values)


def included(project: str | Path, headers: Iterable[str]) -> list[Path]:
    """``headers`` and the project's own headers they include, again and again (not the
    PROS, LemLib or other templates' headers a project holds)."""
    project = Path(project).resolve()
    include = project / "include"
    queue = [(project / h).resolve() for h in headers]
    found: list[Path] = []
    while queue:
        path = queue.pop(0)
        if path in found or not path.is_file() or _template_header(path, include):
            continue
        found.append(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name in _INCLUDE.findall(text):
            for base in (path.parent, include):
                candidate = (base / name).resolve()
                if candidate.is_file() and candidate.is_relative_to(project):
                    queue.append(candidate)
                    break
    return found


def _template_header(path: Path, include: Path) -> bool:
    return path.is_relative_to(include) and path.relative_to(include).parts[0] in TEMPLATE_DIRS


def _read_statements(path: Path) -> list[_Statement]:
    return _read_header(path)[0]


def _read_header(path: Path) -> tuple[list[_Statement], list[str]]:
    try:
        stat = path.stat()
    except OSError:
        return [], []
    return _header_of(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=256)
def _header_of(path: str, mtime_ns: int, size: int) -> tuple[list[_Statement], list[str]]:
    """A header's statements and lines, read once while it's unchanged (a route is checked
    often)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return list(_statements(_tokens(text))), text.splitlines()

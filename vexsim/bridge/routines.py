"""A PROS project's autonomous routines, and the switch that runs the one picked.

The routines are the functions a project's ``include/custom/auton.hpp`` declares that take
no arguments and return nothing (``void left40();``, in any namespace), as team 1239E's
project has them. ``find_routines`` reads them, with where each one starts when its
definition sets LemLib's pose (``chassis.setPose(60, 0, 90)``).

The project runs the routine picked in the app without changing. ``vexsim build`` compiles
each file that defines routines with a header of its own included first
(``rename_header``), which gives those routines other names (``asm`` labels), so calls
among them stay as written; and it adds a file (``switch_source``) that takes the
routines' own names. Each of those runs the routine it names, except the first one called
in the autonomous period while ``VEXSIM_ROUTINE`` names a routine: that one runs the
routine named instead, and says so on the console. So the project's own ``autonomous()``
runs as written, setup and all, and the routine it calls becomes the one picked.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

AUTON_HEADER = "include/custom/auton.hpp"
ENV = "VEXSIM_ROUTINE"
NOTE = "vexsim: autonomous() called "  # how the switch's console note begins


@dataclass(frozen=True)
class Routine:
    """A routine: ``name`` as C++ code calls it (``left40``, or ``auton::left40``)."""

    name: str
    line: int  # its declaration's, in the header
    c_linkage: bool = False  # declared extern "C"
    noexcept: bool = False
    start: tuple[float, float, float] | None = None  # LemLib's x, y, theta from its setPose
    source: str | None = None  # the file that defines it, relative to the project, with /

    @property
    def scope(self) -> list[str]:
        return self.name.split("::")[:-1]

    @property
    def base(self) -> str:
        return self.name.split("::")[-1]

    @property
    def symbol(self) -> str:
        """Its name in object files: Itanium C++ mangling, or a C function's own."""
        if self.c_linkage:
            return self.base
        parts = "".join(f"{len(p)}{p}" for p in self.name.split("::"))
        return f"_ZN{parts}Ev" if self.scope else f"_Z{parts}v"

    @property
    def renamed(self) -> str:
        """The name the switch calls the project's own routine by."""
        return "vexsim_routine_" + self.symbol

    def start_pose(self) -> tuple[float, float, float] | None:
        """Where it starts, as vexsim has poses: x, y (in) and heading (degrees,
        counter-clockwise from +x; LemLib's theta is clockwise from +y)."""
        if self.start is None:
            return None
        x, y, theta = self.start
        heading = (90.0 - theta) % 360.0
        return (x, y, heading - 360.0 if heading > 180.0 else heading)


@dataclass(frozen=True)
class NotRoutine:
    """A function the header declares that can't be a routine, and why."""

    name: str
    line: int
    why: str


@dataclass
class Routines:
    header: Path
    routines: list[Routine] = field(default_factory=list)
    others: list[NotRoutine] = field(default_factory=list)

    def named(self, name: str) -> Routine | None:
        return next((r for r in self.routines if r.name == name), None)


def find_routines(project: str | Path) -> Routines | None:
    """The routines ``project``'s auton.hpp declares, where each is defined and where it
    starts; None if it has no such header."""
    project = Path(project)
    header = project / AUTON_HEADER
    if not header.is_file():
        return None
    found = Routines(header)
    seen: set[str] = set()
    tokens = _tokens(header.read_text(encoding="utf-8", errors="replace"))
    for statement in _statements(tokens):
        for fn in _functions(statement):
            if fn.name in seen or fn.deleted:
                continue
            seen.add(fn.name)
            why = fn.why_not()
            if why:
                found.others.append(NotRoutine(fn.name, fn.line, why))
            else:
                found.routines.append(Routine(fn.name, fn.line, fn.c_linkage, fn.noexcept))
    if found.routines:
        _find_definitions(project, found)
    return found


# --- reading C++ ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Token:
    kind: str  # id, num, str or punct
    text: str
    line: int


_IDENT = re.compile(r"[A-Za-z_]\w*")
_NUMBER = re.compile(r"\.?\d(?:[\w.]|'(?=\w)|(?<=[eEpP])[-+])*")
_RAW = re.compile(r'(?:u8|[uUL])?R"([^()\\\s]{0,16})\((.*?)\)\1"', re.S)
_TYPES = {
    "void", "bool", "char", "short", "int", "long", "float", "double", "signed", "unsigned",
    "auto", "decltype", "sizeof", "alignof", "return", "if", "while", "for", "switch",
}  # fmt: skip


def _tokens(text: str) -> list[_Token]:
    """C++ tokens, without comments and preprocessor lines (rough, but enough for
    declarations)."""
    tokens: list[_Token] = []
    i, n, line, line_start = 0, len(text), 1, True
    while i < n:
        c = text[i]
        if c == "\n":
            i, line, line_start = i + 1, line + 1, True
            continue
        if c in " \t\r\f\v":
            i += 1
            continue
        if c == "\\" and text.startswith("\n", i + 1):  # a continued line
            i, line = i + 2, line + 1
            continue
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            line += text.count("\n", i, end)
            i = end
            continue
        if c == "#" and line_start:  # a preprocessor directive, continued lines and all
            while i < n and text[i] != "\n":
                if text[i] == "\\" and text.startswith("\n", i + 1):
                    i, line = i + 2, line + 1
                elif text.startswith("/*", i):
                    end = text.find("*/", i + 2)
                    end = n if end < 0 else end + 2
                    line += text.count("\n", i, end)
                    i = end
                else:
                    i += 1
            continue
        line_start = False
        raw = _RAW.match(text, i)
        if raw:
            tokens.append(_Token("str", raw.group(0), line))
            line += raw.group(0).count("\n")
            i = raw.end()
            continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] not in (c, "\n"):
                j += 2 if text[j] == "\\" else 1
            tokens.append(_Token("str", text[i : j + 1], line))
            i = j + 1
            continue
        for kind, pattern in (("id", _IDENT), ("num", _NUMBER)):
            match = pattern.match(text, i)
            if match:
                tokens.append(_Token(kind, match.group(0), line))
                i = match.end()
                break
        else:
            width = 2 if text.startswith("::", i) else 1
            tokens.append(_Token("punct", text[i : i + width], line))
            i += width
    return tokens


@dataclass
class _Statement:
    """A declaration at namespace scope: its tokens (up to ``;``, or up to its body's
    ``{``), its namespaces and linkage, and its body's tokens if it has one."""

    tokens: list[_Token]
    scope: list[str]
    c_linkage: bool
    body: list[_Token] | None = None


def _statements(tokens: list[_Token]) -> Iterator[_Statement]:
    scope: list[str] = []
    frames: list[tuple[str, int]] = []  # each open namespace (names pushed) or linkage block
    linkage: list[bool] = [False]
    current: list[_Token] = []
    i, n = 0, len(tokens)
    while i < n:
        token = tokens[i]
        text = token.text if token.kind == "punct" else None
        if text == "}":  # the end of a namespace or a linkage block
            if frames:
                kind, count = frames.pop()
                if kind == "namespace":
                    del scope[len(scope) - count :]
                else:
                    linkage.pop()
            current = []
            i += 1
        elif text == ";":
            if current:
                yield _Statement(current, list(scope), linkage[-1])
            current = []
            i += 1
        elif text == "{":
            words = [t.text for t in current]
            if "namespace" in words[:2] and (words[0] == "namespace" or words[0] == "inline"):
                names = [t.text for t in current[words.index("namespace") + 1 :] if t.kind == "id"]
                names = names or [""]  # an anonymous namespace
                scope += names
                frames.append(("namespace", len(names)))
                current = []
                i += 1
                continue
            if len(current) == 2 and words[0] == "extern" and current[1].kind == "str":
                frames.append(("linkage", 0))
                linkage.append(current[1].text == '"C"')
                current = []
                i += 1
                continue
            end = _matching(tokens, i)
            yield _Statement(current, list(scope), linkage[-1], tokens[i + 1 : end])
            current = []
            i = end + 1
        else:
            current.append(token)
            i += 1


def _matching(tokens: list[_Token], start: int) -> int:
    """The index of the bracket that closes the one at ``start`` (or the end)."""
    opening = tokens[start].text
    closing = {"{": "}", "(": ")", "[": "]"}[opening]
    depth = 0
    for k in range(start, len(tokens)):
        if tokens[k].kind != "punct":
            continue
        if tokens[k].text == opening:
            depth += 1
        elif tokens[k].text == closing:
            depth -= 1
            if depth == 0:
                return k
    return len(tokens) - 1


@dataclass
class _Function:
    name: str  # qualified by its namespaces
    line: int
    returns: list[str]
    params: list[str]
    specifiers: set[str]
    c_linkage: bool
    noexcept: bool
    deleted: bool  # = delete, or = 0
    defined: bool  # it has a body here
    anonymous: bool  # in an anonymous namespace

    def why_not(self) -> str:
        """Why it can't be a routine ("" if it can)."""
        if self.params not in ([], ["void"]):
            return "takes arguments"
        if self.returns != ["void"]:
            return "returns a value"
        if self.defined:
            return "is defined in the header, so every file has its own copy"
        if "static" in self.specifiers or self.anonymous:
            return "only the file that defines it can call it (static, or an anonymous namespace)"
        if self.specifiers & {"constexpr", "consteval", "inline"}:
            return "is inline, so every file has its own copy"
        return ""


_SKIP = {"template", "typedef", "using", "class", "struct", "enum", "union", "static_assert"}
_SPECIFIERS = {
    "extern", "inline", "static", "constexpr", "consteval", "virtual", "explicit", "friend",
    "thread_local",
}  # fmt: skip
_QUALIFIERS = {"const", "volatile"}


def _functions(statement: _Statement) -> Iterator[_Function]:
    """The functions a statement declares (or defines)."""
    tokens = _without_attributes(statement.tokens)
    words = [t.text for t in tokens]
    if not tokens or words[0] in _SKIP or "operator" in words:
        return
    specifiers: set[str] = set()
    c_linkage = statement.c_linkage
    k = 0
    while k < len(tokens) and (tokens[k].text in _SPECIFIERS or tokens[k].kind == "str"):
        if tokens[k].kind == "str":
            c_linkage = tokens[k].text == '"C"'
        else:
            specifiers.add(tokens[k].text)
        k += 1
    rest = tokens[k:]
    open_at = _first_call(rest)
    if open_at is None or open_at == 0:
        return
    name_at = open_at - 1
    if rest[name_at].kind != "id" or rest[name_at].text in _TYPES:
        return  # a function pointer, a cast, an initializer
    first = name_at
    while first >= 2 and rest[first - 1].text == "::" and rest[first - 2].kind == "id":
        first -= 2
    returns = [t.text for t in rest[:first] if t.text not in _QUALIFIERS]
    if not returns:
        return  # a call (a macro's, say)
    # each declarator (void a(), b();) up to the comma after its parameters
    declarators, tail = [], rest[first:]
    while tail:
        at = _first_call(tail)
        if at is None or at == 0 or tail[at - 1].kind != "id":
            break
        close = _matching(tail, at)
        end = next((j for j in range(close + 1, len(tail)) if tail[j].text == ","), len(tail))
        declarators.append((tail[:at], tail[at + 1 : close], tail[close + 1 : end]))
        tail = tail[end + 1 :]
    for before, params, trailing in declarators:
        names = [t.text for t in before if t.text != "::"]
        scope = list(statement.scope) if len(names) == 1 else names[:-1]
        words = [t.text for t in trailing]
        yield _Function(
            name="::".join([*[s for s in scope if s], names[-1]]),
            line=before[-1].line,
            returns=returns,
            params=[t.text for t in params],
            specifiers=specifiers,
            c_linkage=c_linkage,
            noexcept="noexcept" in words and "false" not in words,
            deleted="=" in words,
            defined=statement.body is not None,
            anonymous="" in statement.scope,
        )


def _without_attributes(tokens: list[_Token]) -> list[_Token]:
    """Tokens without [[...]], __attribute__((...)), __declspec(...) and alignas(...)."""
    out: list[_Token] = []
    k = 0
    while k < len(tokens):
        t = tokens[k]
        if t.text == "[" and k + 1 < len(tokens) and tokens[k + 1].text == "[":
            k = _matching(tokens, k) + 1
            continue
        if t.text in ("__attribute__", "__declspec", "alignas") and k + 1 < len(tokens):
            if tokens[k + 1].text == "(":
                k = _matching(tokens, k + 1) + 1
                continue
        out.append(t)
        k += 1
    return out


def _first_call(tokens: list[_Token]) -> int | None:
    """Where the first ( outside <...> is."""
    angle = 0
    for k, t in enumerate(tokens):
        if t.kind != "punct":
            continue
        if t.text == "<":
            angle += 1
        elif t.text == ">" and angle:
            angle -= 1
        elif t.text == "(" and not angle:
            return k
    return None


# --- where each routine is defined, and where it starts -------------------------------------


def _find_definitions(project: Path, found: Routines) -> None:
    from vexsim.bridge.build import SOURCE_SUFFIXES

    wanted = {r.name: r for r in found.routines}
    bases = {r.base for r in found.routines}
    located: dict[str, Routine] = {}
    src = project / "src"
    for path in sorted(src.rglob("*")) if src.is_dir() else []:
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not any(base in text for base in bases):
            continue  # (a picture as a C array, say: nothing to read)
        rel = path.relative_to(project).as_posix()
        for statement in _statements(_tokens(text)):
            if statement.body is None:
                continue
            for fn in _functions(statement):
                routine = wanted.get(fn.name)
                takes_nothing = fn.params in ([], ["void"]) and fn.returns == ["void"]
                if routine is not None and takes_nothing and fn.name not in located:
                    located[fn.name] = replace(routine, start=_set_pose(statement.body), source=rel)
    found.routines = [located.get(r.name, r) for r in found.routines]


def _set_pose(body: list[_Token]) -> tuple[float, float, float] | None:
    """LemLib's x, y, theta (degrees) from the first setPose(...) in ``body``, when its
    arguments are numbers: setPose(60, 0, 90), setPose({60, 0, 90}), setPose(Pose(...))."""
    for k, t in enumerate(body[:-1]):
        if t.text != "setPose" or body[k + 1].text != "(":
            continue
        args = _arguments(body[k + 1 : _matching(body, k + 1) + 1])
        if len(args) in (1, 2) and args[0] and args[0][-1].text in (")", "}"):
            inner = args[0]
            opening = next((j for j, a in enumerate(inner) if a.text in ("(", "{")), None)
            radians = len(args) == 2 and _is_true(args[1])
            args = _arguments(inner[opening:]) if opening is not None else []
        else:
            radians = len(args) >= 4 and _is_true(args[3])
        numbers = [_number(a) for a in args[:3]]
        if len(args) >= 3 and all(v is not None for v in numbers):
            x, y, theta = numbers
            return (x, y, math.degrees(theta) if radians else theta)
        return None
    return None


def _arguments(group: list[_Token]) -> list[list[_Token]]:
    """The comma-separated arguments inside a bracketed group of tokens."""
    args: list[list[_Token]] = [[]]
    depth = 0
    for t in group[1:-1]:
        if t.kind == "punct" and t.text in "([{":
            depth += 1
        elif t.kind == "punct" and t.text in ")]}":
            depth -= 1
        if t.text == "," and depth == 0:
            args.append([])
        else:
            args[-1].append(t)
    return [a for a in args if a] if any(args) else []


def _number(tokens: list[_Token]) -> float | None:
    sign = 1.0
    while tokens and tokens[0].text in ("-", "+"):
        sign = -sign if tokens[0].text == "-" else sign
        tokens = tokens[1:]
    if len(tokens) != 1 or tokens[0].kind != "num":
        return None
    text = tokens[0].text.replace("'", "").rstrip("fFlL")
    try:
        return sign * float(text)
    except ValueError:
        return None


def _is_true(tokens: list[_Token]) -> bool:
    return [t.text for t in tokens] == ["true"]


# --- the switch -------------------------------------------------------------------------------

_LABEL = """\
#define VEXSIM_ROUTINE_STR2(x) #x
#define VEXSIM_ROUTINE_STR(x) VEXSIM_ROUTINE_STR2(x)
#define VEXSIM_ROUTINE_NAMED(name) __asm__(VEXSIM_ROUTINE_STR(__USER_LABEL_PREFIX__) name)
"""


def _declaration(routine: Routine, name: str, label: str) -> str:
    """``void name() [noexcept] __asm__(label);`` in the routine's namespaces and linkage."""
    noexcept = " noexcept" if routine.noexcept else ""
    text = f'void {name}(){noexcept} VEXSIM_ROUTINE_NAMED("{label}");'
    if routine.c_linkage:
        return f'extern "C" {text}'
    for scope in reversed(routine.scope):
        text = f"namespace {scope} {{ {text} }}"
    return text


def rename_header(routines: list[Routine]) -> str:
    """Included first by a file that defines ``routines``: their declarations, under the
    names the switch calls them by."""
    lines = [
        f"// Generated by vexsim from {AUTON_HEADER} (vexsim/bridge/routines.py): the",
        "// routines this file defines, under the names vexsim's routine switch calls them by.",
        "#pragma once",
        "#ifdef __cplusplus",
        _LABEL.rstrip("\n"),
    ]
    lines += [_declaration(r, r.base, r.renamed) for r in routines]
    lines.append("#endif")
    return "\n".join(lines) + "\n"


def switch_source(routines: list[Routine]) -> str:
    """The switch: a function with each routine's own name, which runs that routine or,
    the first time one is called in the autonomous period, the one ``VEXSIM_ROUTINE``
    names."""
    lines = [
        f"// Generated by vexsim from {AUTON_HEADER} (vexsim/bridge/routines.py): each routine's",
        "// own name runs it, except the first one called in the autonomous period while",
        f"// {ENV} names a routine, which runs that one instead.",
        "#include <cstdint>",
        "#include <cstdio>",
        "#include <cstdlib>",
        "#include <cstring>",
        "",
        'extern "C" std::uint8_t competition_is_autonomous(void);',
        _LABEL,
        "// the project's own routines, as the files that define them name them",
    ]
    lines += [_declaration(r, f"vexsim_real_{i}", r.renamed) for i, r in enumerate(routines)]
    entries = ",\n".join(
        f'    {{"{r.name}", {"::".join([*([] if r.c_linkage else r.scope), f"vexsim_real_{i}"])}}}'
        for i, r in enumerate(routines)
    )
    lines += [
        "",
        "namespace {",
        "",
        "struct Entry {",
        "    const char* name;",
        "    void (*run)();",
        "};",
        "",
        "const Entry routines[] = {",
        entries,
        "};",
        "constexpr int COUNT = sizeof(routines) / sizeof(routines[0]);",
        "int picked = -2;  // -2: not looked up yet; -1: none",
        "bool switched = false;",
        "",
        "void route(int called) {",
        "    if (picked == -2) {",
        "        picked = -1;",
        f'        const char* want = std::getenv("{ENV}");',
        "        if (want && *want) {",
        "            for (int k = 0; k < COUNT; k++)",
        "                if (std::strcmp(routines[k].name, want) == 0) picked = k;",
        "            if (picked < 0)",
        "                std::printf(",
        f'                    "vexsim: there\'s no routine %s() in {AUTON_HEADER}\\n", want);',
        "        }",
        "    }",
        "    if (picked >= 0 && !switched && competition_is_autonomous()) {",
        "        switched = true;",
        "        if (picked == called)",
        f'            std::printf("{NOTE}%s(), the routine picked\\n", routines[called].name);',
        "        else",
        f'            std::printf("{NOTE}%s(); running %s() instead\\n",',
        "                        routines[called].name, routines[picked].name);",
        "        std::fflush(stdout);",
        "        routines[picked].run();",
        "        return;",
        "    }",
        "    routines[called].run();",
        "}",
        "",
        "}  // namespace",
        "",
        "// the routines' own names",
    ]
    for i, r in enumerate(routines):
        body = f"void {r.base}(){' noexcept' if r.noexcept else ''} {{ route({i}); }}"
        if r.c_linkage:
            lines.append(f'extern "C" {body}')
            continue
        for scope in reversed(r.scope):
            body = f"namespace {scope} {{ {body} }}"
        lines.append(body)
    return "\n".join(lines) + "\n"

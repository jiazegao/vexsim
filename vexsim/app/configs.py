"""Robot and field configs as the browser's editors see them.

The YAML text stays the source of truth. ``check_text`` validates it as it's typed and
places each issue at its line; ``patch_text`` changes numbers in place, so a drag on the
editor's diagram rewrites one number (or adds one missing key) and leaves the rest of the
file, comments and layout included, exactly as it was. Both find their way through the
document with PyYAML's node positions (``yaml.compose``).
"""

from __future__ import annotations

import codecs
import hashlib
import math
import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from vexsim.config.field import FieldConfig
from vexsim.config.issues import ConfigIssue
from vexsim.config.robot import RobotConfig

ConfigKind = Literal["robot", "field"]
Path_ = list[str | int]  # "drivetrain.wheels[2].pos_in" as ["drivetrain", "wheels", 2, "pos_in"]

# a key, a list index, or a key with dots in it, quoted: overrides["wheel.omni.lateral_mu"]
_TOKEN = re.compile(r'([^.\[\]"]+)|\[(\d+)\]|\["([^"]+)"\]')
_MERGE = "<<"
DECIMALS = 4  # numbers written by a drag: 0.0001 in, 0.0001 deg


class PatchError(ValueError):
    """A change that can't be made in place (the message says why)."""


@dataclass(frozen=True)
class Span:
    """Where a node's text is: 1-based lines and columns, the end just past its last
    character."""

    line: int
    column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class LocatedIssue:
    severity: str
    location: str
    message: str
    span: Span | None  # None: about the whole document


@dataclass
class CheckedConfig:
    issues: list[LocatedIssue]
    config: RobotConfig | FieldConfig | None  # None: it doesn't parse into the schema
    summary: list[str] = field(default_factory=list)  # as `vexsim validate-config` prints it
    places: dict[str, Span] = field(default_factory=dict)  # where each drawn item is written


@dataclass(frozen=True)
class Edit:
    location: str  # "sensors[1].pos_in", "sensors[1].heading_deg", ...
    value: float | list[float]


# --- reading ---------------------------------------------------------------------------------


def parse_location(location: str) -> Path_:
    return [
        int(index) if index else name or quoted for name, index, quoted in _TOKEN.findall(location)
    ]


class _Composer(yaml.SafeLoader):
    """Composes a document's nodes, noting the shared ones: anchored, or reached through an
    alias. Changing one of those in place would change it everywhere it's used."""

    def __init__(self, stream: str):
        super().__init__(stream)
        self.shared: set[int] = set()

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            node = super().compose_node(parent, index)
            self.shared.add(id(node))
            return node
        anchored = getattr(self.peek_event(), "anchor", None) is not None
        node = super().compose_node(parent, index)
        if anchored:
            self.shared.add(id(node))
        return node


def _compose(text: str) -> tuple[Node | None, set[int]]:
    loader = _Composer(text)
    try:
        return loader.get_single_node(), loader.shared
    finally:
        loader.dispose()


@dataclass
class _Found:
    chain: list[Node]  # the nodes along the path, from the document's root
    missing: Path_  # the end of the path that isn't in the document
    merged: bool = False  # it came in through a merge key (<<)


def _walk(root: Node, path: Path_) -> _Found:
    found = _Found([root], [])
    node, rest = root, list(path)
    while rest:
        step = _step(node, rest)
        if step is None:
            break
        node, used, merged = step
        found.chain.append(node)
        found.merged = found.merged or merged
        rest = rest[used:]
    found.missing = rest
    return found


def _step(node: Node, rest: Path_) -> tuple[Node, int, bool] | None:
    """The child the start of ``rest`` names, how many of its parts that took, and whether
    it came in through a merge key; None if there's no such child."""
    head = rest[0]
    if isinstance(node, SequenceNode):
        if isinstance(head, int) and 0 <= head < len(node.value):
            return node.value[head], 1, False
        return None
    if not isinstance(node, MappingNode):
        return None
    # a key may have dots in it (overrides: {wheel.omni.lateral_mu: ...}): the longest wins
    for used in range(len(rest), 0, -1):
        if not all(isinstance(part, str) for part in rest[:used]):
            continue
        key = ".".join(str(part) for part in rest[:used])
        for key_node, value_node in node.value:
            if isinstance(key_node, ScalarNode) and key_node.value == key:
                return value_node, used, False
    for key_node, value_node in node.value:
        if isinstance(key_node, ScalarNode) and key_node.value == _MERGE:
            sources = value_node.value if isinstance(value_node, SequenceNode) else [value_node]
            for source in sources:
                step = _step(source, rest)
                if step is not None:
                    return step[0], step[1], True
    return None


def _span(node: Node, text: str) -> Span:
    """The node's text; a block collection's first line only (it runs on until whatever
    comes next)."""
    start, end = node.start_mark, node.end_mark
    if isinstance(node, MappingNode | SequenceNode) and not node.flow_style:
        line_end = text.find("\n", start.index)
        line_end = len(text) if line_end < 0 else line_end
        if line_end > start.index and text[line_end - 1] == "\r":
            line_end -= 1
        return Span(
            start.line + 1,
            start.column + 1,
            start.line + 1,
            start.column + 1 + line_end - start.index,
        )
    return Span(start.line + 1, start.column + 1, end.line + 1, end.column + 1)


def locate(root: Node | None, location: str, text: str, exact: bool = False) -> Span | None:
    """Where an issue's dotted location is written: the node itself, or (unless ``exact``)
    the nearest enclosing one when the end of the path is missing (a required key, say)."""
    if root is None or not location:
        return None
    found = _walk(root, parse_location(location))
    node = found.chain[-1]
    if node is root or exact and found.missing:
        return None
    return _span(node, text)


def kind_of(text: str) -> ConfigKind | None:
    """Robot or field, by its keys (as the workspace tells them apart); None if neither."""
    try:
        data = yaml.load(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        data = None
    if isinstance(data, Mapping):
        if "drivetrain" in data or "body" in data:
            return "robot"
        if "size_in" in data or "elements" in data:
            return "field"
        return None
    # unreadable: guess from its top-level keys, so it can be opened and fixed
    if re.search(r"^(drivetrain|body)\s*:", text, re.MULTILINE):
        return "robot"
    if re.search(r"^(size_in|elements)\s*:", text, re.MULTILINE):
        return "field"
    return None


def check_text(text: str, kind: ConfigKind) -> CheckedConfig:
    """Validate a config's text as ``vexsim validate-config`` would, with each issue at its
    place in the text."""
    from vexsim.config.loader import validate_field, validate_robot
    from vexsim.config.summary import field_summary, robot_summary
    from vexsim.config.yaml_io import parse_yaml

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
        return CheckedConfig([LocatedIssue("error", "", problem, span)], None)
    except yaml.YAMLError as exc:
        return CheckedConfig([LocatedIssue("error", "", f"invalid YAML: {exc}", None)], None)
    if data is None:
        return CheckedConfig([LocatedIssue("error", "", "the file is empty", None)], None)
    if not isinstance(data, Mapping):
        message = "the top level of the file must be a mapping of keys"
        return CheckedConfig([LocatedIssue("error", "", message, None)], None)

    report = validate_robot(data) if kind == "robot" else validate_field(data)
    issues = [_located(issue, root, text) for issue in report.issues]
    config = report.config
    if config is None:
        return CheckedConfig(issues, None)
    if isinstance(config, RobotConfig):
        summary = robot_summary(config)
        items = [f"drivetrain.wheels[{i}]" for i in range(len(config.drivetrain.wheels))]
        items += [f"sensors[{i}]" for i in range(len(config.sensors))]
        items += ["body.footprint_in", "body.cg_in"]
        items += [f"body.shape[{i}]" for i in range(len(config.body.shape or ()))]
    else:
        summary = field_summary(config)
        items = [f"elements[{i}]" for i in range(len(config.elements))] + ["size_in"]
    places = {item: span for item in items if (span := locate(root, item, text, True)) is not None}
    return CheckedConfig(issues, config, summary, places)


def _located(issue: ConfigIssue, root: Node | None, text: str) -> LocatedIssue:
    return LocatedIssue(
        issue.severity, issue.location, issue.message, locate(root, issue.location, text)
    )


# --- changing numbers in place ---------------------------------------------------------------


def format_number(value: float) -> str:
    """A number as a drag writes it: up to DECIMALS places, no trailing zeros."""
    if not math.isfinite(value):
        raise PatchError(f"{value} isn't a number a config can hold")
    text = f"{value:.{DECIMALS}f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def patch_text(text: str, edits: list[Edit]) -> str:
    """``text`` with each edit's number(s) rewritten where they are, or its key added to the
    mapping it belongs in (at the end, in the mapping's own style). Numbers that don't
    change keep their spelling. Raises PatchError when an edit can't be made in place."""
    try:
        root, shared = _compose(text)
    except yaml.YAMLError:
        raise PatchError("the YAML doesn't read: fix it in the text first") from None
    if root is None:
        raise PatchError("the file is empty")
    changes: list[tuple[int, int, str]] = []
    for edit in edits:
        found = _walk(root, parse_location(edit.location))
        if found.merged or any(id(node) in shared for node in found.chain):
            raise PatchError(
                f"{edit.location} comes from an anchor, an alias or a merge (<<): change it "
                "in the text, where it's written"
            )
        if found.missing:
            changes.append(_insertion(text, found, edit))
            continue
        node = found.chain[-1]
        values = edit.value if isinstance(edit.value, list) else [edit.value]
        targets = node.value if isinstance(edit.value, list) else [node]
        if isinstance(edit.value, list) != isinstance(node, SequenceNode) or len(targets) != len(
            values
        ):
            raise PatchError(f"{edit.location} isn't written as {_shape(edit.value)}")
        for target, value in zip(targets, values, strict=True):
            if not isinstance(target, ScalarNode) or target.style in ("|", ">"):
                raise PatchError(f"{edit.location} isn't written as plain numbers")
            if _same(target, value):
                continue
            changes.append((target.start_mark.index, target.end_mark.index, format_number(value)))
    changes.sort(key=lambda change: change[0], reverse=True)
    patched, limit = text, len(text)
    for start, end, new in changes:
        if end > limit:
            raise PatchError("two edits change the same text")
        patched = patched[:start] + new + patched[end:]
        limit = start
    return patched


def _shape(value: float | list[float]) -> str:
    return f"a list of {len(value)} numbers" if isinstance(value, list) else "one number"


def _same(node: ScalarNode, value: float) -> bool:
    """Whether a number already says ``value`` (one the editor read from it, unchanged)."""
    try:
        written = float(node.value)
    except ValueError:
        return False
    return abs(written - value) <= 1e-9 * max(1.0, abs(value))


def set_overrides(text: str, values: dict[str, float]) -> str:
    """A robot config's ``text`` with each of ``values`` under its ``overrides`` (a
    calibration's fitted parameters): changed where the key is written, added to the
    mapping where it isn't, and the mapping added at the end when there's none. Raises
    PatchError."""
    try:
        root, shared = _compose(text)
    except yaml.YAMLError:
        raise PatchError("the YAML doesn't read: fix it in the text first") from None
    if not isinstance(root, MappingNode):
        raise PatchError("a robot config is a mapping of keys")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = [f"  {name}: {format_override(value)}" for name, value in values.items()]
    node = next(
        (v for k, v in root.value if isinstance(k, ScalarNode) and k.value == "overrides"), None
    )
    if node is None:  # a new mapping, at the end
        end = len(text.rstrip("\r\n"))
        return text[:end] + newline + newline.join(["overrides:", *lines]) + newline
    if id(node) in shared:
        raise PatchError("overrides comes from an anchor or an alias: change it in the text")
    if isinstance(node, ScalarNode) and node.tag.endswith(":null"):  # `overrides:`, empty
        key = next(k for k, v in root.value if v is node)
        indent = " " * key.start_mark.column
        line_end = _line_end(text, key.end_mark.index)
        if text[key.end_mark.index : line_end].split("#")[0].strip(" :~") not in ("", "null"):
            raise PatchError("overrides isn't a mapping")
        written = "".join(newline + indent + line for line in lines)
        return text[: key.end_mark.index] + ":" + written + text[line_end:]
    if not isinstance(node, MappingNode):
        raise PatchError("overrides isn't a mapping")
    if node.flow_style and not node.value:  # `overrides: {}`
        pairs = ", ".join(line.strip() for line in lines)
        return text[: node.start_mark.index] + "{" + pairs + "}" + text[node.end_mark.index :]
    changes: list[tuple[int, int, str]] = []
    for name, value in values.items():
        present = next(
            (v for k, v in node.value if isinstance(k, ScalarNode) and k.value == name), None
        )
        if present is None:
            edit = Edit(f"overrides.{name}", value)
            changes.append(_insertion(text, _Found([root, node], [name]), edit, format_override))
        elif not isinstance(present, ScalarNode) or id(present) in shared:
            raise PatchError(f"overrides.{name} isn't written as a plain number")
        elif not _same(present, value):
            changes.append(
                (present.start_mark.index, present.end_mark.index, format_override(value))
            )
    # from the end back; added keys keep their order at the same place
    order = sorted(range(len(changes)), key=lambda i: (changes[i][0], i), reverse=True)
    for i in order:
        start, end, new = changes[i]
        text = text[:start] + new + text[end:]
    return text


def format_override(value: float) -> str:
    """A fitted value as ``vexsim calibrate`` prints it: six significant digits."""
    if not math.isfinite(value):
        raise PatchError(f"{value} isn't a number a config can hold")
    text = f"{value:g}"
    if "e" in text and "." not in text:  # YAML reads 1e-05 as text, 1.0e-05 as a number
        text = text.replace("e", ".0e")
    return text


def _insertion(
    text: str, found: _Found, edit: Edit, number: Callable[[float], str] | None = None
) -> tuple[int, int, str]:
    """Where and what to add for an edit whose key isn't in the file yet."""
    parent = found.chain[-1]
    if len(found.missing) != 1 or not isinstance(found.missing[0], str):
        raise PatchError(f"{edit.location} isn't in the file")
    if not isinstance(parent, MappingNode):
        raise PatchError(f"{edit.location} isn't in a mapping")
    key = found.missing[0]
    value = edit.value
    number = number or format_number
    written = (
        "[" + ", ".join(number(v) for v in value) + "]"
        if isinstance(value, list)
        else number(value)
    )
    if parent.flow_style:  # {a: 1, b: 2} -> {a: 1, b: 2, key: value}
        if parent.value:
            at = parent.value[-1][1].end_mark.index
            return at, at, f", {key}: {written}"
        close = text.rindex("}", parent.start_mark.index, parent.end_mark.index)
        return close, close, f"{key}: {written}"
    # a block mapping: a line of its own after its last line, indented as its keys are
    indent = " " * parent.value[0][0].start_mark.column
    newline = "\r\n" if "\r\n" in text else "\n"
    end = _text_end(parent)
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    elif line_end > 0 and text[line_end - 1] == "\r":
        line_end -= 1
    return line_end, line_end, f"{newline}{indent}{key}: {written}"


def _line_end(text: str, index: int) -> int:
    """Where the line with ``index`` on it ends (before its line break)."""
    end = text.find("\n", index)
    if end < 0:
        return len(text)
    return end - 1 if end > 0 and text[end - 1] == "\r" else end


def _text_end(node: Node) -> int:
    """Just past the last character a node's own text takes (a block collection's end mark
    is where the next token starts, which can be lines later)."""
    if isinstance(node, ScalarNode) or getattr(node, "flow_style", False) or not node.value:
        return node.end_mark.index
    last = node.value[-1]
    return _text_end(last[1] if isinstance(node, MappingNode) else last)


# --- files -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigText:
    text: str  # with "\n" line endings, as the editor holds it
    version: str  # of the bytes on disk, to notice changes made elsewhere
    crlf: bool  # the file's lines end in "\r\n"
    bom: bool  # it starts with a UTF-8 byte order mark


def version_of(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def read_config(path: Path) -> ConfigText:
    raw = path.read_bytes()
    bom = raw.startswith(codecs.BOM_UTF8)
    text = raw.decode("utf-8-sig" if bom else "utf-8")
    return ConfigText(text.replace("\r\n", "\n"), version_of(raw), "\r\n" in text, bom)


def write_config(path: Path, text: str, like: ConfigText | None) -> str:
    """Write the editor's text in the file's own line endings (and byte order mark); the
    new version."""
    text = text.replace("\r\n", "\n")
    if like is not None and like.crlf:
        text = text.replace("\n", "\r\n")
    raw = (codecs.BOM_UTF8 if like is not None and like.bom else b"") + text.encode("utf-8")
    temporary = path.with_name(f".{path.name}.vexsim-saving")
    temporary.write_bytes(raw)
    if path.exists():
        shutil.copymode(path, temporary)
    temporary.replace(path)
    return version_of(raw)


def config_json(config: RobotConfig | FieldConfig | None) -> dict[str, Any] | None:
    return None if config is None else config.model_dump(mode="json")

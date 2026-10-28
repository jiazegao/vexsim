"""Changes to a config's YAML text that keep everything else as it was.

The Design view edits a robot through forms and drawing tools, but the YAML text stays the
source of truth. Each change here rewrites only the text it's about: a value set where it's
written (a missing key added to its mapping), an item added at the end of its list, an item
or a key removed with its own lines, a key renamed. New text takes its neighbours' style
(flow ``{...}`` items in a list of flow items, block ones among block ones, their
indentation), and every comment and blank line elsewhere stays where it was.

Numbers dragged on the diagram go through ``configs.patch_text``; ``apply`` takes both.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from vexsim.app.configs import (
    Edit,
    PatchError,
    _compose,
    _Found,
    _line_end,
    _text_end,
    _walk,
    parse_location,
    patch_text,
)
from vexsim.config.yaml_io import parse_yaml

Op = Literal["set", "add", "remove", "rename", "insert", "move"]
INDENT = 2  # for blocks that have no neighbours to copy


@dataclass(frozen=True)
class Change:
    """``set`` a value (a word, a number, a list or a mapping) at ``location``, adding the
    key if it's missing; ``add`` it to the end of the list there (making the list if there's
    none); ``remove`` the list item or the key there; ``rename`` the key there to it;
    ``insert`` it as the list item at ``location`` (``steps[2]``: before the item there, and
    the comments just above it); ``move`` the list item there to the place it says (an
    index), its text, comments and all, as it was."""

    op: Op
    location: str
    value: Any = None


def apply(text: str, edits: Sequence[Edit | Change]) -> str:
    """``text`` with the edits made in order: a run of numbers (as a drag writes them)
    together, each other change on the text the ones before it left. Raises PatchError."""
    numbers: list[Edit] = []
    for edit in [*edits, None]:
        if isinstance(edit, Edit):
            numbers.append(edit)
            continue
        if numbers:
            text = patch_text(text, numbers)
            numbers = []
        if edit is not None:
            text = change(text, edit)
    return text


def change(text: str, edit: Change) -> str:
    """``text`` with one change made."""
    try:
        root, shared = _compose(text)
    except yaml.YAMLError:
        raise PatchError("the YAML doesn't read: fix it in the text first") from None
    if not isinstance(root, MappingNode):
        raise PatchError("a config is a mapping of keys")
    path = parse_location(edit.location)
    if not path:
        raise PatchError("say where the change goes")
    if edit.op in ("insert", "move"):
        if not isinstance(path[-1], int):
            raise PatchError(f"{edit.location} isn't a place in a list")
        listed = _walk(root, path[:-1])
        if listed.merged or any(id(node) in shared for node in listed.chain):
            raise PatchError(
                f"{edit.location} comes from an anchor, an alias or a merge (<<): change it in "
                "the text, where it's written"
            )
        doc = _Doc(text)
        if edit.op == "insert":
            return doc.insert(listed, path[-1], edit.value, edit.location)
        return doc.move(listed, path[-1], edit.value, edit.location)
    found = _walk(root, path)
    if found.merged or any(id(node) in shared for node in found.chain):
        raise PatchError(
            f"{edit.location} comes from an anchor, an alias or a merge (<<): change it in "
            "the text, where it's written"
        )
    doc = _Doc(text)
    if edit.op == "set":
        return doc.set(found, edit.value, edit.location)
    if edit.op == "add":
        return doc.add(found, edit.value, edit.location)
    if found.missing:
        raise PatchError(f"{edit.location} isn't in the file")
    if edit.op == "remove":
        return doc.remove(found, path, edit.location)
    if edit.op == "rename":
        return doc.rename(found, path, edit.value, edit.location)
    raise PatchError(f"unknown change {edit.op!r}")


class _Doc:
    """One text and the changes to it: each returns the changed text."""

    def __init__(self, text: str):
        self.text = text
        self.newline = "\r\n" if "\r\n" in text else "\n"

    # --- set ---------------------------------------------------------------------------------

    def set(self, found: _Found, value: Any, location: str) -> str:
        if found.missing:
            parent = found.chain[-1]
            head, *rest = found.missing
            for step in reversed(rest):  # what's missing below the first missing key
                if not isinstance(step, str):
                    raise PatchError(f"{location} isn't in the file")
                value = {step: value}
            if isinstance(parent, SequenceNode) and head == len(parent.value) and not rest:
                return self._append(parent, value, None)
            if not isinstance(head, str):
                raise PatchError(f"{location} isn't in the file")
            empty = isinstance(parent, MappingNode) and parent.flow_style and not parent.value
            if (_is_null(parent) or empty) and len(found.chain) > 1:  # `mechanisms:` or `{}`
                holder = found.chain[-2]
                return self._replace_value(holder, _key_of(holder, parent), parent, {head: value})
            if not isinstance(parent, MappingNode):
                raise PatchError(f"{location} isn't in the file")
            return self._insert_key(parent, head, value)
        node = found.chain[-1]
        parent = found.chain[-2] if len(found.chain) > 1 else None
        key = _key_of(parent, node)
        if isinstance(node, ScalarNode) and not _is_null(node) and _scalar(value):
            if _same_value(node, value):
                return self.text
            return self._replace(node.start_mark.index, node.end_mark.index, _word(value, node))
        return self._replace_value(parent, key, node, value)

    def _replace_value(self, parent, key: Node | None, node: Node, value: Any) -> str:
        """A key's (or a list item's) value replaced, in the old one's style. A comment on
        the key's line stays on it."""
        inline = _scalar(value) or _flowing(value, node) or bool(getattr(parent, "flow_style", 0))
        written = _word(value) if _scalar(value) else _flow(value) if inline else ""
        end = _text_end(node)
        if key is None:  # a list item (or the document)
            if inline:
                return self._replace(node.start_mark.index, end, written)
            body = _block(value, node.start_mark.column, node, self.newline)
            return self._replace(node.start_mark.index, end, body)
        after = self._after_key(key)
        below = not isinstance(node, ScalarNode) and not node.flow_style
        below = below and node.start_mark.line > key.start_mark.line
        if not below:  # `key: old  # comment`, or `key:` with nothing after it
            if inline:
                return self._replace(after, end, " " + written)
            indent = key.start_mark.column + _step_of(parent, None)
            body = _block(value, indent, node, self.newline)
            comment_end = _line_end(self.text, end)
            rest = self.text[end:comment_end]
            if rest.strip():  # a comment: it stays where it was
                rest = " " * (end - after) + rest
            return (
                self.text[:after]
                + rest
                + self.newline
                + " " * indent
                + body
                + self.text[comment_end:]
            )
        if inline:  # a block becomes `key: [...]`, before the key's comment (where it was)
            comment = self.text[after : _line_end(self.text, after)]
            pad = len(comment) - len(comment.lstrip(" "))
            keep = max(min(pad, 2), pad - len(written) - 1)
            tail = " " * keep + comment.lstrip(" ") if comment.strip() else ""
            return self.text[:after] + " " + written + tail + self.text[_line_end(self.text, end) :]
        body = _block(value, node.start_mark.column, node, self.newline)
        return self._replace(node.start_mark.index, end, body)

    def _insert_key(self, mapping: MappingNode, key: str, value: Any) -> str:
        """``key: value`` added at the end of a mapping, in its own style."""
        name = _word(key)
        if mapping.flow_style or not mapping.value:
            if not mapping.flow_style:
                raise PatchError("can't add to an empty block mapping")
            written = f"{name}: {_flow(value) if not _scalar(value) else _word(value)}"
            if mapping.value:
                at = _text_end(mapping.value[-1][1])
                return self._replace(at, at, ", " + written)
            close = self.text.rindex("}", mapping.start_mark.index, mapping.end_mark.index)
            return self._replace(close, close, written)
        indent = mapping.value[0][0].start_mark.column
        like = _sibling(mapping, value)
        gap = ""
        if _scalar(value) or _flowing(value, like):
            line = f"{name}: {_word(value) if _scalar(value) else _flow(value)}"
        else:
            inner = indent + _step_of(mapping, like)
            body = _block(value, inner, like, self.newline)
            line = f"{name}:{self.newline}{' ' * inner}{body}"
            if indent == 0 and self._spaced(mapping.value[-1][0]):  # sections apart: so is it
                gap = self.newline
        at = _line_end(self.text, _text_end(mapping))
        return self._replace(at, at, f"{self.newline}{gap}{' ' * indent}{line}")

    # --- add ---------------------------------------------------------------------------------

    def add(self, found: _Found, value: Any, location: str) -> str:
        if found.missing:  # no list yet: one with this item
            return self.set(found, [value], location)
        node = found.chain[-1]
        parent = found.chain[-2] if len(found.chain) > 1 else None
        if isinstance(node, ScalarNode) and _is_null(node):  # `sensors:`, nothing after it
            return self._replace_value(parent, _key_of(parent, node), node, [value])
        if not isinstance(node, SequenceNode):
            raise PatchError(f"{location} isn't a list")
        if not node.value:  # `sensors: []`
            return self._replace_value(parent, _key_of(parent, node), node, [value])
        return self._append(node, value, location)

    def _append(self, sequence: SequenceNode, value: Any, location: str | None) -> str:
        last = sequence.value[-1]
        if sequence.flow_style:
            at = _text_end(last)
            return self._replace(at, at, ", " + (_word(value) if _scalar(value) else _flow(value)))
        dash = _dash(self.text, last)
        if dash is None:
            raise PatchError(f"{location or 'the list'} isn't written one item to a line")
        indent = dash - _line_start(self.text, dash)
        item = _item(value, indent, last, self.newline)
        at = _line_end(self.text, _text_end(last))
        return self._replace(at, at, f"{self.newline}{' ' * indent}- {item}")

    # --- insert and move ---------------------------------------------------------------------

    def insert(self, listed: _Found, index: int, value: Any, location: str) -> str:
        sequence = None if listed.missing else listed.chain[-1]
        count = len(sequence.value) if isinstance(sequence, SequenceNode) else 0
        if not 0 <= index <= count:
            raise PatchError(f"{location} is past the end of its list")
        if index == count:  # at the end, as add puts it
            return self.add(listed, value, location)
        item = sequence.value[index]
        if sequence.flow_style:
            at = item.start_mark.index
            return self._replace(at, at, (_word(value) if _scalar(value) else _flow(value)) + ", ")
        dash = _dash(self.text, item)
        if dash is None:
            raise PatchError(f"{location} isn't written one item to a line")
        indent = dash - _line_start(self.text, dash)
        written = _item(value, indent, item, self.newline)
        at = self._lead(dash)
        return self._replace(at, at, f"{' ' * indent}- {written}{self.newline}")

    def move(self, listed: _Found, index: int, to: Any, location: str) -> str:
        sequence = None if listed.missing else listed.chain[-1]
        if not isinstance(sequence, SequenceNode) or not 0 <= index < len(sequence.value):
            raise PatchError(f"{location} isn't in the file")
        count = len(sequence.value)
        if isinstance(to, bool) or not isinstance(to, int) or not 0 <= to < count:
            raise PatchError(f"{location} can only move to a place in its list (0 to {count - 1})")
        if to == index:
            return self.text
        if sequence.flow_style:
            start, end = sequence.value[0].start_mark.index, _text_end(sequence.value[-1])
            if "\n" in self.text[start:end]:
                raise PatchError(f"{location} is in a list written over lines: move it in the text")
            items = [self.text[i.start_mark.index : _text_end(i)] for i in sequence.value]
            items.insert(to, items.pop(index))
            return self._replace(start, end, ", ".join(items))
        spans = []  # each item's lines, the comments just above it with it: (first, end)
        for item in sequence.value:
            dash = _dash(self.text, item)
            if dash is None:
                raise PatchError(f"{location} is in a list not written one item to a line")
            last = _line_end(self.text, _text_end(item))
            spans.append((self._lead(dash), last))
        text = self.text if self.text.endswith(("\n", "\r")) else self.text + self.newline
        block = [(first, end + len(self.newline)) for first, end in spans]
        moved = text[block[index][0] : block[index][1]]
        rest = text[: block[index][0]] + text[block[index][1] :]
        at = block[to][0] if to < index else block[to][1] - len(moved)
        text = rest[:at] + moved + rest[at:]
        return text if self.text.endswith(("\n", "\r")) else text[: -len(self.newline)]

    def _lead(self, dash: int) -> int:
        """Where a list item's lines begin: its own (``dash`` is on it), or the comment
        lines just above it, which are about it."""
        start = _line_start(self.text, dash)
        while start > 0:
            above = _line_start(self.text, start - 1)
            if not self.text[above : start - 1].strip().startswith("#"):
                break
            start = above
        return start

    # --- remove ------------------------------------------------------------------------------

    def remove(self, found: _Found, path: list, location: str) -> str:
        node = found.chain[-1]
        parent = found.chain[-2] if len(found.chain) > 1 else None
        if isinstance(parent, SequenceNode):
            if len(parent.value) == 1:
                return self._emptied(found, parent, "[]")
            index = next(i for i, item in enumerate(parent.value) if item is node)
            if parent.flow_style:
                return self._remove_flow(parent.value, index)
            dash = _dash(self.text, node)
            if dash is None:
                raise PatchError(f"{location} isn't written on lines of its own")
            return self._remove_lines(dash, _text_end(node), location)
        if isinstance(parent, MappingNode):
            key = _key_of(parent, node)
            if len(parent.value) == 1:
                return self._emptied(found, parent, "{}")
            if parent.flow_style:
                index = next(i for i, (_, v) in enumerate(parent.value) if v is node)
                return self._remove_flow([k for k, _ in parent.value], index, values=parent.value)
            return self._remove_lines(key.start_mark.index, _text_end(node), location)
        raise PatchError(f"{location} can't be removed")

    def _emptied(self, found: _Found, collection: Node, empty: str) -> str:
        """The last item or key gone: its collection written as an empty one (beside its
        key, before the key's comment)."""
        holder = found.chain[-3] if len(found.chain) > 2 else None
        key = _key_of(holder, collection)
        if collection.flow_style or key is None:
            return self._replace(collection.start_mark.index, _text_end(collection), empty)
        return self._replace_value(holder, key, collection, [] if empty == "[]" else {})

    def _remove_flow(self, items: list[Node], index: int, values=None) -> str:
        """An item (or a key and its value) out of a flow collection, with its comma."""
        start = items[index].start_mark.index
        end = _text_end(values[index][1] if values else items[index])
        if index + 1 < len(items):  # up to the next item
            end = items[index + 1].start_mark.index
        else:  # from the end of the item before
            before = values[index - 1][1] if values else items[index - 1]
            start = _text_end(before)
        return self._replace(start, end, "")

    def _remove_lines(self, start: int, end: int, location: str) -> str:
        """The lines from the one ``start`` is on through the one ``end`` is on (comments
        on them too), when nothing else is on them."""
        first = _line_start(self.text, start)
        last = _line_end(self.text, end)
        rest = self.text[end:last].strip()
        if self.text[first:start].strip(" ") or (rest and not rest.startswith("#")):
            raise PatchError(
                f"{location} shares its line with something else: change it in the text"
            )
        after = last + len(self.newline) if self.text.startswith(self.newline, last) else last
        if after == last and first > 0:  # the file's last line: take the break before it
            first -= len(self.newline)
        return self.text[:first] + self.text[after:]

    # --- rename ------------------------------------------------------------------------------

    def rename(self, found: _Found, path: list, name: Any, location: str) -> str:
        parent = found.chain[-2] if len(found.chain) > 1 else None
        if not isinstance(parent, MappingNode) or not isinstance(name, str) or not name:
            raise PatchError(f"{location} isn't a key that can be renamed")
        key = _key_of(parent, found.chain[-1])
        if any(isinstance(k, ScalarNode) and k.value == name for k, _ in parent.value):
            raise PatchError(f"there's already a {name!r} there")
        return self._replace(key.start_mark.index, key.end_mark.index, _word(name))

    # --- text --------------------------------------------------------------------------------

    def _replace(self, start: int, end: int, new: str) -> str:
        return self.text[:start] + new + self.text[end:]

    def _spaced(self, key: Node) -> bool:
        """Whether a blank line comes before this key (or the comments just above it)."""
        lines = self.text[: _line_start(self.text, key.start_mark.index)].splitlines()
        while lines and lines[-1].lstrip().startswith("#"):
            lines.pop()
        return bool(lines) and not lines[-1].strip()

    def _after_key(self, key: Node) -> int:
        """Just past the ``:`` after a key."""
        colon = self.text.index(":", key.end_mark.index)
        return colon + 1


# --- helpers -----------------------------------------------------------------------------------


def _key_of(parent: Node | None, node: Node) -> Node | None:
    if isinstance(parent, MappingNode):
        for key, value in parent.value:
            if value is node:
                return key
    return None


def _is_null(node: Node) -> bool:
    return isinstance(node, ScalarNode) and node.tag.endswith(":null")


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _same_value(node: ScalarNode, value: Any) -> bool:
    """Whether a scalar already says ``value`` (one read from it, unchanged)."""
    try:
        written = parse_yaml(f"v: {_source(node)}")["v"]
    except (yaml.YAMLError, TypeError, KeyError):
        return False
    if isinstance(value, bool) or isinstance(written, bool):
        return value is written
    if isinstance(value, int | float) and isinstance(written, int | float):
        return abs(written - value) <= 1e-12 * max(1.0, abs(value))
    return written == value


def _source(node: ScalarNode) -> str:
    """A scalar as written (quotes included)."""
    if node.style in ('"', "'"):
        return json.dumps(node.value)
    return node.value


def _line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def _dash(text: str, item: Node) -> int | None:
    """Where a block list item's ``-`` is: on its line, with only spaces before it."""
    start = _line_start(text, item.start_mark.index)
    before = text[start : item.start_mark.index]
    match = re.fullmatch(r"( *)-( +)", before)
    if not match:
        return None
    return start + len(match.group(1))


def _block_indent(parent: MappingNode, key: Node, node: Node) -> int:
    """How far a block value under ``key`` is indented: as the old one was, or a step in."""
    if not isinstance(node, ScalarNode) and not getattr(node, "flow_style", True):
        if node.start_mark.line > key.start_mark.line:
            return node.start_mark.column
    return key.start_mark.column + INDENT


def _sibling(mapping: MappingNode, value: Any) -> Node | None:
    """A value already in a mapping that's like ``value`` (a mapping for a mapping, a list of
    the same kind of items for a list), to copy the style of: in a mapping of things all
    alike (gear groups, mechanisms), not one of different things (a body, a drivetrain)."""
    if not mapping.value or not all(_alike(node, value) for _, node in mapping.value):
        return None
    return mapping.value[-1][1]


def _alike(node: Node, value: Any) -> bool:
    if isinstance(value, Mapping):
        return isinstance(node, MappingNode) and bool(node.value)
    if isinstance(value, list | tuple):
        if not isinstance(node, SequenceNode) or not node.value:
            return False
        return isinstance(node.value[0], MappingNode) == any(isinstance(v, Mapping) for v in value)
    return False


def _step_of(mapping: MappingNode, like: Node | None) -> int:
    """How much further in than a key its block value goes, as its neighbours do."""
    for key, value in mapping.value:
        if (
            isinstance(value, MappingNode | SequenceNode)
            and not value.flow_style
            and value.start_mark.line > key.start_mark.line
        ):
            step = value.start_mark.column - key.start_mark.column
            return step if step > 0 else INDENT
    return INDENT


# --- writing values ----------------------------------------------------------------------------


def number(value: float | int) -> str:
    """A number as YAML reads it back, as short as it can be."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise PatchError(f"{value} isn't a number a config can hold")
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    text = repr(float(value))
    if "e" in text:  # YAML reads 1e-05 as a word: 1.0e-05 is a number
        mantissa, exponent = text.split("e")
        if "." not in mantissa:
            mantissa += ".0"
        if exponent[0] not in "+-":
            exponent = "+" + exponent
        text = f"{mantissa}e{exponent}"
    return text


def _word(value: Any, like: ScalarNode | None = None) -> str:
    """A scalar as YAML text: plain if it reads back the same everywhere, else quoted (in
    the quotes the old text used, if any)."""
    if value is None:
        return "null"
    if isinstance(value, bool | int | float):
        return number(value)
    text = str(value)
    if like is not None and like.style == "'" and "'" not in text and "\n" not in text:
        return f"'{text}'"
    if like is not None and like.style == '"':
        return json.dumps(text, ensure_ascii=False)
    return text if _plain(text) else json.dumps(text, ensure_ascii=False)


def _plain(text: str) -> bool:
    """Whether a word can go unquoted: it reads back as itself, in a mapping or a flow list,
    with vexsim's loader and with plain YAML (which reads 36:48 as a number)."""
    if not text or text != text.strip() or re.search(r"[\n:,\[\]{}#&*!|>'\"%@`]", text):
        return False  # a word with a colon, a gear ratio, is quoted: YAML 1.1 reads 36:48 as 2208
    if text.startswith(("- ", "? ", "-\t")):
        return False
    for loads in (parse_yaml, yaml.safe_load):
        try:
            if loads(f"k: {text}") != {"k": text} or loads(f"[{text}]") != [text]:
                return False
        except yaml.YAMLError:
            return False
    return True


def _flow(value: Any) -> str:
    """A value written on one line: ``[a, b]``, ``{k: v}``."""
    if _scalar(value):
        return _word(value)
    if isinstance(value, Mapping):
        return "{" + ", ".join(f"{_word(k)}: {_flow(v)}" for k, v in value.items()) + "}"
    return "[" + ", ".join(_flow(v) for v in value) + "]"


def _flowing(value: Any, like: Node | None) -> bool:
    """Whether to write a collection on one line: as the one it replaces or sits beside was,
    or (with nothing to copy) a list of words and numbers, or a mapping with nothing deeper
    than such lists, does."""
    if _scalar(value) or not value:
        return True
    if like is not None and not isinstance(like, ScalarNode) and like.value:
        return bool(like.flow_style)
    return _simple(value)


def _simple(value: Any) -> bool:
    """Whether a value goes on one line by default: no mapping inside it (so a list of
    mappings is a block, one to a line, as is a mapping with a mapping in it)."""
    if _scalar(value):
        return True
    children = value.values() if isinstance(value, Mapping) else value
    return all(not isinstance(c, Mapping) and _simple(c) for c in children)


def _item(value: Any, indent: int, like: Node | None, newline: str) -> str:
    """A list item's text after its ``- ``: as its neighbour ``like`` is written."""
    if _scalar(value) or _flowing(value, like):
        return _word(value) if _scalar(value) else _flow(value)
    return _block(value, indent + 2, like, newline)


def _block(value: Any, indent: int, like: Node | None, newline: str) -> str:
    """A collection written as a block, its first line starting where it's put and the rest
    indented to ``indent``: each part as its counterpart in ``like`` (the old value, or a
    neighbour) is written, or by default."""
    pad = newline + " " * indent
    lines = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            twin = _twin(like, key, child)
            if _scalar(child) or _flowing(child, twin):
                lines.append(f"{_word(key)}: {_word(child) if _scalar(child) else _flow(child)}")
            else:
                inner = indent + INDENT
                body = _block(child, inner, twin, newline)
                lines.append(f"{_word(key)}:{newline}{' ' * inner}{body}")
        return pad.join(lines)
    if isinstance(value, list | tuple):
        for i, child in enumerate(value):
            twin = _nth(like, i)
            lines.append("- " + _item(child, indent, twin, newline))
        return pad.join(lines)
    return _word(value)


def _twin(like: Node | None, key: str, value: Any) -> Node | None:
    """The node for ``key`` in a mapping like this one (or a neighbour like ``value``, for a
    new key)."""
    if not isinstance(like, MappingNode):
        return None
    for k, v in like.value:
        if isinstance(k, ScalarNode) and k.value == key:
            return v
    return _sibling(like, value)


def _nth(like: Node | None, index: int) -> Node | None:
    """List item ``index`` of a list like this one (or its last item, for a new one)."""
    if not isinstance(like, SequenceNode) or not like.value:
        return None
    return like.value[min(index, len(like.value) - 1)]

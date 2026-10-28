"""Copies of the workspace's files, for the app's list (an item's *Duplicate*).

``duplicate`` writes a copy beside the file and never over one. A robot's or field's copy
is renamed in its own text (``name: ... (copy)``), with everything else in it, comments and
line endings too, as it was.
"""

from __future__ import annotations

import codecs
import itertools
from pathlib import Path

import yaml

from vexsim.app.configs import PatchError, read_config
from vexsim.app.yamledit import Change, apply
from vexsim.config.yaml_io import parse_yaml

NAMED = ("robot", "field")  # configs with a name of their own, which their copies change


def duplicate(path: Path, kind: str) -> Path:
    """A copy of the file at ``path`` beside it: ``<stem>_copy<suffix>``, or ``_copy_2``
    and on if that's taken. Returns where it went."""
    if not path.is_file():
        raise PatchError(f"{path.name} isn't a file to copy")
    for n in itertools.count(1):
        number = "" if n == 1 else f"_{n}"
        target = path.with_name(f"{path.stem}_copy{number}{path.suffix}")
        if target.exists():
            continue
        raw = _copied(path, kind, "" if n == 1 else f" {n}")
        try:
            with target.open("xb") as file:
                file.write(raw)
        except FileExistsError:  # made meanwhile: the next name
            continue
        return target
    return path  # never: the names don't run out


def _copied(path: Path, kind: str, number: str) -> bytes:
    """The copy's bytes: the file's, with a robot's or field's name saying it's a copy."""
    raw = path.read_bytes()
    if kind not in NAMED:
        return raw
    read = read_config(path)
    try:
        document = parse_yaml(read.text)
    except yaml.YAMLError:
        return raw
    name = document.get("name") if isinstance(document, dict) else None
    if not isinstance(name, str) or not name.strip():
        return raw
    try:
        text = apply(read.text, [Change("set", "name", f"{name} (copy{number})")])
    except PatchError:  # written through an anchor, say: the copy keeps the name
        return raw
    if read.crlf:
        text = text.replace("\n", "\r\n")
    return (codecs.BOM_UTF8 if read.bom else b"") + text.encode("utf-8")

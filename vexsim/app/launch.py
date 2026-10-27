"""Saved run configurations: the workspace's ``.vexsim/launch.yaml``.

Each one is a named ``RunSpec`` (paths relative to the workspace), so picking one fills in
everything a run takes, its start pose and environment variables included::

    version: 1
    configurations:
      - name: "1239E: Left 40"
        robot: examples/robots/1239e_2026-27.yaml
        program: examples/pros_projects/1239e_2026-27
        field: examples/fields/1239e_2026-27.yaml
        start: [60, 0, 0]
        env: {VEXSIM_AUTON: Left 40}

The browser app reads and writes the file, and people can edit it too; the app writes
it afresh, so comments in it don't survive a save from the app.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import yaml
from pydantic import Field, ValidationError

from vexsim.app.runspec import RunSpec
from vexsim.config.yaml_io import parse_yaml

LAUNCH_FILE = ".vexsim/launch.yaml"
VERSION = 1
HEADER = """\
# Run configurations for `vexsim ui`: pick one in the run bar to fill it in.
# Each takes what `vexsim run` does; paths are relative to the folder vexsim ui opened.
# The app rewrites this file when you save from it (comments here aren't kept).
"""


class RunConfiguration(RunSpec):
    """A named run, kept in the workspace's .vexsim/launch.yaml."""

    name: Annotated[str, Field(min_length=1, max_length=80)]


class LaunchFileError(ValueError):
    """The file exists but can't be used as it is."""


def read_configurations(root: Path) -> list[RunConfiguration]:
    """The workspace's run configurations (none if it has no file); raises
    LaunchFileError when the file is there but broken."""
    path = Path(root) / LAUNCH_FILE
    if not path.is_file():
        return []
    try:
        data = parse_yaml(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise LaunchFileError(f"{LAUNCH_FILE}: {exc}") from None
    if data is None:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("configurations", []), list):
        raise LaunchFileError(f"{LAUNCH_FILE}: expected a list under 'configurations'")
    configurations = []
    for i, item in enumerate(data.get("configurations") or []):
        try:
            configurations.append(RunConfiguration.model_validate(item))
        except ValidationError as exc:
            error = exc.errors()[0]
            where = ".".join(str(part) for part in error["loc"])
            name = item.get("name") if isinstance(item, dict) else None
            label = f"configuration {i + 1}" + (f" ({name})" if name else "")
            raise LaunchFileError(
                f"{LAUNCH_FILE}: {label}: {where + ': ' if where else ''}{error['msg']}"
            ) from None
    _check_names(configurations)
    return configurations


def write_configurations(root: Path, configurations: list[RunConfiguration]) -> Path:
    """Save the run configurations (creating .vexsim/ if needed); returns the file."""
    _check_names(configurations)
    path = Path(root) / LAUNCH_FILE
    data = {"version": VERSION, "configurations": [_plain(c) for c in configurations]}
    text = yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)
    head, *entries = text.split("\n  - name:")  # a blank line between configurations
    text = HEADER + head
    text += "".join(("\n\n" if i else "\n") + "  - name:" + e for i, e in enumerate(entries))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _check_names(configurations: list[RunConfiguration]) -> None:
    seen: set[str] = set()
    for c in configurations:
        key = c.name.strip().casefold()
        if key in seen:
            raise LaunchFileError(f"two run configurations are named {c.name!r}")
        seen.add(key)


class _Inline(list):
    """Written on one line: ``start: [60, 0, 0]``."""


class _InlineMap(dict):
    """Written on one line: ``env: {VEXSIM_AUTON: Left 40}``."""


class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow, False)  # indent lists under their key


_Dumper.add_representer(
    _Inline, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", v, flow_style=True)
)
_Dumper.add_representer(
    _InlineMap, lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", v, flow_style=True)
)


def _plain(configuration: RunConfiguration) -> dict:
    """A configuration as YAML data: its name first, then what differs from the defaults."""
    data = configuration.model_dump(exclude_defaults=True)
    data = {"name": data.pop("name"), **data}
    if "start" in data:
        data["start"] = _Inline(int(v) if float(v).is_integer() else v for v in data["start"])
    if "env" in data:
        data["env"] = _InlineMap(data["env"])
    return data

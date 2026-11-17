"""Robot and field configs in their editors: opened, checked as typed, patched, saved, made new."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import model_validator

from vexsim.config.field import FieldConfig
from vexsim.config.robot import RobotConfig
from vexsim.ui.protocol.base import ConfigKind, _Message


class TextSpan(_Message):
    """Where something is written in a config: 1-based lines and columns, the end just past
    its last character."""

    line: int
    column: int
    end_line: int
    end_column: int


class PlacedIssue(_Message):
    severity: Literal["error", "warning"]
    location: str  # dotted path, as in Issue
    message: str
    span: TextSpan | None  # None: about the whole document


class ConfigCheck(_Message):
    """A config's text, checked as `vexsim validate-config` would: its issues where they're
    written, and when it parses, the config itself (`robot` or `field`), its summary, and
    where each part the editor's diagram draws is written (`sensors[1]`, `elements[3]`)."""

    issues: list[PlacedIssue]
    robot: RobotConfig | None = None
    field: FieldConfig | None = None
    summary: list[str] = []
    places: dict[str, TextSpan] = {}


class ConfigFile(_Message):
    """A robot or field config, opened for editing. `version` is of the bytes on disk."""

    path: str
    kind: ConfigKind
    text: str
    version: str
    check: ConfigCheck


class ConfigCheckRequest(_Message):
    kind: ConfigKind
    text: str


class ConfigEdit(_Message):
    """Write `value` where `location` is: one number, or a list of them (`pos_in`), as a drag
    on the diagram does. With an `op` (the Design view's forms and tools): `set` any value
    there (a word, a number, a list, a mapping; a missing key is added), `add` it to the end
    of the list there, `remove` the item or key there, or `rename` the key there to `value`."""

    location: str
    value: Any = None
    op: Literal["set", "add", "remove", "rename"] | None = None

    @model_validator(mode="after")
    def _numbers(self) -> ConfigEdit:
        if self.op is None:
            numbers = self.value if isinstance(self.value, list) else [self.value]
            if not numbers or not all(
                isinstance(v, int | float) and not isinstance(v, bool) for v in numbers
            ):
                raise ValueError("a drag writes a number, or a list of numbers")
        return self


class ConfigPatchRequest(_Message):
    kind: ConfigKind
    text: str
    edits: list[ConfigEdit]


class ConfigPatched(_Message):
    """The text with the edits made in place (nothing else in it changed), checked."""

    text: str
    check: ConfigCheck


class ConfigSave(_Message):
    """Write a config. `version`: the one it was opened at; the save is refused (409) if
    the file has changed since. None overwrites whatever is there."""

    path: str
    text: str
    version: str | None = None


class ConfigSaved(_Message):
    version: str


class NewRobotRequest(_Message):
    """Make a robot config at `path` (in the workspace; never over a file): a rectangle to
    draw over on a `preset` drivetrain (tank4, tank6, xdrive, mecanum, hdrive), or a copy
    of the robot at `source`, named `name`."""

    path: str
    name: str
    preset: str = "tank4"
    source: str | None = None


class NewRobot(_Message):
    path: str  # in the workspace


class ConfigDriveRequest(_Message):
    """Put a drivetrain preset on a robot config's text: its wheels in the robot's box, its
    motors on free ports. The answer is a ConfigPatched."""

    text: str
    preset: str


class ConfigOverridesRequest(_Message):
    """Set ``overrides`` in a robot config's text (``POST /api/config/overrides``)."""

    text: str
    values: dict[str, float]

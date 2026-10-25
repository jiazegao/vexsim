"""Load and validate robot and field configs from YAML files or mappings."""

from __future__ import annotations

import difflib
import os
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from vexsim.config.checks import check_robot
from vexsim.config.field import FieldConfig
from vexsim.config.issues import ConfigError, ConfigIssue, ValidationReport
from vexsim.config.robot import ROBOT_MODELS, SENSOR_TYPES, RobotConfig
from vexsim.config.yaml_io import load_yaml_file

M = TypeVar("M", bound=BaseModel)
Source = str | os.PathLike[str] | Mapping[str, Any]

_KNOWN_KEYS = sorted(
    {name for model in (*ROBOT_MODELS, FieldConfig) for name in model.model_fields}
)


def validate_robot(source: Source) -> ValidationReport[RobotConfig]:
    return _validate(source, RobotConfig, check_robot)


def load_robot(source: Source) -> RobotConfig:
    """Load a robot config, raising ConfigError if it has any errors."""
    return validate_robot(source).raise_for_errors()


def validate_field(source: Source) -> ValidationReport[FieldConfig]:
    return _validate(source, FieldConfig, None)


def load_field(source: Source | None = None) -> FieldConfig:
    """Load a field config; with no source, return the default empty V5RC field."""
    if source is None:
        return FieldConfig()
    return validate_field(source).raise_for_errors()


def _validate(
    source: Source,
    model: type[M],
    checker: Callable[[M], list[ConfigIssue]] | None,
) -> ValidationReport[M]:
    if isinstance(source, Mapping):
        label, data = "<mapping>", source
    else:
        label = str(source)
        try:
            data = load_yaml_file(source)
        except ConfigError as exc:
            return ValidationReport(label, None, exc.issues)
        if not isinstance(data, Mapping):
            issue = ConfigIssue("error", "", "the top level of the file must be a mapping of keys")
            return ValidationReport(label, None, [issue])

    try:
        config = model.model_validate(data)
    except ValidationError as exc:
        return ValidationReport(label, None, _issues_from_pydantic(exc))
    return ValidationReport(label, config, checker(config) if checker else [])


def _format_location(loc: tuple[Any, ...]) -> str:
    parts = list(loc)
    # Tagged unions insert the tag into the path: sensors.0.imu.port -> sensors[0].port
    if len(parts) > 2 and parts[0] == "sensors" and parts[2] in SENSOR_TYPES:
        del parts[2]
    out = ""
    for part in parts:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out


def _issues_from_pydantic(exc: ValidationError) -> list[ConfigIssue]:
    issues = []
    for err in exc.errors(include_url=False):
        loc = tuple(err["loc"])
        kind = err["type"]
        if kind == "extra_forbidden":
            key = str(loc[-1])
            message = f"unknown key {key!r}"
            close = difflib.get_close_matches(key, _KNOWN_KEYS, n=1)
            if close:
                message += f" (did you mean {close[0]!r}?)"
        elif kind == "missing":
            message = "required key is missing"
        else:
            message = err["msg"].removeprefix("Value error, ")
        issues.append(ConfigIssue("error", _format_location(loc), message))
    return issues

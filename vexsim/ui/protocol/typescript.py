"""The models as TypeScript, for ``frontend/src/protocol.ts``."""

from __future__ import annotations

import types
import typing
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from vexsim.ui.protocol.registry import ALIASES, MODELS


def _ts(annotation: Any, aliases: dict[int, str]) -> str:
    """A Python type as TypeScript."""
    if id(annotation) in aliases:
        return aliases[id(annotation)]
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is type(None) or annotation is None:
        return "null"
    if annotation is str:
        return "string"
    if annotation in (int, float):
        return "number"
    if annotation is bool:
        return "boolean"
    if annotation is Any:
        return "unknown"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation.__name__
    if origin is Annotated:
        return _ts(args[0], aliases)
    if origin is Literal:
        return " | ".join(f'"{a}"' if isinstance(a, str) else str(a).lower() for a in args)
    if origin in (Union, types.UnionType):
        parts: list[str] = []
        for arg in args:
            part = _ts(arg, aliases)
            if part not in parts:
                parts.append(part)
        return " | ".join(parts)
    if origin is list:
        inner = _ts(args[0], aliases)
        return f"({inner})[]" if "|" in inner else f"{inner}[]"
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            inner = _ts(args[0], aliases)
            return f"({inner})[]" if "|" in inner else f"{inner}[]"
        return "[" + ", ".join(_ts(a, aliases) for a in args) + "]"
    if origin is dict:
        return f"Record<string, {_ts(args[1], aliases)}>"
    raise TypeError(f"no TypeScript for {annotation!r}")


def typescript() -> str:
    """``frontend/src/protocol.ts``: the models above as TypeScript types."""
    aliases = {id(value): name for name, value in ALIASES.items()}
    lines = [
        "// Generated from vexsim/ui/protocol.py: python -m vexsim.ui.protocol "
        "frontend/src/protocol.ts",
        "// Don't edit by hand; a test fails when this file is stale.",
        "",
    ]
    declared: dict[int, str] = {}  # an alias can use the ones before it
    for name, value in ALIASES.items():
        lines.append(f"export type {name} = {_ts(value, declared)};")
        declared[id(value)] = name
    lines.append("")
    for model in MODELS:
        doc = (model.__doc__ or "").strip()
        if doc and model.__doc__ is not BaseModel.__doc__:
            lines.append("/** " + " ".join(doc.split()).replace("``", "`") + " */")
        lines.append(f"export interface {model.__name__} {{")
        hints = typing.get_type_hints(model, include_extras=True)
        for name, info in model.model_fields.items():
            optional = "?" if not info.is_required() else ""
            lines.append(f"  {name}{optional}: {_ts(hints[name], aliases)};")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)

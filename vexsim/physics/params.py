"""Model parameter groups and the robot config's dotted ``overrides``.

A key ``group.name`` replaces one scalar field of that group's spec dataclass,
e.g. ``motor.free_current_a: 0.2`` or ``battery.internal_resistance_ohm: 0.15``.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from vexsim.physics.battery import BatterySpec
from vexsim.physics.motor import MotorSpec
from vexsim.physics.thermal import ThermalSpec

PARAM_GROUPS: dict[str, type] = {
    "motor": MotorSpec,
    "thermal": ThermalSpec,
    "battery": BatterySpec,
}
# Groups whose models arrive in later phases: accepted now, applied then.
FUTURE_GROUPS = {"wheel": 3, "chassis": 3, "sensor": 4, "field": 9}


def scalar_fields(group: str) -> list[str]:
    return [f.name for f in dataclasses.fields(PARAM_GROUPS[group]) if f.type in ("float", float)]


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def check_overrides(overrides: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """Return (severity, key, message) for every problem with the given overrides."""
    problems: list[tuple[str, str, str]] = []
    per_group: dict[str, dict[str, Any]] = {}
    for key, value in overrides.items():
        group, _, name = key.partition(".")
        if group in PARAM_GROUPS:
            known = scalar_fields(group)
            if name not in known:
                problems.append(
                    ("error", key, f"unknown {group} parameter; known: {', '.join(known)}")
                )
            elif not _is_number(value):
                problems.append(("error", key, f"must be a number, got {value!r}"))
            else:
                per_group.setdefault(group, {})[name] = value
        elif group in FUTURE_GROUPS:
            problems.append(
                (
                    "warning",
                    key,
                    f"'{group}' parameters take effect in Phase {FUTURE_GROUPS[group]}",
                )
            )
        else:
            groups = ", ".join([*PARAM_GROUPS, *FUTURE_GROUPS])
            problems.append(("error", key, f"unknown parameter group {group!r} (known: {groups})"))

    # Values can be valid one by one yet inconsistent together (e.g. free current above stall).
    for group, values in per_group.items():
        try:
            PARAM_GROUPS[group](**values)
        except ValueError as exc:
            problems.append(("error", f"{group}.*", str(exc)))
    return problems


@dataclass(frozen=True)
class PhysicsParams:
    motor: MotorSpec
    thermal: ThermalSpec
    battery: BatterySpec


def resolve_params(overrides: Mapping[str, Any] | None = None) -> PhysicsParams:
    """Default specs with the matching overrides applied. Raises ValueError on bad overrides."""
    overrides = overrides or {}
    errors = [f"{key}: {msg}" for sev, key, msg in check_overrides(overrides) if sev == "error"]
    if errors:
        raise ValueError("invalid overrides: " + "; ".join(errors))
    values: dict[str, dict[str, Any]] = {group: {} for group in PARAM_GROUPS}
    for key, value in overrides.items():
        group, _, name = key.partition(".")
        if group in PARAM_GROUPS:
            values[group][name] = float(value)
    return PhysicsParams(**{group: cls(**values[group]) for group, cls in PARAM_GROUPS.items()})

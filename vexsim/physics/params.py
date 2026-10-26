"""Model parameter groups and the robot config's dotted ``overrides``.

A key ``<group>.<name>`` replaces one scalar field of that group's spec
dataclass, e.g. ``motor.free_current_a: 0.2``, ``battery.internal_resistance_ohm: 0.15``,
``wheel.omni.lateral_mu: 0.08`` or ``field.wall_restitution: 0.1``. Sensor keys
(``sensor.imu.scale_error``) apply on top of each sensor's noise preset.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from vexsim.devices.specs import SPEC_TYPES
from vexsim.physics.battery import BatterySpec
from vexsim.physics.chassis import ChassisSpec
from vexsim.physics.field import FieldSpec
from vexsim.physics.motor import MotorSpec
from vexsim.physics.thermal import ThermalSpec
from vexsim.physics.wheel import MecanumWheelSpec, OmniWheelSpec, TractionWheelSpec, WheelSpec

PARAM_GROUPS: dict[str, type] = {
    "motor": MotorSpec,
    "thermal": ThermalSpec,
    "battery": BatterySpec,
    "chassis": ChassisSpec,
    "wheel.omni": OmniWheelSpec,
    "wheel.traction": TractionWheelSpec,
    "wheel.mecanum": MecanumWheelSpec,
    "field": FieldSpec,
    **{f"sensor.{kind}": cls for kind, cls in SPEC_TYPES.items()},
}


def scalar_fields(group: str) -> list[str]:
    return [f.name for f in dataclasses.fields(PARAM_GROUPS[group]) if f.type in ("float", float)]


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def check_overrides(overrides: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """Return (severity, key, message) for every problem with the given overrides."""
    problems: list[tuple[str, str, str]] = []
    per_group: dict[str, dict[str, Any]] = {}
    for key, value in overrides.items():
        group, _, name = key.rpartition(".")
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
        else:
            groups = ", ".join(PARAM_GROUPS)
            problems.append(("error", key, f"unknown parameter group (known: {groups})"))

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
    chassis: ChassisSpec
    omni_wheel: OmniWheelSpec
    traction_wheel: TractionWheelSpec
    mecanum_wheel: MecanumWheelSpec
    field: FieldSpec
    sensor_overrides: dict[str, dict[str, float]] = dataclasses.field(default_factory=dict)

    def value(self, key: str) -> float:
        """The value of a dotted parameter key, e.g. ``wheel.omni.lateral_mu``."""
        group, _, name = key.rpartition(".")
        if group not in _FIELD_FOR_GROUP:
            raise KeyError(key)
        return float(getattr(getattr(self, _FIELD_FOR_GROUP[group]), name))

    def wheel(self, wheel_type: str) -> WheelSpec:
        specs = {
            "omni": self.omni_wheel,
            "traction": self.traction_wheel,
            "mecanum": self.mecanum_wheel,
        }
        return specs[wheel_type]


_FIELD_FOR_GROUP = {
    "motor": "motor",
    "thermal": "thermal",
    "battery": "battery",
    "chassis": "chassis",
    "wheel.omni": "omni_wheel",
    "wheel.traction": "traction_wheel",
    "wheel.mecanum": "mecanum_wheel",
    "field": "field",
}


def resolve_params(overrides: Mapping[str, Any] | None = None) -> PhysicsParams:
    """Default specs with the matching overrides applied. Raises ValueError on bad overrides."""
    overrides = overrides or {}
    errors = [f"{key}: {msg}" for sev, key, msg in check_overrides(overrides) if sev == "error"]
    if errors:
        raise ValueError("invalid overrides: " + "; ".join(errors))
    values: dict[str, dict[str, Any]] = {group: {} for group in PARAM_GROUPS}
    for key, value in overrides.items():
        group, _, name = key.rpartition(".")
        if group in PARAM_GROUPS:
            values[group][name] = float(value)
    sensors = {
        group.removeprefix("sensor."): vals
        for group, vals in values.items()
        if group.startswith("sensor.") and vals
    }
    return PhysicsParams(
        **{
            _FIELD_FOR_GROUP[group]: PARAM_GROUPS[group](**values[group])
            for group in _FIELD_FOR_GROUP
        },
        sensor_overrides=sensors,
    )

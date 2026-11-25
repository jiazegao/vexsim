"""A compiled robot's objects as views of its block: the same classes, their numbers
properties over it. ``_adopt`` makes an object one, ``_release`` makes it plain again.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from vexsim.physics.battery import Battery
from vexsim.physics.compiled.layout import CONTACTS, K, M, R
from vexsim.physics.mechanism import Mechanism
from vexsim.physics.motor import BrakeMode, ControlMode, V5Motor
from vexsim.physics.power import PowerSystem
from vexsim.physics.thermal import MotorThermal


def _number(index: int) -> property:
    def get(self):
        return self._v[index]

    def put(self, value) -> None:
        self._v[index] = value

    return property(get, put)


def _flag(index: int) -> property:
    def get(self):
        return self._v[index] != 0.0

    def put(self, value) -> None:
        self._v[index] = 1.0 if value else 0.0

    return property(get, put)


def _choice(index: int, enum: type[Enum]) -> property:
    members = tuple(enum)
    number = {member: float(i) for i, member in enumerate(members)}

    def get(self):
        return members[int(self._v[index])]

    def put(self, value) -> None:
        self._v[index] = number[value]

    return property(get, put)


def _watched(name: str) -> property:
    """An attribute kept as it was, but for telling the step when it's replaced: what it
    says (a spec's constants, which supply) is read again before the next step."""

    def get(self):
        return self.__dict__[name]

    def put(self, value) -> None:
        self.__dict__[name] = value
        self._owner.stale = True

    return property(get, put)


def _column(index: int) -> property:
    """One of the wheels' columns, as a new array each time it's read (as the Python step
    makes new ones each step: one kept from an earlier step doesn't change under its keeper)."""

    def get(self):
        return self._columns[index].copy()

    def put(self, value) -> None:
        column = self._columns[index]
        column[:] = value if len(value) == len(column) else 0.0  # (empty before a first step)

    return property(get, put)


def _view(base: type, numbers: dict[str, int], watched: tuple[str, ...] = (), **more) -> type:
    """``base`` with its numbers in a block: ``numbers`` says where, by attribute."""
    members: dict[str, Any] = {name: _number(index) for name, index in numbers.items()}
    members.update({name: _watched(name) for name in watched})
    members.update(more)
    # what's in the block (the watched ones stay where they were, in the object)
    members["_numbers"] = tuple(n for n in members if n not in watched)
    members["__doc__"] = f"A robot's {base.__name__} with its numbers in the robot's block."
    return type(f"Shared{base.__name__}", (base,), members)


SharedMotor = _view(
    V5Motor,
    {
        "position": M["position"], "velocity": M["velocity"], "current": M["current"],
        "voltage": M["voltage"], "torque": M["torque"], "power_in": M["power_in"],
        "_voltage_cmd": M["voltage_cmd"], "_velocity_cmd": M["velocity_cmd"],
        "_position_cmd": M["position_cmd"], "_max_speed": M["max_speed"],
        "_hold_target": M["hold_target"], "_integral_v": M["integral_v"],
        "_velocity_est": M["velocity_est"], "_accel_est": M["accel_est"],
        "_current_limit": M["current_limit"], "supply_current_cap": M["supply_current_cap"],
    },
    watched=("spec", "core", "thermal", "supply", "ratio", "rated_speed", "gear"),
    current_limited=_flag(M["current_limited"]),
    _mode=_choice(M["mode"], ControlMode),
    _brake_mode=_choice(M["brake_mode"], BrakeMode),
)  # fmt: skip
SharedThermal = _view(
    MotorThermal, {"winding_c": M["winding_c"], "housing_c": M["housing_c"]}, watched=("spec",)
)
SharedPower = _view(
    PowerSystem,
    {
        "_bus_voltage": R["bus_voltage"], "_load_w": R["load_w"],
        "battery_current_a": R["battery_current_a"], "quiescent_current_a": R["quiescent_a"],
    },
    watched=("battery",),
)  # fmt: skip
SharedBattery = _view(
    Battery, {"soc": R["soc"], "charge_used_mah": R["charge_used_mah"]}, watched=("spec",)
)
SharedMechanism = _view(
    Mechanism,
    {name: K[name] for name in ("angle", "speed", "inertia", "load", "friction", "low", "high")},
    watched=("motors",),
)
_shared_contacts: type | None = None


def _contacts_view() -> type:
    global _shared_contacts
    if _shared_contacts is None:
        from vexsim.physics.robot import ContactState

        members = {name: _column(i) for i, name in enumerate(CONTACTS)}
        members["_numbers"] = CONTACTS
        members["__doc__"] = "A robot's ContactState with its arrays in the robot's block."
        _shared_contacts = type("SharedContactState", (ContactState,), members)
    return _shared_contacts


def _adopt(obj: Any, view: type, owner: Any, **where) -> None:
    """Make ``obj`` a view: its numbers go where ``where`` says, its class becomes ``view``.
    ``owner`` is the robot's compiled step, told when something it keeps a copy of is replaced."""
    if type(obj) is view:
        if obj._owner is owner:
            return
        _release(obj)  # another robot's (not that anything shares them)
    values = {name: obj.__dict__.pop(name) for name in view._numbers if name in obj.__dict__}
    obj.__dict__.update(where, _owner=owner)
    obj.__class__ = view
    for name, value in values.items():
        setattr(obj, name, value)


def _release(obj: Any) -> None:
    """A view back to a plain object, holding its numbers as they are now."""
    view = type(obj)
    values = {name: getattr(obj, name) for name in view._numbers}
    obj.__class__ = view.__mro__[1]
    for name in ("_v", "_columns", "_owner"):
        obj.__dict__.pop(name, None)
    obj.__dict__.update(values)

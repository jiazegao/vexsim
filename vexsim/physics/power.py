"""Power delivery from the battery through the brain to the motors.

Each motor reports the electrical power it draws during a step; the power
system turns the total into battery current, discharges the battery, and
publishes the sagged bus voltage for the next step. Using the previous step's
voltage (a 1 ms lag) stands in for the bus capacitance and avoids an
algebraic loop.

The brain shares a 20 A budget once more than 8 motors are plugged in: each
motor's current limit becomes 20 A / N. This is community-reported, not
official; see docs/models.md.
"""

from __future__ import annotations

from typing import Protocol

from vexsim.physics.battery import Battery


class Supply(Protocol):
    @property
    def bus_voltage(self) -> float: ...

    def add_load(self, power_w: float) -> None: ...


class CurrentLimited(Protocol):
    supply: Supply
    supply_current_cap: float


class IdealSupply:
    """A stiff voltage source: no sag, no limit. For tests and dyno measurements."""

    def __init__(self, voltage: float = 12.8):
        self._voltage = voltage
        self.load_w = 0.0

    @property
    def bus_voltage(self) -> float:
        return self._voltage

    def add_load(self, power_w: float) -> None:
        self.load_w += power_w

    def end_step(self, dt: float) -> None:
        self.load_w = 0.0


class PowerSystem:
    def __init__(
        self,
        battery: Battery | None = None,
        *,
        quiescent_current_a: float = 0.3,
        current_budget_a: float = 20.0,
        full_current_motor_count: int = 8,
    ):
        self.battery = battery or Battery()
        self.quiescent_current_a = quiescent_current_a
        self.current_budget_a = current_budget_a
        self.full_current_motor_count = full_current_motor_count
        self.motors: list[CurrentLimited] = []
        self.battery_current_a = quiescent_current_a
        self._bus_voltage = self.battery.terminal_voltage(quiescent_current_a)
        self._load_w = 0.0

    @property
    def bus_voltage(self) -> float:
        return self._bus_voltage

    @property
    def per_motor_current_cap(self) -> float:
        n = len(self.motors)
        if n <= self.full_current_motor_count:
            return float("inf")
        return self.current_budget_a / n

    def attach(self, motor: CurrentLimited) -> None:
        """Plug a motor into the brain; it draws from this supply from now on."""
        motor.supply = self
        self.motors.append(motor)
        cap = self.per_motor_current_cap
        for m in self.motors:
            m.supply_current_cap = cap

    def add_load(self, power_w: float) -> None:
        self._load_w += power_w

    def end_step(self, dt: float) -> None:
        """Settle the step's total draw against the battery. Call once per tick, after motors."""
        # Motors regenerating power can feed others on the bus, but never charge the battery.
        load_w = max(self._load_w, 0.0)
        current = load_w / max(self._bus_voltage, 1e-3) + self.quiescent_current_a
        self.battery.step(current, dt)
        self.battery_current_a = current
        self._bus_voltage = self.battery.terminal_voltage(current)
        self._load_w = 0.0

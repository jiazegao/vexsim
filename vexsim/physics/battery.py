"""V5 robot battery: open-circuit voltage vs. charge, internal resistance, charge counting.

The V5 battery is 1100 mAh at 12.8 V nominal, i.e. four LiFePO4 cells in series.
The open-circuit curve below is a generic LiFePO4 shape scaled to 4 cells, and
the internal resistance (cells + BMS + wiring to the brain) is an estimate.
Both are calibration targets for Phase 10. See docs/models.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BatterySpec:
    capacity_mah: float = 1100.0
    internal_resistance_ohm: float = 0.10
    ocv_soc: tuple[float, ...] = (0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 0.70, 0.90, 1.00)
    ocv_v: tuple[float, ...] = (11.2, 12.2, 12.6, 12.9, 13.0, 13.1, 13.2, 13.3, 13.5)

    def __post_init__(self) -> None:
        if not (math.isfinite(self.capacity_mah) and self.capacity_mah > 0):
            raise ValueError("capacity_mah must be positive")
        if not (math.isfinite(self.internal_resistance_ohm) and self.internal_resistance_ohm >= 0):
            raise ValueError("internal_resistance_ohm must be >= 0")
        soc, volts = np.asarray(self.ocv_soc), np.asarray(self.ocv_v)
        if len(soc) != len(volts) or len(soc) < 2:
            raise ValueError("ocv_soc and ocv_v must be equal-length with >= 2 points")
        if soc[0] != 0.0 or soc[-1] != 1.0 or np.any(np.diff(soc) <= 0):
            raise ValueError("ocv_soc must increase strictly from 0.0 to 1.0")
        if np.any(np.diff(volts) < 0):
            raise ValueError("ocv_v must not decrease with state of charge")


class Battery:
    def __init__(self, spec: BatterySpec | None = None, soc: float = 1.0):
        if not 0.0 <= soc <= 1.0:
            raise ValueError(f"state of charge must be in [0, 1], got {soc}")
        self.spec = spec or BatterySpec()
        self.soc = soc
        self.charge_used_mah = 0.0

    def open_circuit_voltage(self) -> float:
        return float(np.interp(self.soc, self.spec.ocv_soc, self.spec.ocv_v))

    def terminal_voltage(self, current_a: float) -> float:
        return max(0.0, self.open_circuit_voltage() - current_a * self.spec.internal_resistance_ohm)

    def step(self, current_a: float, dt: float) -> None:
        """Discharge by ``current_a`` (>= 0) for ``dt`` seconds. The sim never charges it."""
        drawn_mah = max(current_a, 0.0) * dt / 3.6
        self.charge_used_mah += drawn_mah
        self.soc = max(0.0, self.soc - drawn_mah / self.spec.capacity_mah)

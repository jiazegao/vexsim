"""Lumped two-node thermal model of a V5 motor, with firmware current derating.

Heat (I^2 R) enters the winding node, flows to the housing node (where the
motor's temperature sensor sits, on the PCB), and from there to ambient.
Derating is driven by the housing node, so it lags the winding the way the
real sensor does.

Derating levels follow community reports of V5 firmware behavior: current is
cut to 1/2, 1/4, 1/8, then 0. The onset temperature (~55 C) is forum-observed;
the spacing between levels and every thermal constant are estimates to be
calibrated in Phase 10. See docs/models.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DERATE_FACTORS = (1.0, 0.5, 0.25, 0.125, 0.0)


@dataclass(frozen=True)
class ThermalSpec:
    ambient_c: float = 25.0
    winding_heat_capacity_j_per_k: float = 12.0
    housing_heat_capacity_j_per_k: float = 50.0
    winding_to_housing_k_per_w: float = 1.5
    housing_to_ambient_k_per_w: float = 4.0
    derate_start_c: float = 55.0
    derate_step_c: float = 5.0

    def __post_init__(self) -> None:
        for name in (
            "winding_heat_capacity_j_per_k",
            "housing_heat_capacity_j_per_k",
            "winding_to_housing_k_per_w",
            "housing_to_ambient_k_per_w",
            "derate_step_c",
        ):
            value = getattr(self, name)
            if not (math.isfinite(value) and value > 0):
                raise ValueError(f"{name} must be positive, got {value}")
        if self.derate_start_c <= self.ambient_c:
            raise ValueError("derate_start_c must be above ambient_c")


class MotorThermal:
    def __init__(self, spec: ThermalSpec | None = None, initial_c: float | None = None):
        self.spec = spec or ThermalSpec()
        start = self.spec.ambient_c if initial_c is None else initial_c
        self.winding_c = start
        self.housing_c = start

    def step(self, heat_w: float, dt: float) -> None:
        s = self.spec
        to_housing = (self.winding_c - self.housing_c) / s.winding_to_housing_k_per_w
        to_ambient = (self.housing_c - s.ambient_c) / s.housing_to_ambient_k_per_w
        self.winding_c += (heat_w - to_housing) * dt / s.winding_heat_capacity_j_per_k
        self.housing_c += (to_housing - to_ambient) * dt / s.housing_heat_capacity_j_per_k

    @property
    def derate_level(self) -> int:
        """0 = full current; 1-4 = progressively derated (4 = disabled)."""
        over = self.housing_c - self.spec.derate_start_c
        if over < 0:
            return 0
        return min(len(DERATE_FACTORS) - 1, 1 + int(over // self.spec.derate_step_c))

    @property
    def derate_factor(self) -> float:
        return DERATE_FACTORS[self.derate_level]

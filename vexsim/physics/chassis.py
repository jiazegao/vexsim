"""Chassis parameters and wheel normal loads.

Each wheel sits on a stiff vertical spring (tire plus foam tile compliance)
under a rigid chassis plane. Every step the plane is solved quasi-statically,
so the loads carry the robot's weight and balance the pitch and roll moments
of the previous step's ground forces acting below the center of gravity.
This one model gives weight transfer under acceleration and turning, the
rocking of drop-center drivetrains, and wheel lift-off.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ChassisSpec:
    wheel_stiffness_n_per_m: float = 2.0e4  # tire + foam tile, per wheel (estimate)
    gravity_m_s2: float = 9.81

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if not (math.isfinite(value) and value > 0):
                raise ValueError(f"chassis.{name} must be positive, got {value}")


class NormalLoads:
    """Normal load on each wheel (N) as a function of the horizontal ground force.

    ``pos`` is (n, 2) wheel contact positions relative to the CG, in the body
    frame. ``drop`` lowers individual wheels (m). Pushing the CG forward loads
    the rear wheels: sum(N * x) = -h * Fx, and likewise for y.

    While every wheel touches the ground the loads are linear in the force, so
    that map is precomputed. Lift-off falls back to an active-set solve.
    """

    def __init__(
        self, pos: np.ndarray, drop: np.ndarray, stiffness: float, weight: float, cg_height: float
    ):
        self.pos = np.asarray(pos, dtype=float)
        self.drop = np.asarray(drop, dtype=float)
        self.stiffness = stiffness
        self.weight = weight
        self.cg_height = cg_height
        self._basis = np.column_stack([np.ones(len(self.pos)), self.pos])
        # loads = base + sens @ (fx, fy) when all wheels are in contact
        loads_of = self._solve_active(np.ones(len(self.pos), dtype=bool))
        self._base = loads_of(np.array([weight, 0.0, 0.0]))
        self._sens = np.column_stack(
            [
                loads_of(np.array([weight, -cg_height, 0.0])) - self._base,
                loads_of(np.array([weight, 0.0, -cg_height])) - self._base,
            ]
        )

    def __call__(self, fx: float = 0.0, fy: float = 0.0) -> np.ndarray:
        loads = self._base + self._sens @ (fx, fy)
        if loads.min() >= 0.0:
            return loads
        return self._lift_off(np.array([self.weight, -self.cg_height * fx, -self.cg_height * fy]))

    def _solve_active(self, active: np.ndarray):
        basis, k = self._basis[active], self.stiffness
        system = k * basis.T @ basis
        offset = k * basis.T @ self.drop[active]

        def loads(rhs: np.ndarray) -> np.ndarray:
            # Compression of wheel i: a + b*x_i + c*y_i + drop_i; load = k * compression.
            plane = np.linalg.lstsq(system, rhs - offset, rcond=None)[0]
            return np.where(active, k * (self._basis @ plane + self.drop), 0.0)

        return loads

    def _lift_off(self, rhs: np.ndarray) -> np.ndarray:
        active = np.ones(len(self.pos), dtype=bool)
        loads = np.zeros(len(self.pos))
        for _ in range(len(self.pos)):
            loads = self._solve_active(active)(rhs)
            lifted = active & (loads < 0.0)
            if not lifted.any():
                break
            active &= ~lifted
        loads = np.maximum(loads, 0.0)
        total = loads.sum()
        # Past the tipping point no plane balances the moments; keep the total weight right.
        if total <= 0:
            return np.full(len(self.pos), self.weight / len(self.pos))
        return loads * (self.weight / total)

"""Wheel-ground contact.

Each wheel contributes forces along three channels, each a smoothed Coulomb
friction ``F = coeff * N * tanh(x / x_s)`` of one contact velocity ``x``:

  slip     s = w_wheel * r - v_long   main-wheel traction (along the rolling direction)
  lateral  v_lat                      sideways roller friction (omni rollers roll freely)
  rolling  w_wheel * r                rolling resistance of the tire on foam tiles

On an omni wheel the two directions are mechanically separate (main wheel vs.
rollers), so the channels are independent: an omni wheel rolling sideways on
its rollers keeps its full drive traction. That is how X-drives work.
Traction and mecanum wheels need a coupled friction ellipse and come in Phase 9.

Coefficients are estimates (calibration targets for Phase 10); docs/models.md
describes simple experiments to measure them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OmniWheelSpec:
    longitudinal_mu: float = 0.9  # main wheel on foam tiles (estimate)
    slip_velocity_m_s: float = 0.03  # slip at which traction is ~76% developed
    lateral_mu: float = 0.2  # roller friction when sliding sideways (estimate)
    lateral_velocity_m_s: float = 0.02
    rolling_resistance: float = 0.10  # lumped coast-down losses: foam, bearings, chain (estimate)
    rolling_velocity_m_s: float = 0.02
    mass_kg: float = 0.06  # per wheel, for spin inertia (estimate)

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if not (math.isfinite(value) and value > 0):
                raise ValueError(f"wheel.omni.{name} must be positive, got {value}")

    def channel_coefficients(self) -> tuple[np.ndarray, np.ndarray]:
        """(friction coefficient, velocity scale) for the slip, lateral and rolling channels."""
        coeff = np.array([self.longitudinal_mu, self.lateral_mu, self.rolling_resistance])
        scale = np.array(
            [self.slip_velocity_m_s, self.lateral_velocity_m_s, self.rolling_velocity_m_s]
        )
        return coeff, scale


def smoothed_coulomb(
    x: np.ndarray, limit: np.ndarray, scale: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """``limit * tanh(x / scale)`` and its derivative with respect to x."""
    t = np.tanh(x / scale)
    return limit * t, limit * (1.0 - t * t) / scale

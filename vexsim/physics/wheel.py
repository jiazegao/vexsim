"""Wheel-ground contact.

Each wheel contributes forces along three channels of contact velocity. All
three are smoothed Coulomb friction, ``F = coeff * N * tanh(x / x_s)``:

  slip     s = w_wheel * r * cos(g) - a . v   where the wheel grips (drives the robot)
  free     f . v + w_wheel * r * sin(g)       across it (rollers roll, tires slide)
  rolling  w_wheel * r                        rolling resistance of the tire on foam tiles

``v`` is the ground velocity of the contact point. The grip direction ``a`` is
the rolling direction turned by the roller angle ``g``, and ``f`` is ``a``
turned a further 90 degrees.

Omni wheels have ``g = 0``: the main wheel grips along the rolling direction
and the rollers roll freely across it. The two directions are mechanically
separate, so the channels are independent. An omni wheel rolling sideways on
its rollers keeps its full drive traction, which is how X-drives work.

Mecanum wheels are the same with ``g = +-45 deg``. The ground rollers' axes
point along ``a``, so a mecanum wheel grips there and its rollers roll along
``f``. Driving the wheel pushes the robot along ``a``, diagonally.

Traction wheels grip the same in every direction. Their slip and free
channels share one friction circle, ``F = mu * N * tanh(|c| / x_s) * c / |c|``
with ``c = (slip, free)``. A wheel sliding sideways (turning scrub) loses drive
traction, and a wheel spinning in place loses its sideways grip.

Coefficients are estimates (calibration targets for Phase 10); docs/models.md
describes simple experiments to measure them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def _check_positive(group: str, spec: object) -> None:
    for name, value in vars(spec).items():
        if not (math.isfinite(value) and value > 0):
            raise ValueError(f"{group}.{name} must be positive, got {value}")


@dataclass(frozen=True)
class OmniWheelSpec:
    longitudinal_mu: float = 0.9  # main wheel on foam tiles (estimate)
    slip_velocity_m_s: float = 0.03  # slip at which traction is ~76% developed
    lateral_mu: float = 0.2  # roller friction when sliding sideways (estimate)
    lateral_velocity_m_s: float = 0.02
    rolling_resistance: float = 0.10  # lumped coast-down losses: foam, bearings, chain (estimate)
    rolling_velocity_m_s: float = 0.02
    mass_kg: float = 0.06  # per wheel, for spin inertia (estimate)

    coupled = False  # independent slip and free channels

    def __post_init__(self) -> None:
        _check_positive("wheel.omni", self)

    @property
    def grip_mu(self) -> float:
        return self.longitudinal_mu

    def channel_coefficients(self) -> tuple[np.ndarray, np.ndarray]:
        """(friction coefficient, velocity scale) for the slip, free and rolling channels."""
        coeff = np.array([self.longitudinal_mu, self.lateral_mu, self.rolling_resistance])
        scale = np.array(
            [self.slip_velocity_m_s, self.lateral_velocity_m_s, self.rolling_velocity_m_s]
        )
        return coeff, scale


@dataclass(frozen=True)
class TractionWheelSpec:
    mu: float = 1.1  # rubber tread on foam tiles, the same in every direction (estimate)
    slip_velocity_m_s: float = 0.03
    rolling_resistance: float = 0.12  # a little above omni wheels: more tread deforms (estimate)
    rolling_velocity_m_s: float = 0.02
    mass_kg: float = 0.07  # per wheel (estimate)

    coupled = True  # one friction circle for the slip and free channels

    def __post_init__(self) -> None:
        _check_positive("wheel.traction", self)

    @property
    def grip_mu(self) -> float:
        return self.mu

    def channel_coefficients(self) -> tuple[np.ndarray, np.ndarray]:
        coeff = np.array([self.mu, self.mu, self.rolling_resistance])
        scale = np.array(
            [self.slip_velocity_m_s, self.slip_velocity_m_s, self.rolling_velocity_m_s]
        )
        return coeff, scale


@dataclass(frozen=True)
class MecanumWheelSpec:
    grip_mu: float = 0.8  # roller rubber on tiles, along the roller axes (estimate)
    slip_velocity_m_s: float = 0.03
    roller_mu: float = 0.15  # resistance of the free-turning rollers (estimate)
    roller_velocity_m_s: float = 0.02
    rolling_resistance: float = 0.12
    rolling_velocity_m_s: float = 0.02
    mass_kg: float = 0.15  # per wheel, rollers included (estimate)

    coupled = False

    def __post_init__(self) -> None:
        _check_positive("wheel.mecanum", self)

    def channel_coefficients(self) -> tuple[np.ndarray, np.ndarray]:
        coeff = np.array([self.grip_mu, self.roller_mu, self.rolling_resistance])
        scale = np.array(
            [self.slip_velocity_m_s, self.roller_velocity_m_s, self.rolling_velocity_m_s]
        )
        return coeff, scale


WheelSpec = OmniWheelSpec | TractionWheelSpec | MecanumWheelSpec


def smoothed_coulomb(
    x: np.ndarray, limit: np.ndarray, scale: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """``limit * tanh(x / scale)`` and its derivative with respect to x."""
    t = np.tanh(x / scale)
    return limit * t, limit * (1.0 - t * t) / scale


def friction_circle(
    slip: float, free: float, limit: float, scale: float
) -> tuple[float, float, float, float, float]:
    """Isotropic smoothed Coulomb friction of the 2D slip velocity ``(slip, free)``.

    Returns the two force components and the symmetric 2x2 Jacobian as
    ``(f_slip, f_free, d_ss, d_ff, d_sf)``. Along the slip direction the force
    stiffens like ``tanh``; across it, like ``tanh(r/s) / r``. Both are positive,
    so the block is positive definite.
    """
    speed = math.hypot(slip, free)
    if speed < 1e-9 * scale:
        return limit * slip / scale, limit * free / scale, limit / scale, limit / scale, 0.0
    t = math.tanh(speed / scale)
    along = limit * (1.0 - t * t) / scale  # d|F| / d|c|
    across = limit * t / speed  # |F| / |c|
    ux, uy = slip / speed, free / speed
    return (
        across * slip,
        across * free,
        across + (along - across) * ux * ux,
        across + (along - across) * uy * uy,
        (along - across) * ux * uy,
    )

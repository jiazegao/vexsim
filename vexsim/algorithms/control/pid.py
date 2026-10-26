"""PID with the safeguards VEX motions need, and LemLib-style exit conditions."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PID:
    kp: float
    ki: float = 0.0
    kd: float = 0.0
    integral_zone: float = math.inf  # only integrate when |error| is below this
    reset_integral_on_sign_change: bool = True

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._integral = 0.0
        self._previous: float | None = None

    def update(self, error: float, dt: float) -> float:
        if abs(error) < self.integral_zone:
            self._integral += error * dt
        if (
            self.reset_integral_on_sign_change
            and self._previous is not None
            and math.copysign(1, error) != math.copysign(1, self._previous)
        ):
            self._integral = 0.0
        derivative = 0.0 if self._previous is None else (error - self._previous) / dt
        self._previous = error
        return self.kp * error + self.ki * self._integral + self.kd * derivative


@dataclass
class ExitCondition:
    """Done once |error| stays below ``tolerance`` for ``hold_s`` seconds."""

    tolerance: float
    hold_s: float = 0.1

    def __post_init__(self) -> None:
        self._held = 0.0

    def update(self, error: float, dt: float) -> bool:
        self._held = self._held + dt if abs(error) < self.tolerance else 0.0
        return self._held >= self.hold_s

"""Simulation time, kept as integer microseconds so long runs never drift."""

from __future__ import annotations

US_PER_MS = 1000
US_PER_S = 1_000_000


def _to_us(value: float, scale: int, unit: str) -> int:
    us = round(value * scale)
    if abs(us - value * scale) > 1e-6:
        raise ValueError(f"{value} {unit} is not a whole number of microseconds")
    return us


def ms_to_us(ms: float) -> int:
    return _to_us(ms, US_PER_MS, "ms")


def seconds_to_us(seconds: float) -> int:
    return _to_us(seconds, US_PER_S, "s")


class SimClock:
    __slots__ = ("_us",)

    def __init__(self, start_us: int = 0):
        if start_us < 0:
            raise ValueError("start time must be >= 0")
        self._us = int(start_us)

    @property
    def us(self) -> int:
        return self._us

    @property
    def ms(self) -> float:
        return self._us / US_PER_MS

    @property
    def seconds(self) -> float:
        return self._us / US_PER_S

    def advance(self, dt_us: int) -> None:
        if dt_us <= 0:
            raise ValueError("clock can only move forward")
        self._us += dt_us

    def __repr__(self) -> str:
        return f"SimClock({self._us} us)"

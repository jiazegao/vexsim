"""The fixed-step simulation loop.

One tick at time t:
  1. Fire every event due at t (sensor sampling, controllers, logging), ordered
     by (priority, registration order). Sensors use PRIORITY_SENSOR so a
     controller firing in the same tick sees that tick's fresh readings.
  2. Step every physics system from t to t + dt, in the order they were added.
  3. Advance the clock to t + dt.

Event periods and offsets must be whole multiples of the physics step, so
every event lands exactly on a tick.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from vexsim.core.clock import SimClock, ms_to_us, seconds_to_us
from vexsim.core.events import EventHandle, EventScheduler
from vexsim.core.rng import RngStreams

PRIORITY_SENSOR = -100
PRIORITY_CONTROL = 0
PRIORITY_RECORD = 100


class System(Protocol):
    def step(self, world: World, dt: float) -> None: ...


class World:
    def __init__(self, *, seed: int = 0, dt_ms: float = 1.0):
        self.dt_us = ms_to_us(dt_ms)
        if self.dt_us <= 0:
            raise ValueError("physics step must be positive")
        self.clock = SimClock()
        self.rng = RngStreams(seed)
        self.steps = 0
        self._events = EventScheduler()
        self._systems: list[System] = []
        self._stop_reason: str | None = None

    @property
    def time(self) -> float:
        """Current simulation time in seconds."""
        return self.clock.seconds

    @property
    def dt(self) -> float:
        """Physics step in seconds."""
        return self.dt_us / 1_000_000

    @property
    def stop_reason(self) -> str | None:
        return self._stop_reason

    def add_system(self, system: System) -> System:
        self._systems.append(system)
        return system

    def every(
        self,
        period_ms: float,
        callback: Callable[[World], Any],
        *,
        offset_ms: float = 0,
        priority: int = PRIORITY_CONTROL,
        name: str = "",
    ) -> EventHandle:
        """Call ``callback(world)`` every ``period_ms``, first at now + ``offset_ms``."""
        period_us = self._tick_aligned(period_ms, "period", allow_zero=False)
        offset_us = self._tick_aligned(offset_ms, "offset", allow_zero=True)
        return self._events.schedule_every(
            period_us, callback, start_us=self.clock.us + offset_us, priority=priority, name=name
        )

    def after(
        self,
        delay_ms: float,
        callback: Callable[[World], Any],
        *,
        priority: int = PRIORITY_CONTROL,
        name: str = "",
    ) -> EventHandle:
        """Call ``callback(world)`` once, ``delay_ms`` from now (0 = this tick)."""
        delay_us = self._tick_aligned(delay_ms, "delay", allow_zero=True)
        return self._events.schedule_at(
            self.clock.us + delay_us, callback, priority=priority, name=name
        )

    def step(self) -> None:
        self._events.run_due(self.clock.us, self)
        dt = self.dt
        for system in self._systems:
            system.step(self, dt)
        self.clock.advance(self.dt_us)
        self.steps += 1

    def run_for(self, seconds: float) -> None:
        """Advance by ``seconds`` (a whole number of ticks) or until stop() is called."""
        duration_us = seconds_to_us(seconds)
        if duration_us < 0:
            raise ValueError(f"duration must be >= 0, got {seconds} s")
        if duration_us % self.dt_us:
            raise ValueError(f"{seconds} s is not a whole number of {self.dt_us} us ticks")
        self._stop_reason = None
        end_us = self.clock.us + duration_us
        while self.clock.us < end_us and self._stop_reason is None:
            self.step()

    def run_until(self, predicate: Callable[[World], bool], *, timeout_s: float) -> bool:
        """Step until ``predicate(world)`` holds. Returns False on timeout or stop()."""
        deadline_us = self.clock.us + seconds_to_us(timeout_s)
        self._stop_reason = None
        while not predicate(self):
            if self.clock.us >= deadline_us or self._stop_reason is not None:
                return False
            self.step()
        return True

    def stop(self, reason: str = "stopped") -> None:
        """Ask the running run_for/run_until to return after the current tick."""
        self._stop_reason = reason

    def _tick_aligned(self, ms: float, what: str, *, allow_zero: bool) -> int:
        us = ms_to_us(ms)
        if us < 0 or (us == 0 and not allow_zero):
            raise ValueError(f"{what} must be {'>= 0' if allow_zero else 'positive'}, got {ms} ms")
        if us % self.dt_us:
            raise ValueError(
                f"{what} {ms} ms is not a multiple of the {self.dt_us / 1000:g} ms physics step"
            )
        return us

"""Deterministic timed callbacks.

Due events fire in order of (time, priority, registration order). Lower
priority values fire first. A periodic event keeps its registration order on
every firing, so two events with the same period and priority always fire in
the order they were registered.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable
from itertools import count
from typing import Any

Callback = Callable[[Any], None]


class EventHandle:
    __slots__ = ("name", "callback", "priority", "period_us", "seq", "cancelled", "fire_count")

    def __init__(
        self, name: str, callback: Callback, priority: int, period_us: int | None, seq: int
    ):
        self.name = name
        self.callback = callback
        self.priority = priority
        self.period_us = period_us
        self.seq = seq
        self.cancelled = False
        self.fire_count = 0

    def cancel(self) -> None:
        self.cancelled = True

    def __repr__(self) -> str:
        kind = f"every {self.period_us} us" if self.period_us else "once"
        state = ", cancelled" if self.cancelled else ""
        return f"EventHandle({self.name!r}, {kind}{state})"


class EventScheduler:
    def __init__(self) -> None:
        self._heap: list[tuple[int, int, int, EventHandle]] = []
        self._seq = count()

    def schedule_at(
        self, time_us: int, callback: Callback, *, priority: int = 0, name: str = ""
    ) -> EventHandle:
        handle = EventHandle(name, callback, priority, None, next(self._seq))
        self._push(time_us, handle)
        return handle

    def schedule_every(
        self,
        period_us: int,
        callback: Callback,
        *,
        start_us: int,
        priority: int = 0,
        name: str = "",
    ) -> EventHandle:
        if period_us <= 0:
            raise ValueError("period must be positive")
        handle = EventHandle(name, callback, priority, period_us, next(self._seq))
        self._push(start_us, handle)
        return handle

    def next_time_us(self) -> int | None:
        while self._heap and self._heap[0][3].cancelled:
            heapq.heappop(self._heap)
        return self._heap[0][0] if self._heap else None

    def run_due(self, now_us: int, context: Any) -> int:
        """Fire every event due at or before ``now_us``, passing ``context``.

        Events scheduled for ``now_us`` by a callback fire in the same call.
        Returns the number of callbacks fired.
        """
        fired = 0
        while self._heap and self._heap[0][0] <= now_us:
            time_us, _, _, handle = heapq.heappop(self._heap)
            if handle.cancelled:
                continue
            if handle.period_us is not None:
                # Reschedule before calling, so the callback may cancel itself.
                self._push(time_us + handle.period_us, handle)
            handle.fire_count += 1
            handle.callback(context)
            fired += 1
        return fired

    def __len__(self) -> int:
        return sum(1 for entry in self._heap if not entry[3].cancelled)

    def _push(self, time_us: int, handle: EventHandle) -> None:
        heapq.heappush(self._heap, (time_us, handle.priority, handle.seq, handle))

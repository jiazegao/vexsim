"""Fanning a run's messages out to the pages that watch it."""

from __future__ import annotations

import asyncio

_FRAME = object()  # a frame is waiting in a Subscriber


class Subscriber:
    """One browser's queue of a session's messages. Frames don't pile up: a slow viewer
    gets the newest frame, never an old one, and every other message in order."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.frame: dict | None = None
        self.floor = 0  # messages numbered up to this were covered by the catch-up

    def push(self, message: dict) -> None:
        if message.get("type") == "frame":
            if self.frame is None:
                self.queue.put_nowait(_FRAME)
            self.frame = message
        else:
            self.queue.put_nowait(message)

    def deliver(self, seq: int, message: dict) -> None:
        if seq > self.floor:
            self.push(message)

    async def next(self) -> dict:
        item = await self.queue.get()
        if item is _FRAME:
            item, self.frame = self.frame, None
        return item


class Hub:
    """Delivers messages published from any thread to the subscribers of a channel."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.channels: dict[str, set[Subscriber]] = {}

    def publish(self, channel: str, seq: int, message: dict) -> None:
        loop = self.loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._deliver, channel, seq, message)

    def _deliver(self, channel: str, seq: int, message: dict) -> None:
        for subscriber in list(self.channels.get(channel, ())):
            subscriber.deliver(seq, message)

    def subscribe(self, channel: str) -> Subscriber:
        subscriber = Subscriber()
        self.channels.setdefault(channel, set()).add(subscriber)
        return subscriber

    def unsubscribe(self, channel: str, subscriber: Subscriber) -> None:
        self.channels.get(channel, set()).discard(subscriber)

    def listening(self, channel: str) -> bool:
        """Whether anyone is subscribed to the channel."""
        return bool(self.channels.get(channel))

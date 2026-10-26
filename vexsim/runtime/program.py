"""Loading robot programs and running their competition functions as coroutines."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from collections.abc import Callable, Generator, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

from vexsim.api import Delay

DEFAULT_YIELD_MS = 10.0
PHASES = ("initialize", "autonomous", "opcontrol")


def load_program(path: str | Path) -> ModuleType:
    """Import a robot program file (it runs as ordinary Python code)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"program not found: {path}")
    name = f"vexsim_program_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def as_generator(fn: Callable[[Any], Any], bot: Any) -> Iterator[Any]:
    """Call a competition function; plain functions run to completion in one tick."""
    result = fn(bot)
    if inspect.isgenerator(result):
        return result

    def once() -> Generator[None, None, None]:
        return
        yield  # pragma: no cover

    return once()


class Coroutine:
    """Steps a program generator, honoring ``yield delay(ms)`` (bare ``yield`` = 10 ms)."""

    def __init__(self, name: str, generator: Iterator[Any], start_us: int, limit_s: float | None):
        self.name = name
        self.generator = generator
        self.wake_us = start_us
        self.end_us = None if limit_s is None else start_us + round(limit_s * 1e6)
        self.finished = False
        self.timed_out = False

    def tick(self, now_us: int) -> None:
        if self.finished:
            return
        if self.end_us is not None and now_us >= self.end_us:
            self.timed_out = True
            self.stop()
            return
        if now_us < self.wake_us:
            return
        try:
            value = next(self.generator)
        except StopIteration:
            self.finished = True
            return
        ms = value.ms if isinstance(value, Delay) else DEFAULT_YIELD_MS
        if value is not None and not isinstance(value, Delay):
            raise TypeError(f"{self.name}: yield delay(ms) or nothing, not {value!r}")
        self.wake_us = now_us + max(1, round(ms * 1000))

    def stop(self) -> None:
        self.finished = True
        close = getattr(self.generator, "close", None)
        if close is not None:
            close()

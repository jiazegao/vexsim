"""Which step robots take (``VEXSIM_STEP``), and how alike the two steps have to be."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

MODES = ("auto", "python", "compiled", "check")
ENV = "VEXSIM_STEP"
_override: str | None = None

# From the same state, one step of each agrees on every number to this part of its size
# (outright, for a number under 1). Measured, they agree some ten thousand times closer.
TOLERANCE = 1e-9


class StepUnavailable(RuntimeError):
    """The compiled step was asked for (VEXSIM_STEP=compiled or check) and can't be had."""


class StepMismatch(AssertionError):
    """The two steps, from the same state, gave numbers further apart than ``TOLERANCE``."""


def mode() -> str:
    """Which step robots take: ``VEXSIM_STEP``, or what ``use`` says."""
    chosen = _override or os.environ.get(ENV, "").strip().lower() or "auto"
    if chosen not in MODES:
        raise ValueError(f"{ENV} must be one of {', '.join(MODES[1:])} (or unset), got {chosen!r}")
    return chosen


@contextmanager
def use(chosen: str) -> Iterator[None]:
    """Robots that take their first step inside take this step, whatever ``VEXSIM_STEP`` says."""
    global _override
    if chosen not in MODES:
        raise ValueError(f"a step is one of {', '.join(MODES)}, got {chosen!r}")
    before, _override = _override, chosen
    try:
        yield
    finally:
        _override = before

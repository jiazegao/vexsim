"""The API Python robot programs are written against (PROS 4 style).

A program is a Python file with any of these generator functions, each taking
the ``bot`` object::

    from vexsim.api import delay

    def initialize(bot): ...      # default: wait for the IMU to calibrate
    def autonomous(bot): ...
    def opcontrol(bot): ...       # default: arcade drive from the controller

``yield delay(ms)`` waits like ``pros::delay(ms)``; a bare ``yield`` waits 10 ms.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Delay:
    ms: float


def delay(ms: float) -> Delay:
    """Yield this from a program to wait ``ms`` milliseconds of simulated time."""
    if ms < 0:
        raise ValueError("delay must be >= 0 ms")
    return Delay(ms)


__all__ = ["Delay", "delay"]

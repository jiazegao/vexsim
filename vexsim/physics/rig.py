"""Test rigs for a single motor: a driven inertia, and a speed-controlled dynamometer.

These rigs are for validation, calibration and plotting. The drivetrain
(Phase 3) integrates motors together with wheels and the chassis instead.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from vexsim.physics.motor import V5Motor
from vexsim.physics.power import IdealSupply


class ShaftRig:
    """A motor driving a rigid inertia with optional viscous drag and external torque.

    Implements the World ``System`` protocol, so it can be added to a World and
    commanded from timed events.
    """

    def __init__(
        self,
        motor: V5Motor,
        *,
        load_inertia_kgm2: float = 0.0,
        viscous_nm_s: float = 0.0,
        external_torque: float | Callable[[float], float] = 0.0,
    ):
        self.motor = motor
        self.load_inertia_kgm2 = load_inertia_kgm2
        self.viscous_nm_s = viscous_nm_s
        self.external_torque = external_torque
        self.omega = 0.0
        self.angle = 0.0
        self.time = 0.0

    @property
    def inertia_kgm2(self) -> float:
        return self.load_inertia_kgm2 + self.motor.reflected_inertia_kgm2

    def step(self, world: Any, dt: float) -> None:
        self.advance(dt)

    def advance(self, dt: float) -> None:
        ext = self.external_torque
        tau_ext = ext(self.time) if callable(ext) else ext
        tau = self.motor.update(self.omega, dt) + tau_ext - self.viscous_nm_s * self.omega
        self.omega += tau / self.inertia_kgm2 * dt  # semi-implicit Euler
        self.angle += self.omega * dt
        self.time += dt
        end_step = getattr(self.motor.supply, "end_step", None)
        if end_step is not None:
            end_step(dt)

    def run(self, seconds: float, dt: float = 0.001) -> None:
        for _ in range(round(seconds / dt)):
            self.advance(dt)


@dataclass(frozen=True)
class OperatingPoint:
    speed: float  # rad/s
    torque: float  # N*m
    current: float  # A
    voltage: float  # V
    power_in: float  # W
    power_out: float  # W


def hold_speed(
    motor: V5Motor,
    omega: float,
    *,
    min_settle_s: float = 0.3,
    max_settle_s: float = 20.0,
    dt: float = 0.001,
) -> OperatingPoint:
    """Dynamometer: hold the shaft at ``omega`` until the motor's torque stops changing.

    Close to the velocity target the speed error is tiny, so the controller's
    integral takes seconds to saturate. The settling time adapts to that.
    """
    end_step = getattr(motor.supply, "end_step", None)
    window = round(0.1 / dt)
    tolerance = 1e-5 * motor.ratio  # N*m over the window, scaled with the cartridge
    previous = None
    for i in range(1, round(max_settle_s / dt) + 1):
        motor.update(omega, dt)
        if end_step is not None:
            end_step(dt)
        if i % window == 0 and i * dt >= min_settle_s:
            if previous is not None and abs(motor.torque - previous) < tolerance:
                break
            previous = motor.torque
    return OperatingPoint(
        speed=omega,
        torque=motor.torque,
        current=motor.current,
        voltage=motor.voltage,
        power_in=motor.power_in,
        power_out=motor.power_out,
    )


def free_speed(motor: V5Motor, volts: float) -> float:
    """Output shaft speed (rad/s) where the motor's torque falls to zero at ``volts``."""
    lo, hi = 0.0, 2.0 * volts / (motor.core.ke * motor.ratio)
    core = motor.core
    for _ in range(60):  # bisection on the natural (unlimited) torque line
        mid = 0.5 * (lo + hi)
        w_core = mid * motor.ratio
        current = (volts - core.ke * w_core) / core.resistance_ohm
        if core.kt * current - core.friction(w_core) > 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


@dataclass(frozen=True)
class TorqueSpeedCurve:
    cartridge: str
    command: str  # "velocity" (max rated speed) or "voltage" (+12 V)
    supply_voltage: float
    speed: np.ndarray  # rad/s
    torque: np.ndarray
    current: np.ndarray
    power_out: np.ndarray


def torque_speed_curve(
    cartridge: str,
    command: str = "velocity",
    *,
    supply_voltage: float = 12.8,
    points: int = 61,
) -> TorqueSpeedCurve:
    """Steady-state torque, current and output power from stall to free speed.

    ``command="velocity"`` asks for full rated speed (move_velocity at max) and
    is swept up to rated speed. ``command="voltage"`` applies +12 V
    (move_voltage(12000)) and is swept up to its natural free speed.
    """
    if command not in ("velocity", "voltage"):
        raise ValueError("command must be 'velocity' or 'voltage'")
    probe = V5Motor(cartridge)
    if command == "velocity":
        top = probe.rated_speed
    else:
        volts = min(probe.spec.max_command_v, supply_voltage)
        top = free_speed(probe, volts)
    speeds = np.linspace(0.0, top, points)
    rows = []
    for omega in speeds:
        motor = V5Motor(cartridge, supply=IdealSupply(supply_voltage))
        if command == "velocity":
            motor.set_velocity(motor.rated_speed)
        else:
            motor.set_voltage(motor.spec.max_command_v)
        rows.append(hold_speed(motor, float(omega)))
    return TorqueSpeedCurve(
        cartridge=cartridge,
        command=command,
        supply_voltage=supply_voltage,
        speed=speeds,
        torque=np.array([r.torque for r in rows]),
        current=np.array([r.current for r in rows]),
        power_out=np.array([r.power_out for r in rows]),
    )

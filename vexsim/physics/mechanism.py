"""Mechanisms: motors that drive something other than the wheels (lifts, intakes, arms).

Each mechanism is one rotating output driven by its motors through a gear
ratio, integrated at the motor shaft like a drive gear group:

    J dw/dt = sum(motor torques) - G * (load + friction(w))

with ``J`` the motors' rotor inertia plus the load's, ``G`` the output speed
over the motor speed, ``load`` a constant torque at the output (a lift's
weight) and Coulomb friction. Friction is applied implicitly (exact stiction,
no chatter at the 1 ms step). Hard stops end the travel inelastically: the
output stops dead, and motors pushing into the stop stall there.

A mechanism doesn't push the chassis (its mass is part of the body's). Its
motors draw from the battery with the rest.
"""

from __future__ import annotations

import math

from vexsim.config.robot import MechanismConfig
from vexsim.physics.motor import V5Motor


class Mechanism:
    def __init__(self, name: str, config: MechanismConfig, motors: list[tuple[int, int, V5Motor]]):
        self.name = name
        self.config = config
        self.ratio = config.speed_ratio  # output speed / motor shaft speed
        self.motors = motors  # (port, mount sign, motor)
        self.inertia = (
            sum(m.reflected_inertia_kgm2 for _, _, m in motors)
            + config.inertia_kgm2 * self.ratio**2
        )
        self.load = config.load_torque_nm * self.ratio  # at the motor shaft
        self.friction = config.friction_nm * self.ratio
        if config.range_deg is None:
            self.low, self.high = -math.inf, math.inf
        else:  # motor shaft radians
            self.low, self.high = (math.radians(d) / self.ratio for d in config.range_deg)
        self.angle = 0.0  # motor shaft, rad from the start
        self.speed = 0.0  # motor shaft, rad/s

    @property
    def position_deg(self) -> float:
        """Output angle in degrees from the starting position."""
        return math.degrees(self.angle * self.ratio)

    @property
    def at_stop(self) -> bool:
        return self.angle <= self.low or self.angle >= self.high

    def advance(self, dt: float) -> None:
        w = self.speed
        torque = sum(sign * motor.update(sign * w, dt) for _, sign, motor in self.motors)
        w_free = w + dt * (torque - self.load) / self.inertia
        grip = dt * self.friction / self.inertia  # the most friction can change the speed
        w = 0.0 if abs(w_free) <= grip else w_free - math.copysign(grip, w_free)
        angle = self.angle + w * dt
        if angle >= self.high:
            angle, w = self.high, min(w, 0.0)
        elif angle <= self.low:
            angle, w = self.low, max(w, 0.0)
        self.angle, self.speed = angle, w
        for _, sign, motor in self.motors:  # the encoders follow the output, stops included
            motor.position = sign * angle

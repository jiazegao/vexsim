"""A robot built from its config: motors, gear groups, wheels, chassis, mechanisms and power.

Degrees of freedom (all velocities):
  u, v, w   CG velocity in the body frame (+x forward, +y left) and yaw rate
  g_k       output shaft speed of the motors in gear group k

All wheels in a group turn together at ``ratio * g_k``. Contact forces are
smoothed Coulomb friction (see wheel.py) of contact velocities that are linear
in the velocity vector, ``c = C @ qdot``. Generalized forces are therefore
``-C.T @ F(c)``, and their Jacobian ``-C.T @ D @ C`` is symmetric and
dissipative. ``D`` is diagonal except for a 2x2 block per traction wheel (its
friction circle couples two channels). Each step solves the linearly implicit
Euler update

    (M - dt * J) dq = dt * Q

which stays stable at a 1 ms step even though tire friction is far stiffer.
Motor torques, Coriolis terms and external forces are treated explicitly.
Field walls, if given, then push the footprint back inside (see field.py).

Motor direction: a negative port in the config means the motor is mounted so
that its raw positive direction drives the group backward. Group commands
apply that sign, so positive always means "wheels roll forward", exactly like
a PROS 4 MotorGroup built from the same ports.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from vexsim.config.robot import RobotConfig
from vexsim.physics.battery import Battery
from vexsim.physics.chassis import NormalLoads
from vexsim.physics.field import WallContact, Walls
from vexsim.physics.mechanism import Mechanism
from vexsim.physics.motor import BrakeMode, V5Motor
from vexsim.physics.params import PhysicsParams, resolve_params
from vexsim.physics.power import PowerSystem
from vexsim.physics.wheel import friction_circle, smoothed_coulomb
from vexsim.units import in_to_m

CHANNELS = 3  # slip, free, rolling (see wheel.py)


@dataclass
class DriveGroup:
    """Motors geared to a set of wheels. Positive commands roll the wheels forward."""

    name: str
    index: int  # position of this group's speed in the velocity vector
    ratio: float  # wheel speed / motor shaft speed
    motors: list[tuple[int, int, V5Motor]]  # (port, mount sign, motor)
    wheels: list[int]
    inertia_kgm2: float = 0.0  # at the motor shaft, motors and wheels combined

    def set_voltage(self, volts: float) -> None:
        for _, sign, motor in self.motors:
            motor.set_voltage(sign * volts)

    def set_velocity(self, rad_s: float) -> None:
        """Motor shaft speed target (rad/s); the motors' own controllers track it."""
        for _, sign, motor in self.motors:
            motor.set_velocity(sign * rad_s)

    def stop(self) -> None:
        for _, _, motor in self.motors:
            motor.stop()

    @property
    def brake_mode(self) -> BrakeMode:
        return self.motors[0][2].brake_mode

    @brake_mode.setter
    def brake_mode(self, mode: BrakeMode) -> None:
        for _, _, motor in self.motors:
            motor.brake_mode = mode

    @property
    def rated_speed(self) -> float:
        return self.motors[0][2].rated_speed


@dataclass
class ContactState:
    """Per-wheel results of the latest step (SI, body frame)."""

    normal: np.ndarray = field(default_factory=lambda: np.zeros(0))
    slip: np.ndarray = field(default_factory=lambda: np.zeros(0))  # in the grip direction (m/s)
    lateral_velocity: np.ndarray = field(default_factory=lambda: np.zeros(0))  # free direction
    traction_force: np.ndarray = field(default_factory=lambda: np.zeros(0))  # along grip dir
    lateral_force: np.ndarray = field(default_factory=lambda: np.zeros(0))  # along free dir


class Robot:
    def __init__(
        self,
        config: RobotConfig,
        *,
        params: PhysicsParams | None = None,
        battery_soc: float = 1.0,
        pose: tuple[float, float, float] = (0.0, 0.0, 0.0),
        walls: Walls | None = None,
    ):
        """Build the robot. ``pose`` is (x m, y m, heading rad) of the footprint center.

        Without ``walls`` the robot drives on an endless floor.
        """
        self.config = config
        self.params = params or resolve_params(config.overrides)
        body = config.body
        self.mass = body.mass_kg
        self.yaw_inertia = body.yaw_inertia_kgm2()
        self.cg_offset = np.array([in_to_m(body.cg_in[0]), in_to_m(body.cg_in[1])])
        self.cg_height = in_to_m(body.cg_in[2])
        self.power = PowerSystem(Battery(self.params.battery, soc=battery_soc))

        wheels = config.drivetrain.wheels
        self.wheel_names = [w.name for w in wheels]
        index = {name: i for i, name in enumerate(self.wheel_names)}
        mount = np.array([[in_to_m(w.pos_in[0]), in_to_m(w.pos_in[1])] for w in wheels])
        self.wheel_pos = mount - self.cg_offset  # relative to the CG
        self.wheel_heading = np.radians([w.heading_deg for w in wheels])
        self.roller_angle = np.radians([w.roller_angle for w in wheels])
        self.wheel_radius = np.array([in_to_m(w.diameter_in) / 2 for w in wheels])
        self.wheel_drop = np.array([in_to_m(w.drop_in) for w in wheels])
        specs = [self.params.wheel(w.type) for w in wheels]
        self.grip_mu = np.array([s.grip_mu for s in specs])

        self.groups: list[DriveGroup] = []
        self.motors: dict[int, V5Motor] = {}
        for k, (name, gear) in enumerate(config.drivetrain.gearing.items()):
            members = []
            for port in gear.motors:
                motor = V5Motor(gear.cartridge, spec=self.params.motor, thermal=self.params.thermal)
                self.power.attach(motor)
                self.motors[abs(port)] = motor
                members.append((abs(port), 1 if port > 0 else -1, motor))
            group = DriveGroup(
                name, 3 + k, gear.speed_ratio, members, [index[w] for w in gear.wheels]
            )
            wheel_inertia = sum(
                0.5 * specs[i].mass_kg * self.wheel_radius[i] ** 2 for i in group.wheels
            )
            group.inertia_kgm2 = (
                sum(m.reflected_inertia_kgm2 for _, _, m in members)
                + wheel_inertia * group.ratio**2
            )
            self.groups.append(group)
        self._group_by_name = {g.name: g for g in self.groups}
        self.mechanisms: dict[str, Mechanism] = {}
        for name, mech in config.mechanisms.items():
            members = []
            for port in mech.motors:
                motor = V5Motor(mech.cartridge, spec=self.params.motor, thermal=self.params.thermal)
                self.power.attach(motor)
                self.motors[abs(port)] = motor
                members.append((abs(port), 1 if port > 0 else -1, motor))
            self.mechanisms[name] = Mechanism(name, mech, members)

        n = 3 + len(self.groups)
        self.mass_matrix = np.diag(
            [self.mass, self.mass, self.yaw_inertia, *(g.inertia_kgm2 for g in self.groups)]
        )
        self.contact_matrix = self._build_contact_matrix(n)
        coeff, scale = zip(*(s.channel_coefficients() for s in specs), strict=True)
        self._channel_coeff = np.concatenate(coeff)
        self._channel_scale = np.concatenate(scale)
        self._channel_wheel = np.repeat(np.arange(len(wheels)), CHANNELS)
        # slip rows of the wheels whose slip and free channels share a friction circle
        self._coupled_rows = [CHANNELS * i for i, s in enumerate(specs) if s.coupled]
        chassis = self.params.chassis
        self.normal_loads = NormalLoads(
            self.wheel_pos,
            self.wheel_drop,
            chassis.wheel_stiffness_n_per_m,
            self.mass * chassis.gravity_m_s2,
            self.cg_height,
        )

        self.qdot = np.zeros(n)
        x, y, heading = pose
        cg = self._rotate(self.cg_offset, heading)
        self.cg_position = np.array([x + cg[0], y + cg[1]])
        self.heading = heading
        self.time = 0.0
        self.external_force = np.zeros(2)  # field frame, N, applied at the CG
        self.external_torque = 0.0
        self.contacts = ContactState()
        self._ground_force = (0.0, 0.0)
        self.contacts.normal = self.normal_loads()

        length, width = (in_to_m(v) for v in body.footprint_in)
        half = np.array([[1, 1], [-1, 1], [-1, -1], [1, -1]]) * (length / 2, width / 2)
        self.footprint_corners = half - self.cg_offset  # body frame, relative to the CG
        self.footprint_radius = float(np.hypot(*self.footprint_corners.T).max())
        self.walls = walls
        self.wall_contacts: list[WallContact] = []  # this step's
        self.wall_hits = 0  # times the robot started touching a wall

    # --- construction helpers ---------------------------------------------------------

    def _build_contact_matrix(self, n: int) -> np.ndarray:
        rows = np.zeros((CHANNELS * len(self.wheel_names), n))
        group_of = {w: g for g in self.groups for w in g.wheels}
        geometry = zip(
            self.wheel_pos, self.wheel_heading, self.roller_angle, self.wheel_radius, strict=True
        )
        for i, ((px, py), phi, gamma, r) in enumerate(geometry):
            # grip direction: the rolling direction turned by the roller angle
            c, s = math.cos(phi + gamma), math.sin(phi + gamma)
            group = group_of[i]
            spin = group.ratio * r  # wheel surface speed per unit motor shaft speed
            # contact point velocity: (u - w*py, v + w*px)
            v_grip = np.array([c, s, -py * c + px * s])
            v_free = np.array([-s, c, py * s + px * c])
            slip, free, rolling = CHANNELS * i, CHANNELS * i + 1, CHANNELS * i + 2
            rows[slip, :3] = -v_grip
            rows[slip, group.index] = spin * math.cos(gamma)
            rows[free, :3] = v_free
            rows[free, group.index] = spin * math.sin(gamma)
            rows[rolling, group.index] = spin
        return rows

    @staticmethod
    def _rotate(vec: Iterable[float], angle: float) -> np.ndarray:
        c, s = math.cos(angle), math.sin(angle)
        x, y = vec
        return np.array([c * x - s * y, s * x + c * y])

    # --- commands and readouts ----------------------------------------------------------

    def group(self, name: str) -> DriveGroup:
        return self._group_by_name[name]

    @property
    def pose(self) -> tuple[float, float, float]:
        """(x m, y m, heading rad) of the footprint center in the field frame."""
        center = self.cg_position - self._rotate(self.cg_offset, self.heading)
        return float(center[0]), float(center[1]), float(self.heading)

    @property
    def body_velocity(self) -> tuple[float, float, float]:
        """(forward m/s, left m/s, yaw rad/s) of the footprint center, in the body frame."""
        u, v, w = self.qdot[:3]
        cx, cy = self.cg_offset
        return float(u + w * cy), float(v - w * cx), float(w)

    @property
    def field_velocity(self) -> tuple[float, float]:
        u, v, _ = self.body_velocity
        vx, vy = self._rotate((u, v), self.heading)
        return float(vx), float(vy)

    def group_speed(self, name: str) -> float:
        """Motor shaft speed of a group (rad/s, positive = wheels rolling forward)."""
        return float(self.qdot[self.group(name).index])

    def point_velocity(self, rel: Iterable[float]) -> tuple[float, float]:
        """Body-frame velocity (m/s) of a point given relative to the CG (m)."""
        px, py = rel
        u, v, w = self.qdot[:3]
        return float(u - w * py), float(v + w * px)

    # --- simulation -----------------------------------------------------------------

    def step(self, world: Any, dt: float) -> None:
        self.advance(dt)

    def advance(self, dt: float) -> None:
        qdot = self.qdot
        normal = self.normal_loads(*self._ground_force)

        forces = np.zeros_like(qdot)
        for group in self.groups:
            speed = qdot[group.index]
            for _, sign, motor in group.motors:
                forces[group.index] += sign * motor.update(sign * speed, dt)
        for mechanism in self.mechanisms.values():
            mechanism.advance(dt)

        C = self.contact_matrix
        contact_vel = C @ qdot
        limit = self._channel_coeff * normal[self._channel_wheel]
        friction, slope = smoothed_coulomb(contact_vel, limit, self._channel_scale)
        if self._coupled_rows:
            jacobian = -C.T @ self._friction_circles(contact_vel, limit, friction, slope) @ C
        else:
            jacobian = -(C.T * slope) @ C
        contact_forces = -C.T @ friction
        forces += contact_forces

        u, v, w = qdot[:3]
        forces[0] += self.mass * w * v  # rotating-frame terms
        forces[1] -= self.mass * w * u
        if self.external_force.any() or self.external_torque:
            ext = self._rotate(self.external_force, -self.heading)
            forces[0] += ext[0]
            forces[1] += ext[1]
            forces[2] += self.external_torque

        qdot += np.linalg.solve(self.mass_matrix - dt * jacobian, dt * forces)

        u, v, w = qdot[:3]
        mid = self.heading + 0.5 * w * dt
        c, s = math.cos(mid), math.sin(mid)
        self.cg_position[0] += (c * u - s * v) * dt
        self.cg_position[1] += (s * u + c * v) * dt
        self.heading += w * dt
        self.time += dt
        self.power.end_step(dt)
        if self.walls is not None:
            touching = bool(self.wall_contacts)
            self.wall_contacts = self.walls.resolve(self)
            self.wall_hits += bool(self.wall_contacts) and not touching

        self._ground_force = (float(contact_forces[0]), float(contact_forces[1]))
        state = self.contacts
        state.normal = normal
        state.slip = contact_vel[0::CHANNELS]
        state.lateral_velocity = contact_vel[1::CHANNELS]
        state.traction_force = friction[0::CHANNELS]
        state.lateral_force = -friction[1::CHANNELS]

    def _friction_circles(self, contact_vel, limit, friction, slope) -> np.ndarray:
        """Replace the traction wheels' slip and free forces with their friction circle;
        returns the channel damping matrix ``D`` (diagonal plus their 2x2 blocks)."""
        damping = np.diag(slope)
        for i in self._coupled_rows:
            j = i + 1
            friction[i], friction[j], damping[i, i], damping[j, j], cross = friction_circle(
                float(contact_vel[i]),
                float(contact_vel[j]),
                float(limit[i]),
                float(self._channel_scale[i]),
            )
            damping[i, j] = damping[j, i] = cross
        return damping

    def run(self, seconds: float, dt: float = 0.001) -> None:
        for _ in range(round(seconds / dt)):
            self.advance(dt)

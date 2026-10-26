"""The field perimeter: walls the robot's footprint collides with.

The footprint is a rectangle (``body.footprint_in``) around the robot's
center. Each physics step, after the robot moves, every corner that ended up
past a wall is a contact. Contacts are resolved with impulses, the usual way
rigid-body engines handle hard impacts:

  normal    stop the corner's approach, then bounce it back at
            ``wall_restitution`` times the impact speed (slow touches don't
            bounce, so a robot pushed against a wall stays there)
  friction  oppose the corner's sliding along the wall, up to
            ``wall_friction`` times the normal impulse (Coulomb)

A few sweeps over the contacts (sequential impulses) settle two or three
simultaneous contacts, such as both front corners or a field corner. Then the
robot is moved straight back inside the walls, so walls never let a robot
through, however hard it is driven into them.

The impulses act on the body; the wheels follow through tire friction over the
next steps, so a robot driving into a wall stalls with its wheels slipping,
and an angled approach rotates it square against the wall (a wall reset).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from vexsim.config.field import FieldConfig
from vexsim.units import in_to_m

if TYPE_CHECKING:
    from vexsim.physics.robot import Robot

BOUNCE_SPEED_M_S = 0.05  # slower impacts don't bounce (resting contact)
ITERATIONS = 8


@dataclass(frozen=True)
class FieldSpec:
    wall_restitution: float = 0.2  # rebound / impact speed: aluminum frame on the walls (estimate)
    wall_friction: float = 0.3  # robot frame sliding along the polycarbonate walls (estimate)

    def __post_init__(self) -> None:
        if not (math.isfinite(self.wall_restitution) and 0.0 <= self.wall_restitution <= 1.0):
            raise ValueError(f"field.wall_restitution must be in 0..1, got {self.wall_restitution}")
        if not (math.isfinite(self.wall_friction) and self.wall_friction >= 0.0):
            raise ValueError(f"field.wall_friction must be 0 or more, got {self.wall_friction}")


@dataclass(frozen=True)
class WallContact:
    point: tuple[float, float]  # field frame (m)
    normal: tuple[float, float]  # into the field
    depth_m: float  # how far past the wall the corner was before the correction
    impulse_n_s: float  # normal impulse the wall applied


class Walls:
    """Four walls around the field center, ``half_size`` (m) away along x and y."""

    def __init__(self, half_size: tuple[float, float], spec: FieldSpec | None = None):
        self.half_size = (float(half_size[0]), float(half_size[1]))
        self.spec = spec or FieldSpec()

    @classmethod
    def of(cls, field: FieldConfig, spec: FieldSpec | None = None) -> Walls:
        """The perimeter of a field config (its size is measured inside the walls)."""
        return cls((in_to_m(field.size_in[0]) / 2, in_to_m(field.size_in[1]) / 2), spec)

    def resolve(self, robot: Robot) -> list[WallContact]:
        """Push the robot's footprint back inside the walls; returns this step's contacts."""
        half = self.half_size
        cg = robot.cg_position
        if (
            abs(cg[0]) + robot.footprint_radius < half[0]
            and abs(cg[1]) + robot.footprint_radius < half[1]
        ):
            return []  # nowhere near a wall (the usual case)

        heading = robot.heading
        c, s = math.cos(heading), math.sin(heading)
        corners = robot.footprint_corners  # (4, 2) body frame, relative to the CG
        world = cg + corners @ np.array([[c, s], [-s, c]])
        found = []  # (corner, field normal, depth)
        for axis in (0, 1):
            for sign in (1.0, -1.0):
                depth = sign * world[:, axis] - half[axis]
                for k in np.flatnonzero(depth > 0.0):
                    normal = np.zeros(2)
                    normal[axis] = -sign
                    found.append((int(k), normal, float(depth[k])))
        if not found:
            return []

        points = [(*corners[k], *n) for k, n, _ in found]
        impulses = robot_impulses(robot, points, self.spec)
        # Move straight back in: per wall, by its deepest corner.
        shift = np.zeros(2)
        for _, normal, depth in found:
            axis = 0 if normal[0] else 1
            if abs(shift[axis]) < depth:
                shift[axis] = normal[axis] * depth
        robot.cg_position += shift
        return [
            WallContact(
                point=(float(world[k, 0]), float(world[k, 1])),
                normal=(float(n[0]), float(n[1])),
                depth_m=depth,
                impulse_n_s=float(j),
            )
            for (k, n, depth), j in zip(found, impulses, strict=True)
        ]


def robot_impulses(
    robot: Robot, points: list[tuple[float, float, float, float]], spec: FieldSpec
) -> list[float]:
    """Sequential impulses on the robot's body velocity (u, v, w) at fixed contacts.

    ``points`` are (rx, ry, nx, ny): the contact point relative to the CG in the
    body frame, and the field-frame normal pushing the robot away. Returns each
    contact's normal impulse.
    """
    c, s = math.cos(robot.heading), math.sin(robot.heading)
    m, inertia = robot.mass, robot.yaw_inertia
    mu, e = spec.wall_friction, spec.wall_restitution
    q = robot.qdot
    geometry = []
    for rx, ry, fx, fy in points:
        # the normal and tangent in the body frame
        nx, ny = c * fx + s * fy, -s * fx + c * fy
        tx, ty = -ny, nx
        rn, rt = rx * ny - ry * nx, rx * ty - ry * tx
        vn = (q[0] - q[2] * ry) * nx + (q[1] + q[2] * rx) * ny
        target = -e * vn if vn < -BOUNCE_SPEED_M_S else 0.0
        geometry.append((rx, ry, (nx, ny, rn), (tx, ty, rt), target))

    def push(direction: tuple[float, float, float], amount: float) -> None:
        dx, dy, moment = direction
        q[0] += amount * dx / m
        q[1] += amount * dy / m
        q[2] += amount * moment / inertia

    def speed(rx: float, ry: float, direction: tuple[float, float, float]) -> float:
        return (q[0] - q[2] * ry) * direction[0] + (q[1] + q[2] * rx) * direction[1]

    normal_impulse = [0.0] * len(geometry)
    friction_impulse = [0.0] * len(geometry)
    for _ in range(ITERATIONS):
        for i, (rx, ry, n, t, target) in enumerate(geometry):
            kn = 1.0 / m + n[2] * n[2] / inertia  # effective mass^-1 along the normal
            total = max(normal_impulse[i] + (target - speed(rx, ry, n)) / kn, 0.0)
            push(n, total - normal_impulse[i])
            normal_impulse[i] = total

            kt = 1.0 / m + t[2] * t[2] / inertia
            bound = mu * total
            friction = friction_impulse[i] - speed(rx, ry, t) / kt
            friction = min(max(friction, -bound), bound)
            push(t, friction - friction_impulse[i])
            friction_impulse[i] = friction
    return normal_impulse

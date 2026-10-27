"""Game elements: fixed obstacles and movable pieces, and everything they collide with.

Obstacles are fixed rectangles and circles (goals, barriers). The robot's
footprint collides with them as with the walls (field.py): a contact is a
footprint corner inside an obstacle, an obstacle corner inside the footprint,
or the point of the footprint nearest a circle, and the same impulses resolve
them (``field.wall_restitution`` and ``field.wall_friction``). A robot with a
``body.shape`` collides by its outside edge (vexsim.geometry): its corners and
the deepest point of each round piece of its edge, obstacle corners inside it,
and the nearest point of each piece of its edge that a circle reaches, so a
goal or a piece in a notch touches both sides.

Pieces are discs (balls, rings, cylinders by their outer diameter) that slide
on the tiles. Each physics step, after the robot moves:

1. Ground friction slows each piece (Coulomb, ``friction * g``) and it moves.
2. Contacts are found: piece-wall, piece-obstacle, piece-piece, robot-piece.
3. Sequential impulses settle them, with the piece's restitution and the
   field's wall friction. A piece pinned against a wall or an obstacle counts as
   fixed while the robot pushes it into that, so the robot stalls there.
4. Nothing may overlap: pieces move out of the robot, then out of walls,
   obstacles and each other; whatever still overlaps the robot pushes it back.

Pieces don't spin, and they all lie flat on the tiles: robots can't drive over
them or pick them up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from vexsim.config.field import FieldConfig
from vexsim.physics.field import (
    BOUNCE_SPEED_M_S,
    ITERATIONS,
    FieldSpec,
    WallContact,
    Walls,
    robot_impulses,
)
from vexsim.units import in_to_m

if TYPE_CHECKING:
    from vexsim.physics.robot import Robot

G = 9.81
PINNED = -0.5  # a fixed contact opposing the robot's push this much (cosine) pins a piece


@dataclass
class Shape:
    """A fixed rectangle (``half`` = half length, half width) or circle (``half`` = (r, r))."""

    circle: bool
    center: np.ndarray  # field frame, m
    heading: float  # rad
    half: tuple[float, float]
    name: str = ""
    color: str | None = None
    height: float | None = None  # m above the floor; None = taller than any sensor
    solid: bool = True  # False: robots and pieces pass over it; only sensors see it

    @property
    def radius(self) -> float:
        """Radius of the circle that contains it."""
        return self.half[0] if self.circle else math.hypot(*self.half)

    def corners(self) -> np.ndarray:
        c, s = math.cos(self.heading), math.sin(self.heading)
        hx, hy = self.half
        local = np.array([[hx, hy], [-hx, hy], [-hx, -hy], [hx, -hy]])
        return self.center + local @ np.array([[c, s], [-s, c]])

    def signed_distance(self, p: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
        """(distance, outward normal, nearest boundary point) for a point; negative inside."""
        if self.circle:
            d = p - self.center
            length = math.hypot(d[0], d[1])
            normal = d / length if length > 1e-12 else np.array([1.0, 0.0])
            return length - self.half[0], normal, self.center + normal * self.half[0]
        c, s = math.cos(self.heading), math.sin(self.heading)
        dx, dy = p[0] - self.center[0], p[1] - self.center[1]
        lx, ly = c * dx + s * dy, -s * dx + c * dy
        hx, hy = self.half
        if abs(lx) <= hx and abs(ly) <= hy:  # inside: the nearest face
            if hx - abs(lx) < hy - abs(ly):
                nl, distance = (math.copysign(1.0, lx), 0.0), abs(lx) - hx
                qx, qy = math.copysign(hx, lx), ly
            else:
                nl, distance = (0.0, math.copysign(1.0, ly)), abs(ly) - hy
                qx, qy = lx, math.copysign(hy, ly)
        else:
            qx, qy = min(max(lx, -hx), hx), min(max(ly, -hy), hy)
            ex, ey = lx - qx, ly - qy
            distance = math.hypot(ex, ey)
            nl = (ex / distance, ey / distance)
        normal = np.array([c * nl[0] - s * nl[1], s * nl[0] + c * nl[1]])
        point = self.center + np.array([c * qx - s * qy, s * qx + c * qy])
        return distance, normal, point

    def ray(self, origin: np.ndarray, direction: np.ndarray) -> float | None:
        """Distance along a unit ray to where it enters the shape, if it does."""
        if self.circle:
            d = origin - self.center
            b = d @ direction
            disc = b * b - (d @ d - self.half[0] ** 2)
            if disc < 0:
                return None
            t = -b - math.sqrt(disc)
            return t if t >= 0 else None
        c, s = math.cos(self.heading), math.sin(self.heading)
        rot = np.array([[c, s], [-s, c]])
        o, d = rot @ (origin - self.center), rot @ direction
        near, far = -math.inf, math.inf
        for axis in (0, 1):
            h = self.half[axis]
            if abs(d[axis]) < 1e-12:
                if abs(o[axis]) > h:
                    return None
                continue
            t1, t2 = (-h - o[axis]) / d[axis], (h - o[axis]) / d[axis]
            near, far = max(near, min(t1, t2)), min(far, max(t1, t2))
        if near > far or far < 0:
            return None
        return max(near, 0.0)


@dataclass
class Pieces:
    """Every movable piece's state, as arrays (field frame, SI)."""

    position: np.ndarray  # (n, 2)
    velocity: np.ndarray  # (n, 2)
    radius: np.ndarray
    mass: np.ndarray
    friction: np.ndarray
    restitution: np.ndarray
    names: list[str]
    colors: list[str | None]

    def __len__(self) -> int:
        return len(self.radius)


@dataclass
class _Contact:
    """One contact for the impulse solver. ``a`` is a piece; ``b`` is a piece, the robot
    (-1) or something fixed (None). ``normal`` pushes ``a`` away from ``b``."""

    a: int
    b: int | None
    normal: np.ndarray
    depth: float
    point: np.ndarray
    target: float = 0.0
    impulse: float = 0.0
    friction: float = 0.0
    inv_mass: float = 0.0  # of a, as this contact sees it (0 when pinned)
    robot: Robot | None = None  # when b is a robot


class Arena:
    """The field the robot drives in: perimeter walls, obstacles and pieces.

    Robots resolve their own contacts with walls and obstacles every step
    (``resolve``); pieces are a physics system of their own (``step``) that
    runs after the robots.
    """

    def __init__(
        self,
        walls: Walls,
        obstacles: list[Shape] | None = None,
        pieces: Pieces | None = None,
    ):
        self.walls = walls
        self.spec: FieldSpec = walls.spec
        self.obstacles = obstacles or []
        self.solid = [o for o in self.obstacles if o.solid]  # what robots and pieces hit
        self.pieces = pieces or _no_pieces()
        self.robots: list[Robot] = []
        self.piece_contacts: list[tuple[np.ndarray, int]] = []  # (point, piece) this step

    @classmethod
    def of(cls, field: FieldConfig, spec: FieldSpec | None = None) -> Arena:
        obstacles = [
            Shape(
                circle=o.shape == "circle",
                center=np.array([in_to_m(o.pos_in[0]), in_to_m(o.pos_in[1])]),
                heading=math.radians(o.heading_deg),
                half=(
                    (in_to_m(o.diameter_in) / 2,) * 2
                    if o.shape == "circle"
                    else (in_to_m(o.size_in[0]) / 2, in_to_m(o.size_in[1]) / 2)
                ),
                name=o.name or f"obstacle {i}",
                color=o.color,
                height=None if o.height_in is None else in_to_m(o.height_in),
                solid=o.solid,
            )
            for i, o in enumerate(field.obstacles)
        ]
        cfgs = field.pieces
        positions = [[in_to_m(p.pos_in[0]), in_to_m(p.pos_in[1])] for p in cfgs]
        pieces = Pieces(
            position=np.array(positions, dtype=float).reshape(-1, 2),
            velocity=np.zeros((len(cfgs), 2)),
            radius=np.array([in_to_m(p.diameter_in) / 2 for p in cfgs]),
            mass=np.array([p.mass_kg for p in cfgs]),
            friction=np.array([p.friction for p in cfgs]),
            restitution=np.array([p.restitution for p in cfgs]),
            names=[p.name or f"piece {i}" for i, p in enumerate(cfgs)],
            colors=[p.color for p in cfgs],
        )
        return cls(Walls.of(field, spec), obstacles, pieces)

    @property
    def half_size(self) -> tuple[float, float]:
        return self.walls.half_size

    # --- the robot's fixed contacts (called by Robot.advance) ---------------------------------

    def resolve(self, robot: Robot) -> list[WallContact]:
        contacts = self.walls.resolve(robot)
        if self.solid:
            contacts += self._robot_obstacles(robot)
        return contacts

    def _robot_obstacles(self, robot: Robot) -> list[WallContact]:
        if robot.outline is None:
            found = self._footprint_obstacles(robot)
        else:
            found = self._shape_obstacles(robot)
        if not found:
            return []
        c, s = math.cos(robot.heading), math.sin(robot.heading)
        points = []
        for point, normal, _ in found:
            d = point - robot.cg_position
            points.append((c * d[0] + s * d[1], -s * d[0] + c * d[1], normal[0], normal[1]))
        impulses = robot_impulses(robot, points, self.spec)
        shift = np.zeros(2)
        for _, normal, depth in found:
            remaining = depth - shift @ normal
            if remaining > 0:
                shift += normal * remaining
        robot.cg_position += shift
        return [
            WallContact((float(p[0]), float(p[1])), (float(n[0]), float(n[1])), d, float(j))
            for (p, n, d), j in zip(found, impulses, strict=True)
        ]

    def _footprint_obstacles(self, robot: Robot) -> list[tuple[np.ndarray, np.ndarray, float]]:
        """A footprint rectangle's contacts: (point, normal pushing the robot, depth)."""
        footprint = _footprint(robot)
        found = []
        for shape in self.solid:
            if math.dist(shape.center, footprint.center) > shape.radius + footprint.radius:
                continue
            if shape.circle:
                distance, normal, point = footprint.signed_distance(shape.center)
                if distance < shape.half[0]:
                    found.append((point, -normal, shape.half[0] - distance))
                continue
            for corner in footprint.corners():
                distance, normal, _ = shape.signed_distance(corner)
                if distance < 0:
                    found.append((corner, normal, -distance))
            for corner in shape.corners():
                distance, normal, _ = footprint.signed_distance(corner)
                if distance < 0:
                    found.append((corner, -normal, -distance))
        return found

    def _shape_obstacles(self, robot: Robot) -> list[tuple[np.ndarray, np.ndarray, float]]:
        """A ``body.shape``'s contacts, as for the footprint: its corners inside an obstacle
        (and the deepest point of each round piece of its edge), obstacle corners inside the
        shape, and each piece of its edge a circle reaches into."""
        outline, cg = robot.outline, robot.cg_position
        c, s = math.cos(robot.heading), math.sin(robot.heading)
        rotate = np.array([[c, s], [-s, c]])  # body frame (from the CG) @ rotate: field frame
        corners = None
        found = []
        for shape in self.solid:
            if math.dist(shape.center, cg) > shape.radius + robot.footprint_radius:
                continue
            if shape.circle:
                local = (shape.center - cg) @ rotate.T
                for _, depth, normal, point in outline.discs(local, shape.half[0]):
                    found.append((cg + point @ rotate, -(normal @ rotate), depth))
                continue
            if corners is None:
                corners = cg + outline.corners @ rotate
            for corner in corners:
                distance, normal, _ = shape.signed_distance(corner)
                if distance < 0:
                    found.append((corner, normal, -distance))
            for arc in robot.footprint_arcs:
                center = cg + np.array(arc.center) @ rotate
                distance, normal, _ = shape.signed_distance(center)
                facing = -normal @ rotate.T  # body frame: from the arc's center to the obstacle
                if distance < arc.radius and arc.covers(math.atan2(facing[1], facing[0])):
                    found.append((center - normal * arc.radius, normal, arc.radius - distance))
            inside = outline.discs((shape.corners() - cg) @ rotate.T, 0.0)
            for k, depth, normal, _ in inside:
                found.append((shape.corners()[k], -(normal @ rotate), depth))
        return found

    # --- pieces (a physics system, stepped after the robots) ----------------------------------

    def step(self, world, dt: float) -> None:
        self.advance(dt)

    def advance(self, dt: float) -> None:
        pieces = self.pieces
        self.piece_contacts = []
        if not len(pieces):
            return
        speed = np.hypot(*pieces.velocity.T)
        moving = speed > 0
        if not moving.any() and not any(self._near(robot) for robot in self.robots):
            return  # all at rest and nothing to push them: no contacts can change
        # 1. ground friction, then move
        if moving.any():
            slow = np.minimum(speed[moving], pieces.friction[moving] * G * dt)
            pieces.velocity[moving] *= ((speed[moving] - slow) / speed[moving])[:, None]
            pieces.position += pieces.velocity * dt
        # 2. contacts
        fixed = self._fixed_contacts()
        pairs = self._piece_pairs()
        robot_contacts = [c for robot in self.robots for c in self._robot_pieces(robot)]
        contacts = fixed + pairs + robot_contacts
        if not contacts:
            return
        # 3. impulses
        pinned = {}  # piece -> normals of its fixed contacts
        for c in fixed:
            pinned.setdefault(c.a, []).append(c.normal)
        for c in contacts:
            c.inv_mass = 1.0 / pieces.mass[c.a]
            if c.b == -1 and any(n @ c.normal < PINNED for n in pinned.get(c.a, ())):
                c.inv_mass = 0.0  # pushed into a wall or obstacle: as good as fixed
            vn = self._relative_velocity(c) @ c.normal
            e = pieces.restitution[c.a]
            c.target = -e * vn if vn < -BOUNCE_SPEED_M_S else 0.0
        for _ in range(ITERATIONS):
            for c in contacts:
                self._solve(c)
        # 4. positions
        for c in robot_contacts:
            self.piece_contacts.append((c.point, c.a))
        self._separate(fixed, pairs, robot_contacts)

    def _near(self, robot: Robot) -> bool:
        """Whether any piece is within reach of the robot's footprint."""
        x, y = robot.pose[:2] if robot.outline is None else robot.cg_position
        gap = np.hypot(self.pieces.position[:, 0] - x, self.pieces.position[:, 1] - y)
        return bool((gap < robot.footprint_radius + self.pieces.radius).any())

    def _fixed_contacts(self) -> list[_Contact]:
        pieces, out = self.pieces, []
        position, radius = pieces.position, pieces.radius
        half = self.half_size
        for axis in (0, 1):
            for sign in (1.0, -1.0):
                depth = sign * position[:, axis] + radius - half[axis]
                for i in np.flatnonzero(depth > 0):
                    normal = np.zeros(2)
                    normal[axis] = -sign
                    point = position[i] - normal * radius[i]
                    out.append(_Contact(int(i), None, normal, float(depth[i]), point))
        for shape in self.solid:
            gap = np.hypot(position[:, 0] - shape.center[0], position[:, 1] - shape.center[1])
            for i in np.flatnonzero(gap < shape.radius + radius):
                distance, normal, point = shape.signed_distance(position[i])
                if distance < radius[i]:
                    out.append(_Contact(int(i), None, normal, radius[i] - distance, point))
        return out

    def _piece_pairs(self) -> list[_Contact]:
        pieces = self.pieces
        if len(pieces) < 2:
            return []
        diff = pieces.position[:, None, :] - pieces.position[None, :, :]
        dist = np.hypot(diff[..., 0], diff[..., 1])
        reach = pieces.radius[:, None] + pieces.radius[None, :]
        out = []
        for a, b in zip(*np.nonzero(np.triu(dist < reach, k=1)), strict=True):
            d = dist[a, b]
            normal = diff[a, b] / d if d > 1e-12 else np.array([1.0, 0.0])
            point = pieces.position[b] + normal * pieces.radius[b]
            out.append(_Contact(int(a), int(b), normal, reach[a, b] - d, point))
        return out

    def _robot_pieces(self, robot: Robot) -> list[_Contact]:
        if robot.outline is not None:
            return self._shape_pieces(robot)
        pieces, out = self.pieces, []
        footprint = _footprint(robot)
        near = np.hypot(*(pieces.position - footprint.center).T) < footprint.radius + pieces.radius
        for i in np.flatnonzero(near):
            r = pieces.radius[i]
            distance, normal, point = footprint.signed_distance(pieces.position[i])
            if distance < r:
                out.append(_Contact(int(i), -1, normal, r - distance, point, robot=robot))
        return out

    def _shape_pieces(self, robot: Robot) -> list[_Contact]:
        """A ``body.shape``'s contacts with pieces: each piece of its edge a piece reaches
        into (two, a piece in a notch)."""
        pieces, cg = self.pieces, robot.cg_position
        gap = np.hypot(*(pieces.position - cg).T)
        near = np.flatnonzero(gap < robot.footprint_radius + pieces.radius)
        if not len(near):
            return []
        c, s = math.cos(robot.heading), math.sin(robot.heading)
        rotate = np.array([[c, s], [-s, c]])
        local = (pieces.position[near] - cg) @ rotate.T
        return [
            _Contact(int(near[k]), -1, normal @ rotate, depth, cg + point @ rotate, robot=robot)
            for k, depth, normal, point in robot.outline.discs(local, pieces.radius[near])
        ]

    def _relative_velocity(self, c: _Contact) -> np.ndarray:
        v = self.pieces.velocity[c.a]
        if c.b is None:
            return v
        if c.b == -1:
            return v - _point_velocity(c.robot, c.point)
        return v - self.pieces.velocity[c.b]

    def _solve(self, c: _Contact) -> None:
        pieces = self.pieces
        n = c.normal
        t = np.array([-n[1], n[0]])
        k_n = c.inv_mass
        k_t = c.inv_mass
        if c.b is not None and c.b >= 0:
            k_n += 1.0 / pieces.mass[c.b]
            k_t = k_n
        elif c.b == -1:
            k_n += _robot_inverse_mass(c.robot, c.point, n)
            k_t += _robot_inverse_mass(c.robot, c.point, t)
        if k_n <= 0:
            return
        vrel = self._relative_velocity(c)
        total = max(c.impulse + (c.target - vrel @ n) / k_n, 0.0)
        self._apply(c, n, total - c.impulse)
        c.impulse = total
        if k_t <= 0:
            return
        bound = self.spec.wall_friction * total
        friction = min(max(c.friction - (self._relative_velocity(c) @ t) / k_t, -bound), bound)
        self._apply(c, t, friction - c.friction)
        c.friction = friction

    def _apply(self, c: _Contact, direction: np.ndarray, amount: float) -> None:
        """An impulse ``amount`` along ``direction`` on piece a, and its reaction on b."""
        if not amount:
            return
        pieces = self.pieces
        pieces.velocity[c.a] += direction * amount * c.inv_mass
        if c.b is None:
            return
        if c.b == -1:
            _push_robot(c.robot, c.point, -direction * amount)
        else:
            pieces.velocity[c.b] -= direction * amount / pieces.mass[c.b]

    def _separate(self, fixed, pairs, robot_contacts) -> None:
        pieces = self.pieces
        for c in fixed:
            pieces.position[c.a] += c.normal * c.depth
        for c in pairs:
            ma, mb = pieces.mass[c.a], pieces.mass[c.b]
            pieces.position[c.a] += c.normal * c.depth * mb / (ma + mb)
            pieces.position[c.b] -= c.normal * c.depth * ma / (ma + mb)
        moved: dict[int, np.ndarray] = {}  # piece: out of the robot (a shape may touch it twice)
        for c in robot_contacts:
            shift = moved.get(c.a)
            if shift is None:
                moved[c.a] = c.normal * c.depth
            elif (remaining := c.depth - shift @ c.normal) > 0:
                moved[c.a] = shift + c.normal * remaining
        for i, shift in moved.items():
            pieces.position[i] += shift
        if robot_contacts:
            again = self._fixed_contacts()  # pieces pushed into walls or obstacles go back...
            for c in again:
                pieces.position[c.a] += c.normal * c.depth
            for robot in self.robots:  # ...and push the robot back instead
                shift = np.zeros(2)
                for c in self._robot_pieces(robot):
                    remaining = c.depth - shift @ (-c.normal)
                    if remaining > 0:
                        shift -= c.normal * remaining
                robot.cg_position += shift

    # --- sensing ----------------------------------------------------------------------------

    def ray(
        self, origin, angle: float, *, pieces: bool = True, height: float | None = None
    ) -> float | None:
        """Distance (m) along a ray to the first wall, obstacle or (optionally) piece.
        A ray ``height`` m above the floor passes over obstacles no taller than that."""
        from vexsim.devices.devices import ray_to_walls

        hit = ray_to_walls(origin[0], origin[1], angle, *self.half_size)
        if hit is None:
            return None
        best = hit / 1000.0
        o = np.asarray(origin, dtype=float)
        d = np.array([math.cos(angle), math.sin(angle)])
        for shape in self.obstacles:
            if height is not None and shape.height is not None and shape.height <= height:
                continue
            t = shape.ray(o, d)
            if t is not None and t < best:
                best = t
        if pieces:
            for center, r in zip(self.pieces.position, self.pieces.radius, strict=True):
                t = Shape(True, center, 0.0, (r, r)).ray(o, d)
                if t is not None and t < best:
                    best = t
        return best


def _no_pieces() -> Pieces:
    empty = np.zeros(0)
    return Pieces(np.zeros((0, 2)), np.zeros((0, 2)), empty, empty, empty, empty, [], [])


def _footprint(robot: Robot) -> Shape:
    x, y, heading = robot.pose
    length, width = (in_to_m(v) for v in robot.config.body.footprint_in)
    return Shape(False, np.array([x, y]), heading, (length / 2, width / 2))


def _point_velocity(robot: Robot, point: np.ndarray) -> np.ndarray:
    """Field-frame velocity of a point (field frame) on the robot."""
    c, s = math.cos(robot.heading), math.sin(robot.heading)
    d = point - robot.cg_position
    rx, ry = c * d[0] + s * d[1], -s * d[0] + c * d[1]
    u, v, w = robot.qdot[:3]
    bu, bv = u - w * ry, v + w * rx
    return np.array([c * bu - s * bv, s * bu + c * bv])


def _robot_inverse_mass(robot: Robot, point: np.ndarray, direction: np.ndarray) -> float:
    d = point - robot.cg_position
    moment = d[0] * direction[1] - d[1] * direction[0]
    return 1.0 / robot.mass + moment * moment / robot.yaw_inertia


def _push_robot(robot: Robot, point: np.ndarray, impulse: np.ndarray) -> None:
    """Apply a field-frame impulse at a field-frame point to the robot's body velocity."""
    c, s = math.cos(robot.heading), math.sin(robot.heading)
    jx, jy = c * impulse[0] + s * impulse[1], -s * impulse[0] + c * impulse[1]
    d = point - robot.cg_position
    rx, ry = c * d[0] + s * d[1], -s * d[0] + c * d[1]
    robot.qdot[0] += jx / robot.mass
    robot.qdot[1] += jy / robot.mass
    robot.qdot[2] += (rx * jy - ry * jx) / robot.yaw_inertia

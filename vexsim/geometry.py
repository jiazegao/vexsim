"""Plane geometry of robot shapes: the union of rectangles, circles and polygons.

A robot's ``body.shape`` is the union of its parts: where parts overlap they merge, and
only the union's edge touches the walls, field elements and pieces. ``Outline`` finds that
edge exactly, as pieces of the parts' own edges (straight segments and circular arcs, with
the shape on their left: counter-clockwise around the shape, clockwise around any hole the
parts enclose), and answers what the physics and the config checks ask of it: whether a
point is inside, the nearest point of the edge, how far the shape reaches, its area and
its moments.

Any length unit works, the same throughout; angles are radians, counter-clockwise.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cached_property

import numpy as np

Point = tuple[float, float]
TAU = 2.0 * math.pi
_GAUSS = np.polynomial.legendre.leggauss(16)


def _map(p: Sequence[float], scale: float, offset: Sequence[float]) -> Point:
    return (p[0] * scale + offset[0], p[1] * scale + offset[1])


def signed_area(points: Sequence[Sequence[float]]) -> float:
    """Shoelace area: positive when the points go counter-clockwise."""
    total = 0.0
    for (x0, y0), (x1, y1) in zip(points, [*points[1:], points[0]], strict=True):
        total += x0 * y1 - x1 * y0
    return total / 2.0


@dataclass(frozen=True)
class Circle:
    center: Point
    radius: float

    def contains(self, p: Sequence[float]) -> bool:
        return math.hypot(p[0] - self.center[0], p[1] - self.center[1]) < self.radius

    def mapped(self, scale: float, offset: Sequence[float]) -> Circle:
        return Circle(_map(self.center, scale, offset), self.radius * scale)


@dataclass(frozen=True)
class Polygon:
    """A simple polygon (its edges don't cross), its points counter-clockwise."""

    points: tuple[Point, ...]

    @classmethod
    def of(cls, points: Iterable[Sequence[float]]) -> Polygon:
        """The polygon through ``points``, given in either direction."""
        pts = tuple((float(x), float(y)) for x, y in points)
        return cls(pts if signed_area(pts) >= 0 else pts[::-1])

    @classmethod
    def rect(cls, center: Sequence[float], size: Sequence[float], heading: float = 0.0) -> Polygon:
        """A rectangle: ``size`` is its length along ``heading`` by its width across."""
        c, s = math.cos(heading), math.sin(heading)
        hx, hy = size[0] / 2, size[1] / 2
        corners = ((hx, hy), (-hx, hy), (-hx, -hy), (hx, -hy))
        return cls(
            tuple((center[0] + c * u - s * v, center[1] + s * u + c * v) for u, v in corners)
        )

    def edges(self) -> Iterable[tuple[Point, Point]]:
        return zip(self.points, self.points[1:] + self.points[:1], strict=True)

    def contains(self, p: Sequence[float]) -> bool:
        """Crossing number: a point exactly on the edge may count either way."""
        x, y = p
        inside = False
        for (x0, y0), (x1, y1) in self.edges():
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
        return inside

    def mapped(self, scale: float, offset: Sequence[float]) -> Polygon:
        return Polygon(tuple(_map(p, scale, offset) for p in self.points))


Part = Circle | Polygon


@dataclass(frozen=True)
class Segment:
    """A straight piece of the edge, from ``a`` to ``b``, the shape on its left."""

    a: Point
    b: Point

    @property
    def normal(self) -> Point:
        """Outward: to the right of the way it goes."""
        dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
        length = math.hypot(dx, dy)
        return (dy / length, -dx / length)


@dataclass(frozen=True)
class Arc:
    """A piece of a circle's edge: counter-clockwise from ``start`` through ``sweep``."""

    center: Point
    radius: float
    start: float
    sweep: float

    def at(self, angle: float) -> Point:
        return (
            self.center[0] + self.radius * math.cos(angle),
            self.center[1] + self.radius * math.sin(angle),
        )

    def covers(self, angle: float) -> bool:
        return (angle - self.start) % TAU <= self.sweep + 1e-12

    @property
    def ends(self) -> tuple[Point, Point]:
        return self.at(self.start), self.at(self.start + self.sweep)


class Outline:
    """The union of ``parts``, and its edge."""

    def __init__(self, parts: Sequence[Part]):
        if not parts:
            raise ValueError("a shape needs at least one part")
        self.parts = tuple(parts)
        coords = [abs(v) for p in self.parts for v in _coords(p)]
        self.size = max(coords) or 1.0  # how big the numbers are: tolerances scale with it
        self.segments, self.arcs = _edge(self.parts, 1e-9 * self.size)
        # each piece of the edge in a circle around it: most never come near a query point
        self._bounds = [
            ((s.a[0] + s.b[0]) / 2, (s.a[1] + s.b[1]) / 2, math.dist(s.a, s.b) / 2)
            for s in self.segments
        ] + [(a.center[0], a.center[1], a.radius) for a in self.arcs]
        self._ends = [(s.a, s.b) for s in self.segments]
        self._ends += [a.ends if a.sweep < TAU else () for a in self.arcs]

    def mapped(self, scale: float = 1.0, offset: Sequence[float] = (0.0, 0.0)) -> Outline:
        """The same shape, every length times ``scale``, then moved by ``offset``."""
        return Outline([part.mapped(scale, offset) for part in self.parts])

    # --- inside and nearest ------------------------------------------------------------------

    def contains(self, p: Sequence[float]) -> bool:
        return any(part.contains(p) for part in self.parts)

    def signed_distance(self, point: Sequence[float]) -> tuple[float, np.ndarray, np.ndarray]:
        """(distance, outward normal, nearest point of the edge) for a point; negative
        inside. The normal is the edge's, at that point: which way out."""
        x, y = float(point[0]), float(point[1])
        distance, piece, qx, qy, _ = min(self._reached(x, y, math.inf))
        inside = self.contains((x, y))
        normal = self._out(x, y, qx, qy, distance, piece, inside)
        return (-distance if inside else distance), normal, np.array([qx, qy])

    def discs(
        self, centers: np.ndarray, radii: np.ndarray | float
    ) -> list[tuple[int, float, np.ndarray, np.ndarray]]:
        """Where discs overlap the shape: (disc, depth, normal, point) for each piece of the
        edge a disc reaches into, the point being the piece's nearest to the disc's center and
        the normal the edge's there, pointing out of the shape (the way the disc must go). A
        disc centered inside the shape gets one, through the nearest point of the edge.
        Radius 0 finds the points inside the shape."""
        centers = np.asarray(centers, dtype=float).reshape(-1, 2)
        radii = np.broadcast_to(np.asarray(radii, dtype=float), (len(centers),))
        found = []
        same = 1e-9 * self.size
        for i, ((x, y), radius) in enumerate(zip(centers.tolist(), radii.tolist(), strict=True)):
            if self.contains((x, y)):
                distance, piece, qx, qy, _ = min(self._reached(x, y, math.inf))
                normal = self._out(x, y, qx, qy, distance, piece, True)
                found.append((i, radius + distance, normal, np.array([qx, qy])))
                continue
            hits = sorted(self._reached(x, y, radius))
            seen: list[tuple[float, float]] = []
            for distance, piece, qx, qy, end in hits:
                if any(abs(qx - sx) + abs(qy - sy) < same for sx, sy in seen):
                    continue  # two pieces' shared end: one contact
                if end and any(
                    other != piece
                    and near < distance - same
                    and any(abs(qx - ex) + abs(qy - ey) < same for ex, ey in self._ends[other])
                    for near, other, *_ in hits
                ):
                    continue  # the piece on through this end comes nearer: the contact is there
                seen.append((qx, qy))
                normal = self._out(x, y, qx, qy, distance, piece, False)
                found.append((i, radius - distance, normal, np.array([qx, qy])))
        return found

    def _reached(
        self, x: float, y: float, reach: float
    ) -> list[tuple[float, int, float, float, bool]]:
        """(distance, piece, nearest point, whether that's one of the piece's ends) for each
        piece of the edge closer than ``reach`` to (x, y)."""
        found = []
        segments = len(self.segments)
        for j, (bx, by, radius) in enumerate(self._bounds):
            if reach < math.inf and (x - bx) ** 2 + (y - by) ** 2 > (radius + reach) ** 2:
                continue
            if j < segments:
                (ax, ay), (cx, cy) = self.segments[j].a, self.segments[j].b
                dx, dy = cx - ax, cy - ay
                t = min(max(((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy), 0.0), 1.0)
                qx, qy = ax + t * dx, ay + t * dy
                end = t in (0.0, 1.0)
            else:
                arc = self.arcs[j - segments]
                vx, vy = x - bx, y - by
                length = math.hypot(vx, vy)
                end = not (length > 0 and arc.covers(math.atan2(vy, vx)))
                if not end:
                    qx, qy = bx + vx / length * radius, by + vy / length * radius
                else:
                    (ex, ey), (fx, fy) = arc.ends
                    nearer = (ex - x) ** 2 + (ey - y) ** 2 <= (fx - x) ** 2 + (fy - y) ** 2
                    qx, qy = (ex, ey) if nearer else (fx, fy)
            distance = math.hypot(x - qx, y - qy)
            if distance < reach:
                found.append((distance, j, qx, qy, end))
        return found

    def _out(
        self, x: float, y: float, qx: float, qy: float, distance: float, piece: int, inside: bool
    ) -> np.ndarray:
        """The edge's outward normal at (qx, qy), the nearest point to (x, y)."""
        if distance > 1e-12 * self.size:
            sign = 1.0 if inside else -1.0
            return np.array([(qx - x) * sign / distance, (qy - y) * sign / distance])
        if piece < len(self.segments):
            return np.array(self.segments[piece].normal)
        arc = self.arcs[piece - len(self.segments)]
        return np.array([(qx - arc.center[0]) / arc.radius, (qy - arc.center[1]) / arc.radius])

    # --- extent ------------------------------------------------------------------------------

    @cached_property
    def corners(self) -> np.ndarray:
        """Where pieces of the edge end (each once), (n, 2): with the arcs, everything that
        can reach furthest in a direction."""
        ends = [p for s in self.segments for p in (s.a, s.b)]
        ends += [p for a in self.arcs if a.sweep < TAU for p in a.ends]
        unique: list[Point] = []
        for p in ends:
            if not any(abs(p[0] - u[0]) + abs(p[1] - u[1]) < 1e-9 * self.size for u in unique):
                unique.append(p)
        return np.array(unique, dtype=float).reshape(-1, 2)

    def reach(self, origin: Sequence[float] = (0.0, 0.0)) -> float:
        """How far the shape reaches from ``origin``."""
        ox, oy = origin
        far = max((math.hypot(x - ox, y - oy) for x, y in self.corners), default=0.0)
        for arc in self.arcs:
            dx, dy = arc.center[0] - ox, arc.center[1] - oy
            if arc.covers(math.atan2(dy, dx)) or (dx == 0 and dy == 0):
                far = max(far, math.hypot(dx, dy) + arc.radius)
        return far

    def extreme(self, direction: Sequence[float]) -> float:
        """How far the shape reaches along a unit ``direction``: the most of p . direction."""
        dx, dy = direction
        far = max((x * dx + y * dy for x, y in self.corners), default=-math.inf)
        angle = math.atan2(dy, dx)
        for arc in self.arcs:
            if arc.covers(angle):
                far = max(far, arc.center[0] * dx + arc.center[1] * dy + arc.radius)
        return far

    def front(self) -> float:
        """Where the +x axis from the origin leaves the shape (or, if it misses the shape,
        how far forward the shape reaches)."""
        crossings = []
        for seg in self.segments:
            (x0, y0), (x1, y1) = seg.a, seg.b
            if (y0 > 0) != (y1 > 0):
                crossings.append(x0 + (0 - y0) * (x1 - x0) / (y1 - y0))
        for arc in self.arcs:
            cx, cy = arc.center
            if abs(cy) < arc.radius:
                half = math.sqrt(arc.radius**2 - cy * cy)
                crossings += [
                    x for x in (cx - half, cx + half) if arc.covers(math.atan2(-cy, x - cx))
                ]
        ahead = [x for x in crossings if x >= 0]
        return max(ahead) if ahead else self.bounds[2]

    @cached_property
    def bounds(self) -> tuple[float, float, float, float]:
        """(min x, min y, max x, max y)."""
        points = [tuple(p) for p in self.corners]
        for arc in self.arcs:
            points += [
                arc.at(a) for a in (0.0, math.pi / 2, math.pi, 1.5 * math.pi) if arc.covers(a)
            ]
        xs, ys = [float(p[0]) for p in points], [float(p[1]) for p in points]
        return min(xs), min(ys), max(xs), max(ys)

    # --- area --------------------------------------------------------------------------------

    @cached_property
    def moments(self) -> tuple[float, Point, float]:
        """Area, centroid and polar second moment about the centroid (∫r² dA), from the
        edge (Green's theorem, each piece with the triangle or sector it makes with the
        origin)."""
        area = sx = sy = polar = 0.0
        for seg in self.segments:
            (x0, y0), (x1, y1) = seg.a, seg.b
            cross = x0 * y1 - x1 * y0
            area += cross / 2
            sx += (x0 + x1) * cross / 6
            sy += (y0 + y1) * cross / 6
            polar += (x0 * x0 + x0 * x1 + x1 * x1 + y0 * y0 + y0 * y1 + y1 * y1) * cross / 12
        nodes, weights = _GAUSS
        for arc in self.arcs:
            steps = max(1, math.ceil(arc.sweep / (math.pi / 4)))
            for k in range(steps):
                lo = arc.start + arc.sweep * k / steps
                half = arc.sweep / steps / 2
                theta = lo + half * (nodes + 1)
                x = arc.center[0] + arc.radius * np.cos(theta)
                y = arc.center[1] + arc.radius * np.sin(theta)
                w = arc.radius * (arc.center[0] * np.cos(theta) + arc.center[1] * np.sin(theta))
                w = (w + arc.radius**2) * weights * half  # (x y' - y x') dθ
                area += float(w.sum()) / 2
                sx += float((x * w).sum()) / 3
                sy += float((y * w).sum()) / 3
                polar += float(((x * x + y * y) * w).sum()) / 4
        if area <= 0:
            return 0.0, (0.0, 0.0), 0.0
        cx, cy = sx / area, sy / area
        return area, (cx, cy), polar - area * (cx * cx + cy * cy)

    @property
    def area(self) -> float:
        return self.moments[0]

    # --- drawing -----------------------------------------------------------------------------

    def loops(self, step: float = math.radians(3)) -> list[list[Point]]:
        """The edge as closed loops of points (arcs every ``step`` radians at most), the
        shape on their left: fill them together with the nonzero rule and holes stay empty."""
        pieces = [[s.a, s.b] for s in self.segments]
        for arc in self.arcs:
            n = max(2, math.ceil(arc.sweep / step))
            pieces.append([arc.at(arc.start + arc.sweep * k / n) for k in range(n + 1)])
        near = 1e-6 * self.size
        loops, left = [], list(range(len(pieces)))
        while left:
            chain = list(pieces[left.pop(0)])
            while True:
                x, y = chain[-1]
                k = next(
                    (k for k in left if abs(pieces[k][0][0] - x) + abs(pieces[k][0][1] - y) < near),
                    None,
                )
                if k is None:
                    break
                left.remove(k)
                chain += pieces[k][1:]
            closed = len(chain) > 2 and math.dist(chain[0], chain[-1]) < near
            if closed:
                chain.pop()
            loops.append(_straighten(chain, closed, near))
        return loops

    # --- overlap -----------------------------------------------------------------------------

    def overlaps(self, polygon: Polygon) -> bool:
        """Whether the shape and a convex polygon share some area (touching isn't sharing:
        shrink the polygon for a tolerance)."""
        for seg in self.segments:
            if _enters(seg.a, seg.b, polygon):
                return True
        for arc in self.arcs:
            if any(_strictly_inside(p, polygon) for p in arc.ends):
                return True
            cx, cy = arc.center
            for p, q in polygon.edges():
                for t in _cuts(p, q, Circle(arc.center, arc.radius)):
                    if 0 <= t <= 1:
                        x, y = _lerp(p, q, t)
                        if arc.covers(math.atan2(y - cy, x - cx)):
                            return True
        # no edge of the shape goes into the polygon: it's all inside the shape, or outside
        return self.contains(_anywhere(polygon))

    # --- parts -------------------------------------------------------------------------------

    def groups(self) -> list[list[int]]:
        """The parts in groups that touch or overlap each other (one group: one piece)."""
        group = list(range(len(self.parts)))

        def root(i: int) -> int:
            while group[i] != i:
                i = group[i]
            return i

        for i, a in enumerate(self.parts):
            for j in range(i):
                if root(i) != root(j) and _touch(a, self.parts[j]):
                    group[root(i)] = root(j)
        found: dict[int, list[int]] = {}
        for i in range(len(self.parts)):
            found.setdefault(root(i), []).append(i)
        return list(found.values())


def _straighten(points: list[Point], closed: bool, near: float) -> list[Point]:
    """``points`` without those in the middle of a straight run (where one part's edge
    carries on along another's)."""
    n = len(points)
    keep = []
    for k, p in enumerate(points):
        if not closed and k in (0, n - 1):
            keep.append(p)
            continue
        a, b = points[k - 1], points[(k + 1) % n]
        turns = abs(_orient(a, p, b)) > near * math.dist(a, b)
        back = (b[0] - p[0]) * (p[0] - a[0]) + (b[1] - p[1]) * (p[1] - a[1]) <= 0
        if turns or back:
            keep.append(p)
    return keep if len(keep) >= 3 or not closed else points


# --- the edge ----------------------------------------------------------------------------------


def _coords(part: Part) -> list[float]:
    if isinstance(part, Circle):
        return [part.center[0], part.center[1], part.radius]
    return [v for p in part.points for v in p]


def _edge(parts: Sequence[Part], eps: float) -> tuple[list[Segment], list[Arc]]:
    """The union's edge: every piece of a part's edge between two places where another
    part's edge meets it, kept if it's on the outside (see ``_outer``)."""
    segments: list[Segment] = []
    arcs: list[Arc] = []
    for i, part in enumerate(parts):
        others = [q for j, q in enumerate(parts) if j != i]
        if isinstance(part, Polygon):
            for a, b in part.edges():
                if a == b:
                    continue
                cuts = sorted({0.0, 1.0, *(t for q in others for t in _cuts(a, b, q) if 0 < t < 1)})
                normal = Segment(a, b).normal
                kept: list[list[float]] = []
                for t0, t1 in zip(cuts, cuts[1:], strict=False):
                    if t1 - t0 < 1e-12:
                        continue
                    if _outer(i, _lerp(a, b, (t0 + t1) / 2), normal, parts, eps):
                        if kept and kept[-1][1] == t0:
                            kept[-1][1] = t1
                        else:
                            kept.append([t0, t1])
                segments += [Segment(_lerp(a, b, t0), _lerp(a, b, t1)) for t0, t1 in kept]
            continue
        cuts = sorted({angle % TAU for q in others for angle in _circle_cuts(part, q)})
        whole = Arc(part.center, part.radius, 0.0, TAU)
        if not cuts:
            if _outer(i, whole.at(0.0), (1.0, 0.0), parts, eps):
                arcs.append(whole)
            continue
        kept = []
        for k, a0 in enumerate(cuts):
            a1 = cuts[k + 1] if k + 1 < len(cuts) else cuts[0] + TAU
            if a1 - a0 < 1e-12:
                continue
            mid = (a0 + a1) / 2
            if _outer(i, whole.at(mid), (math.cos(mid), math.sin(mid)), parts, eps):
                if kept and kept[-1][1] == a0:
                    kept[-1][1] = a1
                else:
                    kept.append([a0, a1])
        if len(kept) > 1 and kept[0][0] == cuts[0] and kept[-1][1] == cuts[0] + TAU:
            kept[0] = [kept.pop()[0], kept[0][1] + TAU]  # across angle 0: one piece
        arcs += [Arc(part.center, part.radius, a0, a1 - a0) for a0, a1 in kept]
    return segments, arcs


def _outer(i: int, point: Point, normal: Point, parts: Sequence[Part], eps: float) -> bool:
    """Whether this point of part i's edge is on the union's edge: nothing else covers the
    outside next to it, and no earlier part has the same edge (that one keeps it)."""
    out = (point[0] + eps * normal[0], point[1] + eps * normal[1])
    into = (point[0] - eps * normal[0], point[1] - eps * normal[1])
    for j, other in enumerate(parts):
        if j != i and (other.contains(out) or (j < i and other.contains(into))):
            return False
    return True


def _lerp(a: Point, b: Point, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _cuts(a: Point, b: Point, part: Part) -> list[float]:
    """Where the segment a-b meets the part's edge, as fractions of the way along it
    (where it runs along one of the part's edges, where that edge's ends are)."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    rr = rx * rx + ry * ry
    if isinstance(part, Circle):
        fx, fy = a[0] - part.center[0], a[1] - part.center[1]
        half_b = fx * rx + fy * ry
        disc = half_b * half_b - rr * (fx * fx + fy * fy - part.radius**2)
        if disc < 0:
            return []
        root = math.sqrt(disc)
        return [(-half_b - root) / rr, (-half_b + root) / rr]
    found = []
    length = math.sqrt(rr)
    for p, q in part.edges():
        sx, sy = q[0] - p[0], q[1] - p[1]
        px, py = p[0] - a[0], p[1] - a[1]
        denom = rx * sy - ry * sx
        if abs(denom) <= 1e-12 * length * math.hypot(sx, sy):  # parallel
            if abs(px * ry - py * rx) <= 1e-9 * length * max(length, 1.0):  # and on one line
                found += [(px * rx + py * ry) / rr, ((q[0] - a[0]) * rx + (q[1] - a[1]) * ry) / rr]
            continue
        u = (px * ry - py * rx) / denom
        if -1e-12 <= u <= 1 + 1e-12:
            found.append((px * sy - py * sx) / denom)
    return found


def _circle_cuts(circle: Circle, part: Part) -> list[float]:
    """Angles around the circle where the part's edge meets it."""
    cx, cy = circle.center
    if isinstance(part, Circle):
        dx, dy = part.center[0] - cx, part.center[1] - cy
        d = math.hypot(dx, dy)
        r1, r2 = circle.radius, part.radius
        if d == 0 or d > r1 + r2 or d < abs(r1 - r2):
            return []
        along = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
        spread = math.atan2(math.sqrt(max(r1 * r1 - along * along, 0.0)), along)
        base = math.atan2(dy, dx)
        return [base - spread, base + spread]
    found = []
    for p, q in part.edges():
        for t in _cuts(p, q, circle):
            if -1e-12 <= t <= 1 + 1e-12:
                x, y = _lerp(p, q, t)
                found.append(math.atan2(y - cy, x - cx))
    return found


def _enters(a: Point, b: Point, polygon: Polygon) -> bool:
    """Whether the segment a-b has points strictly inside a convex polygon (clipped to each
    edge's inner side in turn: Cyrus-Beck)."""
    lo, hi = 0.0, 1.0
    for p, q in polygon.edges():
        ex, ey = q[0] - p[0], q[1] - p[1]
        start = ex * (a[1] - p[1]) - ey * (a[0] - p[0])  # > 0: a is on the inner side
        rate = ex * (b[1] - a[1]) - ey * (b[0] - a[0])
        if rate == 0:
            if start <= 0:
                return False
            continue
        t = -start / rate
        if rate > 0:
            lo = max(lo, t)
        else:
            hi = min(hi, t)
        if lo >= hi:
            return False
    return True


def _strictly_inside(p: Point, polygon: Polygon) -> bool:
    """Inside a convex polygon, off its edges."""
    return all(
        (q[0] - o[0]) * (p[1] - o[1]) - (q[1] - o[1]) * (p[0] - o[0]) > 0
        for o, q in polygon.edges()
    )


def _touch(a: Part, b: Part) -> bool:
    """Whether two parts touch or overlap."""
    if isinstance(a, Polygon):
        if any(0 <= t <= 1 for p, q in a.edges() for t in _cuts(p, q, b)):
            return True
    elif _circle_cuts(a, b):
        return True
    return b.contains(_anywhere(a)) or a.contains(_anywhere(b))


def _anywhere(part: Part) -> Point:
    """A point inside the part."""
    if isinstance(part, Circle):
        return part.center
    (x0, y0), (x1, y1), (x2, y2) = part.points[:3]
    if part.contains(((x0 + x1 + x2) / 3, (y0 + y1 + y2) / 3)):
        return ((x0 + x1 + x2) / 3, (y0 + y1 + y2) / 3)
    for k in range(len(part.points)):  # a concave polygon: an ear's centroid
        (x0, y0), (x1, y1), (x2, y2) = (part.points[(k + j) % len(part.points)] for j in range(3))
        p = ((x0 + x1 + x2) / 3, (y0 + y1 + y2) / 3)
        if part.contains(p):
            return p
    return part.points[0]


# --- checking an outline -----------------------------------------------------------------------


def polygon_problem(points: Sequence[Sequence[float]]) -> str | None:
    """What's wrong with these points as an outline (a closed polygon that doesn't cross
    itself), if anything. Points are numbered from 0."""
    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    for k in range(n):
        if pts[k] == pts[(k + 1) % n]:
            return f"points {k} and {(k + 1) % n} are the same point"
    size = max(max(abs(v) for p in pts for v in p), 1e-12)
    if all(abs(_orient(pts[0], pts[1], p)) <= 1e-9 * size * size for p in pts[2:]):
        return "its points are all on one line"
    edges = [(pts[k], pts[(k + 1) % n]) for k in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            a, b = edges[i]
            c, d = edges[j]
            if j == i + 1 or (i == 0 and j == n - 1):  # neighbors share a point
                shared, other_a, other_b = (b, a, d) if j == i + 1 else (a, b, c)
                if _folds_back(shared, other_a, other_b):
                    k = j if j == i + 1 else i
                    return f"the edge from point {k} doubles back along the edge before it"
                continue
            if _segments_meet(a, b, c, d):
                return (
                    f"it crosses itself: the edge from point {i} to {(i + 1) % n} meets "
                    f"the edge from point {j} to {(j + 1) % n}"
                )
    if abs(signed_area(pts)) <= 1e-9 * size * size:
        return "it encloses no area"
    return None


def _orient(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _folds_back(shared: Point, a: Point, b: Point) -> bool:
    """Whether the edges shared-a and shared-b run along each other."""
    ax, ay = a[0] - shared[0], a[1] - shared[1]
    bx, by = b[0] - shared[0], b[1] - shared[1]
    cross = ax * by - ay * bx
    return abs(cross) <= 1e-12 * math.hypot(ax, ay) * math.hypot(bx, by) and ax * bx + ay * by > 0


def _segments_meet(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Whether the closed segments a-b and c-d have a point in common."""
    o1, o2, o3, o4 = _orient(a, b, c), _orient(a, b, d), _orient(c, d, a), _orient(c, d, b)
    if ((o1 > 0 and o2 < 0) or (o1 < 0 and o2 > 0)) and (
        (o3 > 0 and o4 < 0) or (o3 < 0 and o4 > 0)
    ):
        return True

    def on(p: Point, q: Point, r: Point, o: float) -> bool:  # r on segment p-q, given collinear
        return (
            o == 0
            and min(p[0], q[0]) <= r[0] <= max(p[0], q[0])
            and min(p[1], q[1]) <= r[1] <= max(p[1], q[1])
        )

    return on(a, b, c, o1) or on(a, b, d, o2) or on(c, d, a, o3) or on(c, d, b, o4)

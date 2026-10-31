"""Where each calibration test runs, on a field with its elements in place (phase 14.3).

A team calibrates on its own field with the season's elements in place, so the session's
tests can't count on open floor. ``make_plan(config, field)`` finds a spot for each:

- *Driving tests* (routine.drive_tests): each is simulated from rest over a spread of the
  parameters it measures (VARIANTS: the uncalibrated robot may roll further, stop sooner,
  slide or grip more than its config says). The robot's shape swept along every one of those
  paths, plus a margin, must stay clear of the walls and of every element, those robots can
  drive over included (a log needs flat tiles). The start is searched over the field, on a
  0.5 in grid with headings by 15 degrees, square to the walls preferred, by correlating the
  swept area with what's on the field (FFT); the spot with the most room wins, in the middle
  of it. A test with no room is slowed and shortened (SCALES), down to a floor; below that,
  the plan names what's in the way.
- *The push lane*: a straight lane 8, 7 or 6 ft long, for pushing the robot by hand.
- *Spins in place*: the slow spin (robots with tracking wheels) and 2 or 3 spots for the
  distance sweep (robots with distance sensors), each picked to see the walls and elements
  at distances the others don't.

Each spot says where to put the robot as distances from two walls, so a tape measure is
enough, and ``write_plan`` draws a map of each (matplotlib, if it's installed). The program
(calibration/program.py) stops a driving test that leaves its envelope: turning or rolling
its motors further than any of the plan's paths did, with some to spare.

Field frame: inches from the field's center, headings in degrees counter-clockwise from +x.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from vexsim.calibration.fit import WHEEL_PARAMS, current_value
from vexsim.calibration.routine import DRIVE_TESTS, Step, drive_tests, run_routine
from vexsim.config.field import FieldConfig, ObstacleConfig
from vexsim.config.robot import RobotConfig

MARGIN_IN = 6.0  # room kept between a driving test's swept area and the walls or elements
CELL_IN = 0.5  # the search grid
FINE_IN = 0.25  # how finely the robot's shape, and its paths, are sampled
SLACK_IN = 0.85  # how far the grid and the samples can be off: the search adds it to margins
SCALES = (1.0, 0.85, 0.7, 0.55)  # each driving test's speed (and drive time), down to a floor
HEADINGS = tuple(range(0, 360, 15))
PUSH_LENGTHS_IN = (96.0, 84.0, 72.0)  # 8, 7 and 6 ft
PUSH_MARGIN_IN = 3.0  # pushed by hand, slowly: less room is enough
SLOW_SPIN_TURNS = 5
IMU_STILL_S = 60
IMU_TURNS = 10
SPIN_DRIFT_IN = 3.0  # how far a robot turning in place may wander
SWEEPS = 3  # distance sweep spots, at most
SWEEP_STEP_DEG = 5.0
RANGE_MM = (20.0, 2000.0)  # what a distance sensor reads
BIN_MM = 100.0  # the sweep spots are picked to cover readings in bins this wide
ENVELOPE = (1.15, 20.0, 15.0)  # the paths' most motor travel and turn x 1.15, + 20, + 15 deg
WALLS = {
    "+x": "the +x wall (right on the map)",
    "-x": "the -x wall (left on the map)",
    "+y": "the +y wall (top of the map)",
    "-y": "the -y wall (bottom of the map)",
}


# --- the parameter spread ----------------------------------------------------------------


@dataclass(frozen=True)
class Variant:
    """A guess at how the uncalibrated robot differs from its config: factors on its wheels'
    rolling resistance, sideways (roller) friction and grip, its motors' speed, its mass."""

    name: str
    factors: Mapping[str, float]


VARIANTS = (
    Variant("as configured", {}),
    Variant(
        "rolls further", {"rolling": 0.6, "sideways": 0.7, "grip": 1.2, "motor": 1.1, "mass": 0.85}
    ),
    Variant("stops sooner", {"rolling": 1.5, "grip": 0.7, "motor": 0.9, "mass": 1.2}),
    Variant("slides more", {"rolling": 0.8, "sideways": 0.5, "grip": 0.6}),
    Variant("grips more", {"sideways": 1.6, "grip": 1.4}),
)
_KIND = {
    "rolling_resistance": "rolling",
    "lateral_mu": "sideways",
    "roller_mu": "sideways",
    "longitudinal_mu": "grip",
    "mu": "grip",
    "grip_mu": "grip",
}


def variant_robot(config: RobotConfig, variant: Variant) -> tuple[RobotConfig, dict[str, float]]:
    """A variant's robot config (its mass) and parameter overrides (the rest)."""
    factors, overrides = variant.factors, {}
    for wheel_type in sorted({w.type for w in config.drivetrain.wheels}):
        for name in WHEEL_PARAMS[wheel_type]:
            if _KIND[name] in factors:
                key = f"wheel.{wheel_type}.{name}"
                overrides[key] = current_value(config, key) * factors[_KIND[name]]
    if "motor" in factors:
        key = "motor.natural_free_rpm"
        overrides[key] = current_value(config, key) * factors["motor"]
    if "mass" in factors:
        body = config.body.model_copy(update={"mass_kg": config.body.mass_kg * factors["mass"]})
        config = config.model_copy(update={"body": body})
    return config, overrides


@dataclass
class Trial:
    """A driving test in one variant, started at the origin facing +x: the true pose every
    10 ms (x in, y in, heading deg), and the most any drive motor turned and the IMU read."""

    variant: str
    poses: np.ndarray
    motor_deg: float
    turn_deg: float | None  # None: the robot has no IMU


def simulate(job: tuple[RobotConfig, Variant, list[Step]]) -> Trial:
    """One driving test in one variant (a job for a process pool)."""
    config, variant, steps = job
    robot, overrides = variant_robot(config, variant)
    truth: list[tuple[float, float, float]] = []
    log = run_routine(robot, steps, overrides=overrides, truth=truth)
    motors = {abs(p) for g in config.drivetrain.gearing.values() for p in g.motors}
    motor_deg = max(_travel(log[f"m{p}_deg"]) for p in sorted(motors))
    imus = log.ports("imu")
    turn = max((_travel(log[f"imu{p}_deg"]) for p in imus), default=None)
    return Trial(variant.name, np.array(truth, dtype=float), motor_deg, turn)


def _travel(values: np.ndarray) -> float:
    known = values[np.isfinite(values)]
    return float(np.max(np.abs(known - known[0]))) if known.size else 0.0


# --- the field ---------------------------------------------------------------------------


class FieldMap:
    """The field on a grid of ``cell`` inch squares, and how far each square's center is from
    the nearest wall or element (negative inside one). Game pieces are left out: the session
    starts with them cleared away."""

    def __init__(self, field: FieldConfig, cell: float = CELL_IN):
        self.field, self.cell = field, cell
        self.half = (field.size_in[0] / 2, field.size_in[1] / 2)
        self.nx, self.ny = (math.ceil(s / cell - 1e-9) for s in field.size_in)
        self.xs = -self.half[0] + (np.arange(self.nx) + 0.5) * cell
        self.ys = -self.half[1] + (np.arange(self.ny) + 0.5) * cell
        grid = np.stack(np.meshgrid(self.xs, self.ys, indexing="ij"), axis=-1)
        self.distance = self.distances(grid)

    def _walls(self, points: np.ndarray) -> dict[str, np.ndarray]:
        x, y = points[..., 0], points[..., 1]
        hx, hy = self.half
        return {"+x": hx - x, "-x": x + hx, "+y": hy - y, "-y": y + hy}

    def distances(self, points: np.ndarray) -> np.ndarray:
        """How far points (..., 2) are from the nearest wall or element."""
        out = np.minimum.reduce(list(self._walls(points).values()))
        for obstacle in self.field.obstacles:
            out = np.minimum(out, element_distance(obstacle, points))
        return out

    def near(self, points: np.ndarray, within: float) -> list[str]:
        """The walls and elements closer than ``within`` to any of the points, nearest first."""
        found = []
        for wall, d in self._walls(points).items():
            found.append((float(d.min()), WALLS[wall]))
        for i, obstacle in enumerate(self.field.obstacles):
            name = obstacle.name or f"element {i + 1}"
            found.append((float(element_distance(obstacle, points).min()), name))
        return [name for d, name in sorted(found) if d < within]


def element_distance(obstacle: ObstacleConfig, points: np.ndarray) -> np.ndarray:
    """How far points (..., 2) are from an element's edge; negative inside it."""
    dx, dy = points[..., 0] - obstacle.pos_in[0], points[..., 1] - obstacle.pos_in[1]
    if obstacle.shape == "circle":
        return np.hypot(dx, dy) - obstacle.diameter_in / 2
    h = math.radians(obstacle.heading_deg)
    c, s = math.cos(h), math.sin(h)
    along = np.abs(dx * c + dy * s) - obstacle.size_in[0] / 2
    across = np.abs(-dx * s + dy * c) - obstacle.size_in[1] / 2
    outside = np.hypot(np.maximum(along, 0.0), np.maximum(across, 0.0))
    return outside + np.minimum(np.maximum(along, across), 0.0)


def ray_lengths(
    field: FieldConfig,
    origins: np.ndarray,
    angles: np.ndarray,
    heights: np.ndarray | None = None,
) -> np.ndarray:
    """How far (in) rays go to the first wall or element they meet, as ``Arena.ray`` has it
    (pieces left out): a ray ``heights`` in above the floor passes over elements no taller.
    Origins (n, 2) inside the walls, angles (n,) in radians, counter-clockwise from +x."""
    hx, hy = field.size_in[0] / 2, field.size_in[1] / 2
    ox, oy = origins[:, 0], origins[:, 1]
    dx, dy = np.cos(angles), np.sin(angles)
    with np.errstate(divide="ignore", invalid="ignore"):
        tx = np.where(dx > 1e-12, (hx - ox) / dx, np.where(dx < -1e-12, (-hx - ox) / dx, np.inf))
        ty = np.where(dy > 1e-12, (hy - oy) / dy, np.where(dy < -1e-12, (-hy - oy) / dy, np.inf))
    best = np.minimum(tx, ty)
    for obstacle in field.obstacles:
        seen = np.ones(len(ox), dtype=bool)
        if heights is not None and obstacle.height_in is not None:
            seen = ~(obstacle.height_in <= heights)
        t = _ray_into(obstacle, ox, oy, dx, dy)
        best = np.where(seen & (t < best), t, best)
    return best


def _ray_into(obstacle: ObstacleConfig, ox, oy, dx, dy) -> np.ndarray:
    px, py = ox - obstacle.pos_in[0], oy - obstacle.pos_in[1]
    if obstacle.shape == "circle":
        r = obstacle.diameter_in / 2
        b = px * dx + py * dy
        disc = b * b - (px * px + py * py - r * r)
        t = -b - np.sqrt(np.maximum(disc, 0.0))
        return np.where((disc >= 0) & (t >= 0), t, np.inf)
    h = math.radians(obstacle.heading_deg)
    c, s = math.cos(h), math.sin(h)
    near = np.full(len(ox), -np.inf)
    far = np.full(len(ox), np.inf)
    for p, d, half in (
        (c * px + s * py, c * dx + s * dy, obstacle.size_in[0] / 2),
        (-s * px + c * py, -s * dx + c * dy, obstacle.size_in[1] / 2),
    ):
        flat = np.abs(d) < 1e-12
        with np.errstate(divide="ignore", invalid="ignore"):
            t1, t2 = (-half - p) / d, (half - p) / d
        inside = np.abs(p) <= half
        lo = np.where(flat, np.where(inside, -np.inf, np.inf), np.minimum(t1, t2))
        hi = np.where(flat, np.where(inside, np.inf, -np.inf), np.maximum(t1, t2))
        near, far = np.maximum(near, lo), np.minimum(far, hi)
    return np.where((near <= far) & (far >= 0), np.maximum(near, 0.0), np.inf)


# --- swept areas ---------------------------------------------------------------------------


def shape_samples(config: RobotConfig) -> tuple[np.ndarray, np.ndarray]:
    """Points (in, robot frame) every FINE_IN over the robot's shape, and along its edge."""
    outline = config.body.outline
    x0, y0, x1, y1 = outline.bounds
    xs = np.arange(x0 + FINE_IN / 2, x1, FINE_IN)
    ys = np.arange(y0 + FINE_IN / 2, y1, FINE_IN)
    inside = np.array([(x, y) for x in xs for y in ys if outline.contains((x, y))]).reshape(-1, 2)
    edge = []
    for loop in outline.loops():
        for a, b in zip(loop, [*loop[1:], loop[0]], strict=True):
            n = max(1, math.ceil(math.dist(a, b) / FINE_IN))
            edge += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
    return inside, np.array(edge, dtype=float).reshape(-1, 2)


def _moved(points: np.ndarray, pose: Sequence[float]) -> np.ndarray:
    """Points (robot frame) with the robot at pose (x, y, heading deg)."""
    h = math.radians(pose[2])
    c, s = math.cos(h), math.sin(h)
    return points @ np.array([[c, s], [-s, c]]) + (pose[0], pose[1])


def _dense(poses: np.ndarray, reach: float) -> np.ndarray:
    """A path's poses with more in between, so no point of the robot moves more than FINE_IN
    from one to the next."""
    out = [poses[:1]]
    for a, b in zip(poses[:-1], poses[1:], strict=True):
        move = math.hypot(b[0] - a[0], b[1] - a[1]) + reach * math.radians(abs(b[2] - a[2]))
        n = max(1, math.ceil(move / FINE_IN))
        f = (np.arange(1, n + 1) / n)[:, None]
        out.append(a + (b - a) * f)
    return np.concatenate(out)


def swept(config: RobotConfig, paths: Iterable[np.ndarray]) -> np.ndarray:
    """Every place (points FINE_IN apart, start frame) the robot's shape covers along paths
    of (x, y, heading deg) poses: the shape where it starts and ends, and its edge on the
    way (whatever the robot covers on the way, its edge passes over)."""
    inside, edge = shape_samples(config)
    reach = config.body.outline.reach()
    cells = []
    for poses in paths:
        cells.append(_cells(_moved(inside, poses[0])))
        cells.append(_cells(_moved(inside, poses[-1])))
        dense = _dense(np.asarray(poses, dtype=float), reach)
        for chunk in range(0, len(dense), 256):
            part = dense[chunk : chunk + 256]
            h = np.radians(part[:, 2])
            c, s = np.cos(h)[:, None], np.sin(h)[:, None]
            x = part[:, :1] + c * edge[:, 0] - s * edge[:, 1]
            y = part[:, 1:2] + s * edge[:, 0] + c * edge[:, 1]
            cells.append(_cells(np.stack([x.ravel(), y.ravel()], axis=-1)))
    return np.unique(np.concatenate(cells), axis=0) * FINE_IN


def _cells(points: np.ndarray) -> np.ndarray:
    return np.unique(np.round(points / FINE_IN).astype(np.int64), axis=0)


def disc(radius: float) -> np.ndarray:
    """Points FINE_IN apart over a disc around the origin: what a robot turning in place
    covers."""
    r = np.arange(-radius, radius + FINE_IN / 2, FINE_IN)
    grid = np.stack(np.meshgrid(r, r, indexing="ij"), axis=-1).reshape(-1, 2)
    return grid[np.hypot(grid[:, 0], grid[:, 1]) <= radius]


def lane(config: RobotConfig, length: float) -> np.ndarray:
    """What the robot covers pushed ``length`` in straight ahead."""
    return swept(config, [np.array([[0.0, 0.0, 0.0], [length, 0.0, 0.0]])])


# --- the search ----------------------------------------------------------------------------


class Search:
    """Where an area (points, start frame) fits on a FieldMap: for every start cell and
    heading, how many of the cells it covers are too near a wall or element: a correlation,
    done with FFTs."""

    def __init__(self, fmap: FieldMap, points: np.ndarray):
        self.fmap, self.points = fmap, points
        self.r = math.ceil(float(np.hypot(points[:, 0], points[:, 1]).max()) / fmap.cell) + 1
        self.size = (fmap.nx + 4 * self.r, fmap.ny + 4 * self.r)
        self._kernels: dict[float, np.ndarray] = {}
        self._blocked: dict[float, np.ndarray] = {}

    def _kernel(self, heading: float) -> np.ndarray:
        if heading not in self._kernels:
            r = self.r
            kernel = np.zeros((2 * r + 1, 2 * r + 1))
            cells = np.unique(
                np.round(_moved(self.points, (0, 0, heading)) / self.fmap.cell).astype(int),
                axis=0,
            )
            kernel[r - cells[:, 0], r - cells[:, 1]] = 1.0  # flipped: a convolution
            self._kernels[heading] = np.fft.rfft2(kernel, s=self.size)
        return self._kernels[heading]

    def _too_near(self, margin: float) -> np.ndarray:
        if margin not in self._blocked:
            fmap, r = self.fmap, self.r
            padded = np.ones((fmap.nx + 2 * r, fmap.ny + 2 * r))  # past the walls
            padded[r : r + fmap.nx, r : r + fmap.ny] = fmap.distance < margin + SLACK_IN
            self._blocked[margin] = np.fft.rfft2(padded, s=self.size)
        return self._blocked[margin]

    def counts(self, heading: float, margin: float) -> np.ndarray:
        """For each start cell (nx, ny), how many covered cells are within ``margin``."""
        full = np.fft.irfft2(self._too_near(margin) * self._kernel(heading), s=self.size)
        r = self.r
        return full[2 * r : 2 * r + self.fmap.nx, 2 * r : 2 * r + self.fmap.ny]

    def fits(self, heading: float, margin: float) -> np.ndarray:
        return self.counts(heading, margin) < 0.5

    def best(
        self, margin: float, headings: Sequence[float] = HEADINGS
    ) -> tuple[float, float, float] | None:
        """The start (x, y, heading) with the most room, at least ``margin``: square to the
        walls if any square heading fits, in the middle of the roomiest place. None if
        nothing fits."""
        square = [h for h in headings if h % 90 == 0]
        for group in (square, [h for h in headings if h % 90]):
            masks = {h: m for h in group if (m := self.fits(h, margin)).any()}
            if masks:
                break
        else:
            return None

        def fitting(extra: float) -> dict[float, np.ndarray]:
            return {h: m for h in masks if (m := self.fits(h, margin + extra)).any()}

        low, high, best, extra = 0.0, None, masks, 1.0
        while extra <= 64 and high is None:  # double the room until nothing fits...
            if found := fitting(extra):
                low, best, extra = extra, found, extra * 2
            else:
                high = extra
        while high is not None and high - low > 0.5:  # ...then halve the difference
            mid = (low + high) / 2
            if found := fitting(mid):
                low, best = mid, found
            else:
                high = mid
        heading, (i, j) = _middle(best)
        return float(self.fmap.xs[i]), float(self.fmap.ys[j]), heading

    def closest(self, margin: float, headings: Sequence[float] = HEADINGS) -> tuple:
        """The start (x, y, heading) where the fewest covered cells are too near something."""
        best = None
        for h in headings:
            counts = self.counts(h, margin)
            i, j = np.unravel_index(np.argmin(counts), counts.shape)
            if best is None or counts[i, j] < best[0]:
                best = (counts[i, j], float(self.fmap.xs[i]), float(self.fmap.ys[j]), h)
        return best[1:]


def _middle(masks: dict[float, np.ndarray]) -> tuple[float, tuple[int, int]]:
    """The heading and cell deepest inside its mask (peeled a cell at a time), the first
    heading winning ties, and the cell nearest the middle of what's left."""
    while True:
        peeled = {h: _peel(m) for h, m in masks.items()}
        peeled = {h: m for h, m in peeled.items() if m.any()}
        if not peeled:
            break
        masks = peeled
    heading, mask = next(iter(masks.items()))
    cells = np.argwhere(mask)
    middle = cells.mean(axis=0)
    i, j = cells[np.argmin(np.hypot(*(cells - middle).T))]
    return heading, (int(i), int(j))


def _peel(mask: np.ndarray) -> np.ndarray:
    out = mask.copy()
    out[1:] &= mask[:-1]
    out[:-1] &= mask[1:]
    out[:, 1:] &= mask[:, :-1]
    out[:, :-1] &= mask[:, 1:]
    out[0] = out[-1] = False
    out[:, 0] = out[:, -1] = False
    return out


# --- placing the robot ---------------------------------------------------------------------


Measure = tuple[tuple[float, float], tuple[float, float], str]  # from a wall, to, label


@dataclass
class Spot:
    """Where a test starts: the robot's pose (x in, y in, heading deg), the least room
    between what it covers and a wall or element, how to put it there with a tape measure,
    and those measurements (for the map)."""

    pose: tuple[float, float, float]
    clearance_in: float
    place: list[str]
    short: list[str] = field(default_factory=list)  # the same in 3 lines, for the brain's screen
    measures: list[Measure] = field(default_factory=list)
    marks: list[tuple[tuple[float, float], tuple[float, float], str]] = field(
        default_factory=list
    )  # tape lines on the floor (the push lane's)

    def to_dict(self) -> dict:
        x, y, h = self.pose
        return {
            "x_in": round(x, 2),
            "y_in": round(y, 2),
            "heading_deg": round(h, 1),
            "clearance_in": round(self.clearance_in, 1),
            "place": list(self.place),
            "short": list(self.short),
        }


def _in(value: float) -> str:
    return f"{round(value, 1):g} in"


def _sides(config: RobotConfig) -> dict[str, tuple[float, tuple[int, int]]]:
    """Each side of the robot: how far it reaches from the robot's origin, and which way
    it faces in the robot's frame."""
    x0, y0, x1, y1 = config.body.outline.bounds
    return {
        "front": (x1, (1, 0)),
        "back": (-x0, (-1, 0)),
        "left side": (y1, (0, 1)),
        "right side": (-y0, (0, -1)),
    }


def _facing(heading: float, short: bool = False) -> str:
    square = round(heading / 90) * 90 % 360
    wall = {0: "+x", 90: "+y", 180: "-x", 270: "-y"}[square]
    turn = (heading - square + 180) % 360 - 180
    if abs(turn) < 1e-6:
        return f"facing the {wall} wall" if short else f"facing {WALLS[wall]}"
    left = {0: "+y", 90: "-x", 180: "-y", 270: "+x"}
    right = {0: "-y", 90: "+x", 180: "+y", 270: "-x"}
    toward = (left if turn > 0 else right)[square]
    if short:
        return f"facing {wall}, turned {abs(turn):g} deg toward {toward}"
    return f"facing {WALLS[wall]}, turned {abs(turn):g} degrees toward the {toward} wall"


def _wall_gap(fmap: FieldMap, point: Sequence[float], axis: int) -> tuple[str, float, Measure]:
    """The wall nearer a point along an axis, how far it is, and that measurement."""
    value, half = point[axis], fmap.half[axis]
    wall = ("-" if value < 0 else "+") + "xy"[axis]
    gap = value + half if value < 0 else half - value
    at_wall = list(point)
    at_wall[axis] = -half if value < 0 else half
    return wall, gap, (tuple(at_wall), (float(point[0]), float(point[1])), _in(gap))


def placement(
    config: RobotConfig, fmap: FieldMap, pose: tuple[float, float, float]
) -> tuple[tuple[float, float, float], list[str], list[str], list[Measure]]:
    """How to put the robot at pose with a tape measure (in sentences, and in three short
    lines), the pose that says exactly (distances to the half inch), and the measurements.
    Square to the walls: how far two of its sides are from the walls they face (the nearer
    wall, unless only the other's tape is clear of the elements); otherwise where two of its
    corners are, each from two walls."""
    x, y, heading = pose
    if heading % 90 == 0:
        h = math.radians(heading)
        nearest = []  # per axis: the side measured, how far it reaches, which way
        for axis in (0, 1):
            best = None
            for side, (reach, (dx, dy)) in _sides(config).items():
                out = (
                    round(math.cos(h) * dx - math.sin(h) * dy),
                    round(math.sin(h) * dx + math.cos(h) * dy),
                )
                if out[axis] == 0:
                    continue
                center, half = (x, y)[axis], fmap.half[axis]
                gap = half - (center + reach) if out[axis] > 0 else center - reach + half
                edge = np.array([[x, y]], dtype=float)
                edge[0, axis] = center + out[axis] * reach
                toward = math.atan2(out[1], out[0])
                crossed = bool(ray_lengths(fmap.field, edge, np.array([toward]))[0] < gap - 1e-6)
                if best is None or (crossed, gap) < best[0]:
                    best = ((crossed, gap), side, reach, out[axis])
            (_, gap), side, reach, sign = best
            half = fmap.half[axis]
            gap = round(gap * 2) / 2
            center = half - gap - reach if sign > 0 else gap + reach - half
            x, y = (center, y) if axis == 0 else (x, center)
            nearest.append((side, reach, sign))
        lines, measures = [f"{_facing(heading).capitalize()}."], []
        short = [_facing(heading, short=True)]
        for axis, (side, reach, sign) in enumerate(nearest):
            edge = [x, y]
            edge[axis] += sign * reach
            wall, gap, measure = _wall_gap(fmap, edge, axis)
            lines.append(f"Its {side} {_in(gap)} from {WALLS[wall]}.")
            short.append(f"{side} {_in(gap)} from the {wall} wall")
            measures.append(measure)
        return (x, y, heading), lines, short, measures
    lines = [f"{_facing(heading).capitalize()}: put tape marks for two of its corners."]
    short, measures = [_facing(heading, short=True)], []
    for name, corner in _corner_pair(config):
        cx, cy = _moved(np.array([corner]), pose)[0]
        (wx, gx, mx), (wy, gy, my) = (_wall_gap(fmap, (cx, cy), axis) for axis in (0, 1))
        lines.append(
            f"Its {name} corner {_in(round(gx * 2) / 2)} from {WALLS[wx]} and "
            f"{_in(round(gy * 2) / 2)} from {WALLS[wy]}."
        )
        measures += [mx, my]
        initials = "".join(word[0].upper() for word in name.split("-"))
        short.append(
            f"{initials} corner: {_in(round(gx * 2) / 2)} from {wx}, "
            f"{_in(round(gy * 2) / 2)} from {wy}"
        )
    return pose, lines, short, measures


def _corner_pair(config: RobotConfig) -> list[tuple[str, tuple[float, float]]]:
    """Two corners of the robot's shape, as far apart as two corners are."""
    corners = config.body.outline.corners
    best, pair = -1.0, (corners[0], corners[-1])
    for i in range(len(corners)):
        for j in range(i + 1, len(corners)):
            d = math.dist(corners[i], corners[j])
            if d > best + 1e-9:
                best, pair = d, (corners[i], corners[j])

    def name(c: np.ndarray) -> str:
        ends = ["front" if c[0] > 1e-6 else "back" if c[0] < -1e-6 else "middle"]
        ends.append("left" if c[1] > 1e-6 else "right" if c[1] < -1e-6 else "middle")
        return "-".join(ends)

    return [(name(c), (float(c[0]), float(c[1]))) for c in pair]


def spot_for(
    config: RobotConfig, fmap: FieldMap, points: np.ndarray, pose: tuple[float, float, float]
) -> Spot:
    """The spot at pose, its placement made exact to the half inch, and its room."""
    exact, place, short, measures = placement(config, fmap, pose)
    clearance = float(fmap.distances(_moved(points, exact)).min()) - FINE_IN / math.sqrt(2)
    return Spot(exact, clearance, place, short, measures)


# --- the plan ------------------------------------------------------------------------------


@dataclass
class TestPlan:
    """One test's spot: a driving test's (its steps at a scale, every variant's path, the
    envelope it may not leave), the push lane's, or a spin in place's."""

    key: str
    title: str
    spot: Spot | None
    points: np.ndarray  # what it covers (start frame), for the maps
    steps: list[Step] = field(default_factory=list)
    scale: float = 1.0
    paths: list[Trial] = field(default_factory=list)
    max_motor_deg: float | None = None  # the envelope: drive motors' travel, IMU turn
    max_turn_deg: float | None = None
    length_in: float | None = None  # the push lane
    turns: float | None = None  # a spin in place
    blocked_by: list[str] = field(default_factory=list)  # no spot: what's in the way
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        out: dict = {"key": self.key, "title": self.title}
        if self.spot is not None:
            out["spot"] = self.spot.to_dict()
        if self.steps:
            out["scale"] = self.scale
            out["steps"] = [
                {
                    k: round(v, 4) if isinstance(v, float) else v
                    for k, v in vars(s).items()
                    if not (k in ("forward", "left", "turn") and v == 0)
                    and not (k == "brake" and v == "coast")
                }
                for s in self.steps
            ]
            out["envelope"] = {
                "motor_deg": round(self.max_motor_deg or 0.0),
                **({"turn_deg": round(self.max_turn_deg)} if self.max_turn_deg else {}),
            }
        if self.length_in is not None:
            out["length_in"] = self.length_in
        if self.turns is not None:
            out["turns"] = self.turns
        if self.blocked_by:
            out["blocked_by"] = list(self.blocked_by)
        if self.notes:
            out["notes"] = list(self.notes)
        return out


@dataclass
class Plan:
    robot: str
    field: str
    margin_in: float
    drive: list[TestPlan]
    push: TestPlan | None
    slow_spin: TestPlan | None
    sweeps: list[TestPlan]
    config: RobotConfig
    fmap: FieldMap

    @property
    def tests(self) -> list[TestPlan]:
        """Every planned spot, in the session's order."""
        return [
            *([self.push] if self.push else []),
            *self.drive,
            *([self.slow_spin] if self.slow_spin else []),
            *self.sweeps,
        ]

    @property
    def missing(self) -> list[TestPlan]:
        return [t for t in self.tests if t.spot is None]

    def session(self) -> list[tuple[str, str, TestPlan | None]]:
        """Every test in the session's order, as the program's menu lists them: (key, title,
        the plan of those that need room on the field)."""
        out: list[tuple[str, str, TestPlan | None]] = [
            ("device_check", "Device check", None),
            ("free_spin", "Free spin, on its side", None),
        ]
        if any(s.type == "imu" for s in self.config.sensors):
            out += [
                ("imu_still", f"IMU, still for {IMU_STILL_S} s", None),
                ("imu_turns", f"IMU, {IMU_TURNS} turns by hand each way", None),
            ]
        return out + [(t.key, t.title, t) for t in self.tests if t.spot is not None]

    def number(self, test: TestPlan) -> int:
        """A test's number in the session (and on its map)."""
        return next(n for n, (_, _, t) in enumerate(self.session(), 1) if t is test)

    def to_dict(self) -> dict:
        return {
            "robot": self.robot,
            "field": self.field,
            "margin_in": self.margin_in,
            "tests": [t.to_dict() for t in self.tests],
        }

    def text(self) -> str:
        lines = [
            f"Calibration plan for {self.robot} on {self.field} (margin {self.margin_in:g} in)",
            "Clear the game pieces off the field first: the plan leaves them out.",
        ]
        for test in self.tests:
            lines.append("")
            what = test.title
            if test.steps and test.scale != 1:
                what += f" (at {test.scale:.0%} speed: there's less room)"
            if test.spot is None:  # not in the session
                lines.append(f"Left out: {what}")
                lines.append("   No room for it, even at the slowest.")
                if test.blocked_by:
                    lines.append(f"   In the way: {', '.join(test.blocked_by)}.")
            else:
                lines.append(f"{self.number(test)}. {what}")
                lines += [f"   {line}" for line in test.spot.place]
                lines.append(f"   Room to spare: {test.spot.clearance_in:.1f} in.")
            lines += [f"   {note}" for note in test.notes]
        return "\n".join(lines) + "\n"


def make_plan(
    config: RobotConfig,
    field: FieldConfig,
    *,
    margin: float = MARGIN_IN,
    workers: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> Plan:
    """Plan every test that needs room on the field (the module says how)."""
    say = progress or (lambda _text: None)
    fmap = FieldMap(field)
    drive = _plan_drive(config, fmap, margin, workers, say)
    say("planning the push lane")
    push = _plan_push(config, fmap)
    reach = config.body.outline.reach()
    slow = None
    imu = any(s.type == "imu" for s in config.sensors)  # the spins in place turn by it
    if imu and any(s.type == "rotation" and s.tracking_wheel for s in config.sensors):
        say("planning the slow spin")
        points = disc(reach + SPIN_DRIFT_IN)
        best = Search(fmap, points).best(margin, headings=(0,))
        slow = TestPlan(
            "slow_spin",
            f"Slow spin, {SLOW_SPIN_TURNS} turns (tracking wheels)",
            None if best is None else spot_for(config, fmap, points, best),
            points,
            turns=SLOW_SPIN_TURNS,
        )
    sweeps = []
    if imu and any(s.type == "distance" for s in config.sensors):
        say("planning the distance sweeps")
        sweeps = _plan_sweeps(config, fmap, margin)
    return Plan(
        config.name or "robot",
        field.name,
        margin,
        drive,
        push,
        slow,
        sweeps,
        config,
        fmap,
    )


def _plan_drive(config, fmap, margin, workers, say) -> list[TestPlan]:
    tests = list(drive_tests(config))
    plans: dict[str, TestPlan] = {}
    for scale in SCALES:
        todo = [key for key in tests if key not in plans]
        if not todo:
            break
        steps = {key: drive_tests(config, scale)[key] for key in todo}
        say(f"simulating {', '.join(todo)} at {scale:.0%} speed in {len(VARIANTS)} variants")
        jobs = [(config, v, steps[key]) for key in todo for v in VARIANTS]
        results = _run(jobs, workers)
        for n, key in enumerate(todo):
            paths = results[n * len(VARIANTS) : (n + 1) * len(VARIANTS)]
            points = swept(config, [p.poses for p in paths])
            search = Search(fmap, points)
            best = search.best(margin)
            if best is None and scale != SCALES[-1]:
                continue
            plan = TestPlan(
                key,
                f"{DRIVE_TESTS[key]} (3 runs)",
                None if best is None else spot_for(config, fmap, points, best),
                points,
                steps=steps[key],
                scale=scale,
                paths=paths,
            )
            k, motor_extra, turn_extra = ENVELOPE
            plan.max_motor_deg = k * max(p.motor_deg for p in paths) + motor_extra
            turns = [p.turn_deg for p in paths if p.turn_deg is not None]
            plan.max_turn_deg = k * max(turns) + turn_extra if turns else None
            if best is None:
                where = search.closest(margin)
                plan.blocked_by = fmap.near(_moved(points, where), margin + SLACK_IN)
            plans[key] = plan
    return [plans[key] for key in tests]


def _run(jobs: list, workers: int | None) -> list[Trial]:
    from vexsim.calibration.fit import worker_count

    n = min(worker_count(workers), len(jobs))
    if n <= 1:
        return [simulate(job) for job in jobs]
    from vexsim.workers import process_pool

    with process_pool(n) as pool:
        return list(pool.map(simulate, jobs))


def _plan_push(config: RobotConfig, fmap: FieldMap) -> TestPlan:
    """The longest lane (PUSH_LENGTHS_IN) that fits, and its two tape lines: where the
    robot's front edge starts and where it's pushed to."""
    best = None
    for length in PUSH_LENGTHS_IN:
        points = lane(config, length)
        search = Search(fmap, points)
        best = search.best(PUSH_MARGIN_IN)
        if best is not None:
            break
    title = "Push, each way"
    if best is None:
        where = _moved(points, search.closest(PUSH_MARGIN_IN))
        blocked = fmap.near(where, PUSH_MARGIN_IN + SLACK_IN)
        return TestPlan("push", title, None, points, length_in=length, blocked_by=blocked)
    spot = spot_for(config, fmap, points, best)
    x, y, heading = spot.pose
    h = math.radians(heading)
    along, across = np.array([math.cos(h), math.sin(h)]), np.array([-math.sin(h), math.cos(h)])
    x0, y0, x1, y1 = config.body.outline.bounds
    for name, ahead in (("start", x1), ("end", x1 + length)):
        middle = np.array([x, y]) + along * ahead
        ends = (middle + across * (y0 - 2), middle + across * (y1 + 2))
        spot.marks.append((tuple(ends[0]), tuple(ends[1]), f"{name} line"))
        if heading % 90 == 0:  # measured along the lane's left edge, clear of the robot's
            axis = 0 if abs(along[0]) > 0.5 else 1
            wall, gap, measure = _wall_gap(fmap, middle + across * (y1 + 1), axis)
            spot.place.append(
                f"Tape the {name} line across the lane {_in(gap)} from {WALLS[wall]}."
            )
            spot.measures.append(measure)
            if name == "start":  # how far its side is, where the start line is, what to do
                spot.short = [
                    spot.short[2 - axis],
                    f"start line {_in(gap)} from the {wall} wall",
                    f"front edge on it; push {length:g} in",
                ]
        else:
            (wx, gx, mx), (wy, gy, my) = (_wall_gap(fmap, middle, axis) for axis in (0, 1))
            spot.place.append(
                f"Tape the {name} line across the lane, its middle {_in(gx)} from {WALLS[wx]} "
                f"and {_in(gy)} from {WALLS[wy]}."
            )
            spot.measures += [mx, my]
            if name == "start":
                spot.short = [
                    spot.short[0],
                    f"start line middle {_in(gx)} from {wx}, {_in(gy)} from {wy}",
                    f"front edge on it; push {length:g} in",
                ]
    spot.place.append(
        f"Its front edge starts on the start line; push it {length:g} in, to the end line."
    )
    return TestPlan("push", title, spot, points, length_in=length)


def _plan_sweeps(config: RobotConfig, fmap: FieldMap, margin: float) -> list[TestPlan]:
    """Spots where one slow turn shows the distance sensors the walls and elements at the
    distances the other spots' turns don't: picked one at a time, each for the most readings
    in new 100 mm bins."""
    points = disc(config.body.outline.reach() + SPIN_DRIFT_IN)
    fits = Search(fmap, points).fits(0, margin)
    step = round(6 / fmap.cell)  # candidates 6 in apart
    cells = [(i, j) for i, j in np.argwhere(fits) if i % step == 0 and j % step == 0]
    sensors = [s for s in config.sensors if s.type == "distance"]
    angles = np.radians(np.arange(0.0, 360.0, SWEEP_STEP_DEG))
    seen = set()
    candidates = []
    for i, j in cells:
        x, y = float(fmap.xs[i]), float(fmap.ys[j])
        bins = set()
        for k, sensor in enumerate(sensors):
            mount = np.array(sensor.pos_in, dtype=float)
            c, s = np.cos(angles), np.sin(angles)
            origins = np.stack(
                [x + c * mount[0] - s * mount[1], y + s * mount[0] + c * mount[1]], axis=-1
            )
            heights = None if sensor.height_in is None else np.full(len(angles), sensor.height_in)
            mm = ray_lengths(
                fmap.field, origins, angles + math.radians(sensor.heading_deg), heights
            )
            mm = mm * 25.4
            mm = mm[(mm >= RANGE_MM[0]) & (mm <= RANGE_MM[1])]
            bins |= {(k, int(v // BIN_MM)) for v in mm}
        candidates.append(((x, y, 0.0), bins))
    plans = []
    for n in range(1, SWEEPS + 1):
        if not candidates:
            break
        pose, bins = max(candidates, key=lambda c: len(c[1] - seen))
        if len(bins - seen) < 3:
            break
        seen |= bins
        plans.append(
            TestPlan(
                f"sweep_{n}",
                f"Distance sweep {n}, one slow turn",
                spot_for(config, fmap, points, pose),
                points,
                turns=1,
            )
        )
        candidates = [c for c in candidates if math.dist(c[0][:2], pose[:2]) > 12]
    return plans


# --- writing it out ------------------------------------------------------------------------


def write_plan(plan: Plan, folder: str | Path) -> list[Path]:
    """plan.txt, plan.yaml and, with matplotlib, a map of each spot; returns the files."""
    import yaml

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = [folder / "plan.txt", folder / "plan.yaml"]
    out[0].write_text(plan.text(), encoding="utf-8")
    out[1].write_text(yaml.safe_dump(plan.to_dict(), sort_keys=False), encoding="utf-8")
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return out
    for test in plan.tests:
        if test.spot is not None:  # a test with no room isn't in the session
            n = plan.number(test)
            out.append(draw_map(plan, test, folder / f"map_{n}_{test.key}.png", number=n))
    return out


def draw_map(plan: Plan, test: TestPlan, path: str | Path, *, number: int | None = None) -> Path:
    """A map of one test's spot: the field and its elements, the robot where it starts, what
    it covers on every variant's path and the margin around that, and the measurements."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Polygon, Rectangle

    fmap, config = plan.fmap, plan.config
    hx, hy = fmap.half
    lines = test.spot.place if test.spot else ["No room for this test.", *test.blocked_by]
    text_in = 0.3 + 0.16 * len(lines)  # the placement's lines under the map
    height = 7.2 + text_in
    fig = plt.figure(figsize=(7.2, height), dpi=110)
    ax = fig.add_axes((0.02, text_in / height, 0.96, (height - text_in - 0.4) / height))
    ax.set_axis_off()
    ax.add_patch(Rectangle((-hx, -hy), 2 * hx, 2 * hy, fill=False, lw=2, ec="#333333"))
    for obstacle in fmap.field.obstacles:
        style = {"fc": obstacle.color or "#8a8a8a", "ec": "#333333", "lw": 0.8, "zorder": 2}
        if obstacle.shape == "circle":
            patch = Circle(obstacle.pos_in, obstacle.diameter_in / 2, **style)
        else:
            length, width = obstacle.size_in
            corner = (obstacle.pos_in[0] - length / 2, obstacle.pos_in[1] - width / 2)
            patch = Rectangle(
                corner, length, width, angle=obstacle.heading_deg, rotation_point="center", **style
            )
        ax.add_patch(patch)
    if test.spot is not None:
        pose = test.spot.pose
        margin = PUSH_MARGIN_IN if test.key == "push" else plan.margin_in
        _shade(ax, _moved(test.points, pose), margin, fmap.cell)
        for trial in test.paths:
            moved = _moved(trial.poses[:, :2], pose)
            ax.plot(moved[:, 0], moved[:, 1], lw=0.8, color="#2f5d8a", alpha=0.8, zorder=3)
        for loop in config.body.outline.loops():
            outline = _moved(np.array(loop), pose)
            ax.add_patch(Polygon(outline, fc="#f2b134", ec="#5a3d00", lw=1.2, zorder=4))
        x, y, h = pose
        ahead = config.body.outline.bounds[2] + 6
        tip = (x + math.cos(math.radians(h)) * ahead, y + math.sin(math.radians(h)) * ahead)
        ax.annotate("", tip, (x, y), arrowprops={"arrowstyle": "->", "lw": 1.6, "color": "#5a3d00"})
        for a, b, label in test.spot.marks:
            ax.plot(*zip(a, b, strict=True), color="#b23a3a", lw=2, zorder=5)
            ax.text(*b, label, color="#b23a3a", fontsize=7, ha="center", va="bottom", zorder=6)
        for a, b, label in test.spot.measures:
            ax.annotate(
                "", b, a, arrowprops={"arrowstyle": "<->", "lw": 0.9, "color": "#222222"}, zorder=6
            )
            middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            ax.text(
                *middle,
                label,
                fontsize=7,
                ha="center",
                va="center",
                bbox={"fc": "white", "ec": "none", "pad": 0.5},
                zorder=7,
            )
    for wall, (tx, ty, rotation) in {
        "+x": (hx + 3, 0, 270),
        "-x": (-hx - 3, 0, 90),
        "+y": (0, hy + 3, 0),
        "-y": (0, -hy - 3, 0),
    }.items():
        ax.text(tx, ty, f"{wall} wall", ha="center", va="center", rotation=rotation, fontsize=8)
    ax.set_title(f"{number}. {test.title}" if number else test.title, fontsize=11)
    ax.set_xlim(-hx - 6, hx + 6)
    ax.set_ylim(-hy - 6, hy + 6)
    ax.set_aspect("equal")
    fig.text(0.04, 0.15 / height, "\n".join(lines), fontsize=8, va="bottom", linespacing=1.4)
    fig.savefig(path)
    plt.close(fig)
    return Path(path)


def _shade(ax, covered: np.ndarray, margin: float, cell: float) -> None:
    """Shade what a test covers (points, field frame), and the margin around it."""
    low = covered.min(axis=0) - margin - 1
    shape = np.ceil((covered.max(axis=0) + margin + 1 - low) / cell).astype(int) + 1
    hit = np.zeros(shape[::-1], dtype=bool)  # rows are y
    idx = np.round((covered - low) / cell).astype(int)
    hit[idx[:, 1], idx[:, 0]] = True
    band = np.zeros_like(hit)
    rows, cols = np.nonzero(hit)
    r = math.ceil(margin / cell)
    for a in range(-r, r + 1):
        for b in range(-r, r + 1):
            if math.hypot(a, b) * cell <= margin:
                yy, xx = rows + a, cols + b
                ok = (yy >= 0) & (yy < hit.shape[0]) & (xx >= 0) & (xx < hit.shape[1])
                band[yy[ok], xx[ok]] = True
    image = np.zeros((*hit.shape, 4))
    image[band] = (0.18, 0.36, 0.54, 0.15)
    image[hit] = (0.18, 0.36, 0.54, 0.45)
    extent = (
        low[0] - cell / 2,
        low[0] + (hit.shape[1] - 0.5) * cell,
        low[1] - cell / 2,
        low[1] + (hit.shape[0] - 0.5) * cell,
    )
    ax.imshow(image, extent=extent, origin="lower", interpolation="nearest", zorder=1)

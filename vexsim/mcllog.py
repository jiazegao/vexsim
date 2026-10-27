"""MCL logs: a robot's Monte Carlo localization, update by update, as its code wrote it.

The format is the one team 1239E's code writes to the SD card (``MclTracking`` in
examples/pros_projects/1239e_2026-27) and their log visualizer reads: a block of lines
per update, numbers separated by commas,

    reading_mm, x, y, angle     a line per distance sensor: its reading (9999: nothing),
    ...                         and the ray MCL cast for it (inches; radians from +x)
    x, y                        a line per particle it logged
    ...
    t                           seconds since the log began
    x, y, theta                 the estimate (inches; radians counter-clockwise from +x),
                                as it stood before this update
    std_x, std_y                the particles' spread (inches)

Lines are told apart by how many numbers they have, so any number of sensors and particles
reads. ``MclLog.drawings`` turns an update into what the browser draws (rays, particles and
a 2-sigma ellipse, as the team's visualizer draws them); ``MclLog.path`` is where the robot
went by its own estimate, for a run to follow (``vexsim.runtime.follow``).
"""

from __future__ import annotations

import math
import statistics as st
from dataclasses import dataclass
from pathlib import Path

NO_READING_MM = 9000  # PROS reads 9999 mm when a distance sensor sees nothing
MM_PER_IN = 25.4
NO_READING_IN = 10.0  # how long a ray that read nothing is drawn
MAX_BYTES = 64 * 1024 * 1024


class MclLogError(ValueError):
    """Not an MCL log, or not one that reads."""


@dataclass(frozen=True)
class Update:
    """One MCL update."""

    t: float  # s since the log began
    sensors: tuple[tuple[float, float, float, float], ...]  # mm; ray origin x, y (in); angle (rad)
    particles: tuple[tuple[float, float], ...]
    estimate: tuple[float, float, float]  # x, y (in), theta (rad, counter-clockwise from +x)
    spread: tuple[float, float]  # standard deviation in x and y (in)


def _numbers(line: str) -> tuple[float, ...]:
    values = tuple(float(v) for v in line.split(",") if v.strip())
    if not all(math.isfinite(v) for v in values):
        raise ValueError("not a finite number")
    return values


def parse(text: str) -> list[Update]:
    """Every complete update in a log's text; a cut-off last one (the robot was switched
    off while it wrote) is left out. Raises MclLogError if the text isn't an MCL log."""
    updates: list[Update] = []
    sensors: list = []
    particles: list = []
    t: float | None = None
    estimate: tuple | None = None
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            values = _numbers(line)
        except ValueError:
            values = ()
        n = len(values)
        if estimate is not None:  # after the estimate: the spread ends the update
            if n != 2:
                break
            updates.append(Update(t, tuple(sensors), tuple(particles), estimate, values))
            sensors, particles, t, estimate = [], [], None, None
        elif t is not None:  # after the time: the estimate
            if n != 3:
                break
            estimate = values
        elif n == 4 and not particles:
            sensors.append(values)
        elif n == 2:
            particles.append(values)
        elif n == 1:
            t = values[0]
        else:
            break
        if not updates and number > 2000:  # nothing like an update this far in
            break
    if not updates:
        raise MclLogError("not an MCL log: no update in it reads")
    return updates


def looks_like_one(text: str) -> bool:
    """Whether the start of a file is an MCL log's (for finding them in a workspace)."""
    try:
        return len(parse(text)) > 0
    except MclLogError:
        return False


@dataclass
class MclLog:
    name: str
    updates: list[Update]

    @classmethod
    def read(cls, path: str | Path) -> MclLog:
        path = Path(path)
        try:
            if path.stat().st_size > MAX_BYTES:
                raise MclLogError(f"{path.name} is too big to be an MCL log")
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise MclLogError(f"can't read {path.name}: {exc.strerror or exc}") from None
        return cls(path.name, parse(text))

    @property
    def start_t(self) -> float:
        return self.updates[0].t

    @property
    def duration(self) -> float:
        return self.updates[-1].t - self.updates[0].t

    @property
    def start(self) -> tuple[float, float, float]:
        """Where MCL started: x, y (in) and heading (degrees counter-clockwise from +x)."""
        x, y, theta = self.updates[0].estimate
        return (x, y, math.degrees(theta))

    def times(self) -> list[float]:
        """Each update's time, from the first update."""
        return [u.t - self.start_t for u in self.updates]

    def estimates(self) -> list[tuple[float, float, float]]:
        """Each update's estimate: x, y (in) and heading (degrees counter-clockwise from +x)."""
        return [(x, y, math.degrees(theta)) for x, y, theta in (u.estimate for u in self.updates)]

    def path(self) -> tuple[list[float], list[tuple[float, float, float]]]:
        """Where the robot went by its estimate: times from the first update, and poses
        (x, y in inches, theta in radians, unwrapped). An update logs the estimate from the
        update before it, so each estimate goes with the time of the update before."""
        if len(self.updates) < 3:
            raise MclLogError("an MCL log needs 3 updates or more to follow")
        times = [u.t - self.start_t for u in self.updates[:-1]]
        poses = []
        theta = self.updates[1].estimate[2]
        for u in self.updates[1:]:
            x, y, t = u.estimate
            theta += math.remainder(t - theta, math.tau)
            poses.append((x, y, theta))
        return times, poses

    def drawings(self, update: Update) -> dict[str, list[list]]:
        """An update as the browser draws it (``vexsim.runtime.drawing`` shapes): each
        sensor's ray to what it read, the particles, and the 2-sigma ellipse of their spread
        around the estimate (as the team's visualizer draws them)."""
        rays = []
        for mm, x, y, angle in update.sensors:
            seen = mm < NO_READING_MM
            length = mm / MM_PER_IN if seen else NO_READING_IN
            end = (x + length * math.cos(angle), y + length * math.sin(angle))
            rays.append(["line", *(_r(v) for v in (x, y, *end)), "yellow" if seen else "muted"])
            if seen:
                rays.append(["point", _r(end[0]), _r(end[1]), "yellow", 5])
        particles = [["point", _r(x), _r(y), "violet", 4] for x, y in update.particles]
        x, y, _ = update.estimate
        sx, sy = update.spread
        spread = [["ellipse", _r(x), _r(y), _r(2 * sx), _r(2 * sy), 0, "blue"]]
        return {"rays": rays, "particles": particles, "spread": spread}

    def summary(self) -> dict:
        """What the log says about how MCL ran."""
        gaps = [(b.t - a.t) * 1000 for a, b in zip(self.updates, self.updates[1:], strict=False)]
        readings = [s[0] for u in self.updates for s in u.sensors]
        spread = [math.hypot(*u.spread) for u in self.updates]
        x, y, heading = self.start
        return {
            "updates": len(self.updates),
            "duration_s": round(self.duration, 3),
            "sensors": len(self.updates[0].sensors),
            "particles": len(self.updates[0].particles),
            "start": [round(x, 2), round(y, 2), round(heading, 2)],
            "interval_ms": [_r(st.median(gaps)), _r(_quantile(gaps, 0.95)), _r(max(gaps))]
            if gaps
            else None,
            "no_reading_pct": _r(100 * st.fmean(r >= NO_READING_MM for r in readings))
            if readings
            else None,
            "spread_in": [_r(st.median(spread)), _r(_quantile(spread, 0.95))],
        }


def _quantile(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[min(int(q * len(values)), len(values) - 1)]


def _r(value: float) -> float:
    return round(float(value), 3)

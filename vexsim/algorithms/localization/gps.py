"""Odometry corrected by a GPS sensor.

Odometry is smooth but drifts; the GPS doesn't drift but is noisy, delayed,
and drops out when its camera can't read the code strip. A complementary
filter takes the best of both: every fresh GPS fix pulls the odometry position
a fraction ``dt / time_constant_s`` of the way toward the GPS, so position
errors decay with that time constant while GPS noise is averaged away.
Heading stays with the odometry's IMU, which is far smoother than the GPS's.

The GPS reports its own position; the filter turns it into the robot center's
with the configured mount position (``pos_in``), so the code never needs to
set an offset. A fix describes where the robot was ``latency_s`` ago, so it is
compared with the odometry pose from then and the difference is applied now;
otherwise a moving robot's estimate would trail it.
"""

from __future__ import annotations

import math
from collections import deque

from vexsim.algorithms.localization.base import Pose
from vexsim.algorithms.localization.odometry import ArcOdometry
from vexsim.devices.frame import GpsReading, SensorFrame
from vexsim.units import m_to_in


class GpsCorrected:
    def __init__(
        self,
        name: str,
        odometry: ArcOdometry,
        port: int,
        mount_in: tuple[float, float],
        *,
        time_constant_s: float = 0.5,
        max_error_m: float = 0.05,
        latency_s: float = 0.03,
    ):
        self.name = name
        self.odometry = odometry
        self.port = port
        self.mount_in = mount_in
        self.time_constant_s = time_constant_s
        self.max_error_m = max_error_m
        self.latency_s = latency_s
        self._last: GpsReading | None = None
        self._last_time: float | None = None
        self._history: deque[tuple[float, Pose]] = deque(maxlen=50)

    @property
    def pose(self) -> Pose:
        return self.odometry.pose

    def reset(self, pose: Pose, frame: SensorFrame) -> None:
        self.odometry.reset(pose, frame)
        self._last = frame.gps.get(self.port)
        self._last_time = frame.time
        self._history.clear()
        self._history.append((frame.time, pose))

    def update(self, frame: SensorFrame) -> Pose:
        pose = self.odometry.update(frame)
        self._history.append((frame.time, pose))
        reading = frame.gps.get(self.port)
        if reading is None or reading is self._last:
            return pose  # no new sample
        dt = frame.time - (self._last_time if self._last_time is not None else frame.time)
        self._last, self._last_time = reading, frame.time
        if not reading.fix or reading.error_m > self.max_error_m:
            return pose
        then = self._pose_at(frame.time - self.latency_s)
        # Where the robot center was, from where the sensor was and the heading then.
        h = math.radians(then.heading)
        mx, my = self.mount_in
        x = m_to_in(reading.x_m) - (math.cos(h) * mx - math.sin(h) * my)
        y = m_to_in(reading.y_m) - (math.sin(h) * mx + math.cos(h) * my)
        gain = min(1.0, dt / self.time_constant_s)
        corrected = Pose(pose.x + gain * (x - then.x), pose.y + gain * (y - then.y), pose.heading)
        self.odometry.pose = corrected
        shift = (corrected.x - pose.x, corrected.y - pose.y)
        self._history = deque(
            ((t, Pose(p.x + shift[0], p.y + shift[1], p.heading)) for t, p in self._history),
            maxlen=self._history.maxlen,
        )
        return corrected

    def _pose_at(self, time: float) -> Pose:
        """The estimate at ``time`` (the latest one at or before it)."""
        best = self._history[0][1]
        for t, p in self._history:
            if t > time + 1e-9:
                break
            best = p
        return best

"""A virtual driver that drives the robot along a logged path: a real robot's run, replayed.

``PathFollower`` is a simulation's input source. Once the program's driver control
(opcontrol) starts, it holds the controller's sticks as a driver would, steering the
simulated robot along a path in time: where a real robot went, by its own estimate
(``vexsim.mcllog.MclLog.path``). It sees where the simulated robot really is. That
estimate is the only record of where the real robot went, so where the real robot's
localization was wrong, the simulated robot drives the wrong path.

It drives through the program's own stick mapping (tank: the left and right sticks' y;
arcade: left y forward, right x turning) and its drive curve (LemLib's ExpoDriveCurve),
inverted, using Kanayama's tracking law on the path's speed, a little ahead of time to make
up for the drive's lag. Where the logged estimate drifts sideways while the robot is still
(localization wandering, or correcting itself), it stays put: a tank drive can't slide, and
a still robot most likely stayed where it stopped. The run ends when the path does.

    vexsim run robot.yaml --program project --mode match --follow mcl_log1040.1239e \\
        --sticks tank --curve 15,20,1.05
"""

from __future__ import annotations

import bisect
import math
import statistics as st
from typing import Literal

Sticks = Literal["tank", "arcade"]
GAINS = (4.0, 0.03, 10.0, 0.1)  # kx, ky, ktheta, lead (s): tuned on 1239E's tank drive
SMOOTH = 5  # updates in the path's moving average
END_S = 0.3  # the run goes on this long after the path ends


class ExpoCurve:
    """LemLib's ExpoDriveCurve(deadband, min_output, curve), and its inverse."""

    def __init__(self, deadband: float = 0, min_output: float = 0, curve: float = 1):
        self.table = [(0, 0.0)]
        deadband = int(deadband)
        g127 = 127 - deadband
        i127 = curve ** (g127 - 127) * g127
        for j in range(deadband + 1, 128):
            out = (127 - min_output) / i127 * curve ** (j - deadband - 127) * (j - deadband)
            self.table.append((j, out + min_output))

    def stick(self, output: float) -> int:
        """The stick position whose curved output is nearest ``output`` (-127 to 127)."""
        position, _ = min(self.table, key=lambda e: abs(e[1] - min(abs(output), 127)))
        return int(math.copysign(position, output))


class LoggedPath:
    """A path in time, lightly smoothed: times from its start (s) and poses (x, y in
    inches, theta in radians counter-clockwise from +x, unwrapped)."""

    def __init__(self, times: list[float], poses: list[tuple[float, float, float]]):
        if len(times) != len(poses) or len(times) < 2:
            raise ValueError("a path needs two poses or more, one per time")
        h = SMOOTH // 2

        def smoothed(values: list[float]) -> list[float]:
            return [st.fmean(values[max(0, i - h) : i + h + 1]) for i in range(len(values))]

        self.t = list(times)
        self.x = smoothed([p[0] for p in poses])
        self.y = smoothed([p[1] for p in poses])
        self.theta = smoothed([p[2] for p in poses])
        self.end = self.t[-1]

    def at(self, tau: float) -> tuple[float, float, float, float, float, float]:
        """x, y, theta and their rates at ``tau`` s."""
        i = min(max(bisect.bisect_right(self.t, tau) - 1, 0), len(self.t) - 2)
        f = min(max((tau - self.t[i]) / (self.t[i + 1] - self.t[i]), 0.0), 1.0)
        j0, j1 = max(i - 2, 0), min(i + 3, len(self.t) - 1)  # rates over about 0.15 s
        dt = self.t[j1] - self.t[j0]
        return (
            self.x[i] + f * (self.x[i + 1] - self.x[i]),
            self.y[i] + f * (self.y[i + 1] - self.y[i]),
            self.theta[i] + f * (self.theta[i + 1] - self.theta[i]),
            (self.x[j1] - self.x[j0]) / dt,
            (self.y[j1] - self.y[j0]) / dt,
            (self.theta[j1] - self.theta[j0]) / dt,
        )


def drive_geometry(config) -> tuple[float, float]:
    """A robot config's track width (in) and top speed (in/s), for driving it like a tank."""
    drive = config.drivetrain
    sides = [abs(w.pos_in[1]) for w in drive.wheels]
    track = 2 * st.fmean(sides) if any(sides) else 10.0
    speeds = []
    for group in drive.gearing.values():
        diameter = st.fmean(drive.wheel(name).diameter_in for name in group.wheels)
        speeds.append(group.wheel_free_rpm / 60 * math.pi * diameter)
    return track, min(speeds)


class PathFollower:
    """An input source that drives along ``path`` once opcontrol starts (see the module)."""

    def __init__(
        self,
        path: LoggedPath,
        *,
        track_in: float,
        top_speed_in_s: float,
        sticks: Sticks = "tank",
        curve: tuple[float, float, float] | None = None,
        gains: tuple[float, float, float, float] = GAINS,
    ):
        self.path = path
        self.track = track_in
        self.top_speed = top_speed_in_s
        self.sticks = sticks
        self.curve = ExpoCurve(*curve) if curve else None
        self.kx, self.ky, self.ktheta, self.lead = gains
        self.sim = None  # set by attach
        self.start_s: float | None = None  # when it began following: the path's start
        self.done = False  # past the path's end: the run is over
        self.following: list[float] = []  # how far the robot was from the path (in)

    def attach(self, sim) -> None:
        self.sim = sim

    def _stick(self, output: float) -> int:
        if self.curve is not None:
            return self.curve.stick(output)
        return round(max(-127.0, min(127.0, output)))

    def poll(self, time_s: float) -> tuple[dict[str, float], set[str]]:
        sim = self.sim
        if sim is None or sim.phase != "opcontrol" or self.done:
            return {}, set()
        if self.start_s is None:
            self.start_s = time_s
        tau = time_s - self.start_s
        if tau > self.path.end + END_S:
            self.done = True
        if tau > self.path.end:
            return {}, set()
        x, y, theta = sim.robot.pose
        x, y = x / 0.0254, y / 0.0254
        xr, yr, thr, *_ = self.path.at(tau)
        _, _, th_lead, vx, vy, w_ref = self.path.at(tau + self.lead)
        c, s = math.cos(theta), math.sin(theta)
        ex, ey = c * (xr - x) + s * (yr - y), -s * (xr - x) + c * (yr - y)
        e_theta = math.remainder(thr - theta, math.tau)
        self.following.append(math.hypot(ex, ey))
        v_ref = vx * math.cos(th_lead) + vy * math.sin(th_lead)  # signed: forward or back
        v = v_ref * math.cos(e_theta) + self.kx * ex
        w = w_ref + self.ky * v_ref * ey + self.ktheta * math.sin(e_theta)
        scale = 127 / self.top_speed
        left, right = (v - w * self.track / 2) * scale, (v + w * self.track / 2) * scale
        if self.sticks == "arcade":
            forward, turn = (left + right) / 2, (left - right) / 2
            return {"LEFT_Y": self._stick(forward), "RIGHT_X": self._stick(turn)}, set()
        return {"LEFT_Y": self._stick(left), "RIGHT_Y": self._stick(right)}, set()

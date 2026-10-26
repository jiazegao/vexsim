"""Telemetry log: one row every 10 ms, written as CSV."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from vexsim.algorithms.localization.base import Pose
from vexsim.units import m_to_in

if TYPE_CHECKING:
    from vexsim.runtime.simulation import Simulation

BASE_COLUMNS = [
    "time_s",
    "phase",
    "x_in",
    "y_in",
    "heading_deg",
    "est_x_in",
    "est_y_in",
    "est_heading_deg",
    "speed_in_s",
    "yaw_rate_deg_s",
    "battery_v",
    "battery_soc",
]


@dataclass(frozen=True)
class PoseError:
    """Estimated vs. true pose over a run: position (in) and heading (deg) errors."""

    mean_in: float
    max_in: float
    max_at_s: float
    final_in: float
    mean_deg: float
    max_deg: float

    def __str__(self) -> str:
        return (
            f"mean {self.mean_in:.2f} in, max {self.max_in:.2f} in (at {self.max_at_s:.1f} s), "
            f"final {self.final_in:.2f} in; heading mean {self.mean_deg:.2f}, "
            f"max {self.max_deg:.1f} deg"
        )


class Recorder:
    def __init__(self, sim: Simulation):
        self.sim = sim
        self.ports = sorted(sim.robot.motors)
        self.mechanisms = list(sim.robot.mechanisms.values())
        self.columns = (
            BASE_COLUMNS
            + [f"motor{p}_{k}" for p in self.ports for k in ("current_a", "temp_c", "volts")]
            + [f"{m.name}_deg" for m in self.mechanisms]  # output angle from the start
        )
        self.rows: list[list] = []

    def capture(self, _world=None) -> None:
        sim, robot = self.sim, self.sim.robot
        true = Pose.from_si(robot.pose)
        est = sim.estimated_pose if sim.localizer_ready or sim.reported_pose else None
        u, v, w = robot.body_velocity
        row = [
            round(sim.world.time, 3),
            sim.phase,
            true.x,
            true.y,
            true.heading,
            est.x if est else math.nan,
            est.y if est else math.nan,
            est.heading if est else math.nan,
            m_to_in(math.hypot(u, v)),
            math.degrees(w),
            robot.power.bus_voltage,
            robot.power.battery.soc,
        ]
        for p in self.ports:
            m = robot.motors[p]
            row += [abs(m.current), m.temperature_c, m.voltage]
        row += [m.position_deg for m in self.mechanisms]
        self.rows.append(row)

    def pose_error(self, phase: str | None = None) -> PoseError | None:
        """How far the estimated pose (the robot code's own, for C++ programs) was from the
        true one, over the rows of ``phase`` (all rows if None); None without estimates."""
        t, dist, turn = [], [], []
        for row in self.rows:
            if (phase is not None and row[1] != phase) or math.isnan(row[5]):
                continue
            t.append(row[0])
            dist.append(math.hypot(row[2] - row[5], row[3] - row[6]))
            turn.append(abs((row[4] - row[7] + 180.0) % 360.0 - 180.0))
        if not t:
            return None
        worst = max(range(len(dist)), key=dist.__getitem__)
        return PoseError(
            mean_in=sum(dist) / len(dist),
            max_in=dist[worst],
            max_at_s=t[worst],
            final_in=dist[-1],
            mean_deg=sum(turn) / len(turn),
            max_deg=max(turn),
        )

    def write_csv(self, path: str | Path) -> Path:
        path = Path(path)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(self.columns)
            for row in self.rows:
                writer.writerow(f"{v:.4f}" if isinstance(v, float) else v for v in row)
        return path


class Log:
    """A telemetry CSV read back for plotting and replay."""

    def __init__(self, columns: list[str], phase: list[str], data: np.ndarray):
        self.columns = columns
        self.phase = phase
        self._data = data
        self._index = {c: i for i, c in enumerate(columns)}

    @classmethod
    def read(cls, path: str | Path) -> Log:
        with Path(path).open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            columns = next(reader)
            rows = list(reader)
        if not rows or columns[: len(BASE_COLUMNS)] != BASE_COLUMNS:
            raise ValueError(f"{path} is not a vexsim telemetry log")
        phase = [r[1] for r in rows]
        numeric = [c for c in columns if c != "phase"]
        data = np.array([[float(v) for i, v in enumerate(r) if i != 1] for r in rows])
        return cls(numeric, phase, data)

    def __getitem__(self, column: str) -> np.ndarray:
        return self._data[:, self._index[column]]

    def __len__(self) -> int:
        return len(self._data)

    @property
    def motor_ports(self) -> list[int]:
        return sorted({int(c[5:].split("_")[0]) for c in self.columns if c.startswith("motor")})

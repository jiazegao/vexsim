"""Telemetry log: one row every 10 ms, written as CSV."""

from __future__ import annotations

import csv
import math
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


class Recorder:
    def __init__(self, sim: Simulation):
        self.sim = sim
        self.ports = sorted(sim.robot.motors)
        self.columns = BASE_COLUMNS + [
            f"motor{p}_{k}" for p in self.ports for k in ("current_a", "temp_c", "volts")
        ]
        self.rows: list[list] = []

    def capture(self, _world=None) -> None:
        sim, robot = self.sim, self.sim.robot
        true = Pose.from_si(robot.pose)
        est = sim.estimated_pose if sim.localizer_ready else None
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
        self.rows.append(row)

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

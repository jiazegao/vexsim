"""Robot logs: what a robot's own code measures, every 10 ms, as CSV.

The calibration routine writes them on a real robot (C++, see cpp.py), and
``RobotLogger`` records the same columns in the simulator. Readings are raw,
as PROS reports them for a positive port: a motor on a negative config port
reads backwards, and rotation sensors are read with reversal off.

Columns (``<p>`` is the smart port):

  time_ms                    since the log started
  battery_mv, battery_ma     pros::battery
  m<p>_cmd_mv                voltage command the code gave (move_voltage), raw direction;
                             0 means stopped with the brake mode; empty if unknown
  m<p>_cmd_rpm               velocity command (move_velocity); empty if unknown
  m<p>_brake                 brake mode: 0 coast, 1 brake, 2 hold
  m<p>_deg m<p>_rpm m<p>_ma m<p>_mv m<p>_temp
                             position, actual velocity, current, voltage, temperature
  r<p>_cdeg                  rotation sensor position, centidegrees
  imu<p>_deg                 IMU rotation, degrees clockwise; empty while calibrating
  d<p>_mm                    distance sensor; empty when nothing is in range
  gps<p>_x_m gps<p>_y_m gps<p>_heading_deg gps<p>_error_m
                             GPS position, heading and error estimate

Printed logs are framed by ``#vexsim-log begin`` and ``#vexsim-log end`` lines,
so a log can be cut out of any terminal capture or simulator console output.
"""

from __future__ import annotations

import codecs
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from vexsim.config.robot import RobotConfig

BEGIN = "#vexsim-log begin"
END = "#vexsim-log end"
MOTOR_FIELDS = ("cmd_mv", "cmd_rpm", "brake", "deg", "rpm", "ma", "mv", "temp")
GPS_FIELDS = ("x_m", "y_m", "heading_deg", "error_m")
_CONSOLE_STAMP = re.compile(r"^\[\s*[-\d.]+\]\s?")  # "[  12.34] " from the simulator console
_PORT = re.compile(r"^(m|r|imu|d|gps)(\d+)_")


def columns_for(config: RobotConfig) -> list[str]:
    """The log columns for a robot: its drive motors and every sensor."""
    columns = ["time_ms", "battery_mv", "battery_ma"]
    ports = sorted({abs(p) for g in config.drivetrain.gearing.values() for p in g.motors})
    for port in ports:
        columns += [f"m{port}_{name}" for name in MOTOR_FIELDS]
    for sensor in sorted(config.sensors, key=lambda s: s.port):
        p = sensor.port
        if sensor.type == "rotation":
            columns.append(f"r{p}_cdeg")
        elif sensor.type == "imu":
            columns.append(f"imu{p}_deg")
        elif sensor.type == "distance":
            columns.append(f"d{p}_mm")
        elif sensor.type == "gps":
            columns += [f"gps{p}_{name}" for name in GPS_FIELDS]
    return columns


@dataclass
class RobotLog:
    """Columns of floats (NaN where a reading was empty), one row per sample."""

    columns: dict[str, np.ndarray] = field(default_factory=dict)
    skipped_lines: int = 0  # malformed lines dropped while parsing

    def __len__(self) -> int:
        return len(self.time_ms)

    def __contains__(self, name: str) -> bool:
        return name in self.columns

    def __getitem__(self, name: str) -> np.ndarray:
        return self.columns[name]

    @property
    def time_ms(self) -> np.ndarray:
        return self.columns["time_ms"]

    @property
    def time_s(self) -> np.ndarray:
        return self.columns["time_ms"] / 1000.0

    def ports(self, kind: str) -> list[int]:
        """Ports with columns of a kind: ``m`` (motors), ``r``, ``imu``, ``d`` or ``gps``."""
        found = set()
        for name in self.columns:
            match = _PORT.match(name)
            if match and match.group(1) == kind:
                found.add(int(match.group(2)))
        return sorted(found)

    # --- reading and writing ------------------------------------------------------------

    @classmethod
    def from_rows(cls, names: list[str], rows: list[list[float]]) -> RobotLog:
        data = np.array(rows, dtype=float).reshape(len(rows), len(names))
        return cls({name: data[:, i].copy() for i, name in enumerate(names)})

    @classmethod
    def parse(cls, text: str) -> RobotLog:
        """A log from CSV text, or the last framed log in a terminal or console capture."""
        lines = [_CONSOLE_STAMP.sub("", line.rstrip("\r")) for line in text.splitlines()]
        stripped = [line.strip() for line in lines]
        if BEGIN in stripped:
            start = len(stripped) - 1 - stripped[::-1].index(BEGIN)
            end = stripped.index(END, start) if END in stripped[start:] else len(stripped)
            body = stripped[start + 1 : end]
        else:
            body = stripped
        body = [line for line in body if line and not line.startswith("#")]
        if not body or not body[0].startswith("time_ms"):
            raise ValueError("no robot log found (expected a CSV header starting with time_ms)")
        names = body[0].split(",")
        rows, skipped = [], 0
        for line in body[1:]:
            cells = line.split(",")
            if len(cells) != len(names):
                skipped += 1
                continue
            try:
                rows.append([float(c) if c else math.nan for c in cells])
            except ValueError:
                skipped += 1
        if not rows:
            raise ValueError("the robot log has a header but no rows")
        log = cls.from_rows(names, rows)
        log.skipped_lines = skipped
        return log

    @classmethod
    def read(cls, path: str | Path) -> RobotLog:
        data = Path(path).read_bytes()
        # Windows PowerShell's `>` writes UTF-16 with a byte-order mark.
        if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            text = data.decode("utf-16", errors="replace")
        else:
            text = data.decode("utf-8-sig", errors="replace")
        return cls.parse(text)

    def to_csv(self) -> str:
        names = list(self.columns)
        out = [",".join(names)]
        data = np.column_stack([self.columns[n] for n in names])
        for row in data:
            out.append(",".join(_cell(v) for v in row))
        return "\n".join(out) + "\n"

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(self.to_csv(), encoding="utf-8")
        return path


def _cell(value: float) -> str:
    if math.isnan(value):
        return ""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.6g}"

"""Robot logs: what a robot's own code measures, every 10 ms, as CSV.

vexsim's logger writes them on a real robot (C++: bridge/cpp/logger, ``vexsim logger add``),
the calibration routine logs through it, and ``RobotLogger`` records the same columns in
the simulator. Readings are raw, as PROS reports them for a positive port: a motor on a
negative config port reads backwards, and a rotation sensor reads as if it weren't reversed.

Format 2, the logger's:

  # vexsim-log: 2             "# key: value" lines before the header: what the log is (name,
  # name: Left 40             started_ms, mode, battery_pct, devices) and what the code
  ...                         added (vexsim_log::info)
  time_ms,battery_mv,...      the header, then a row every 10 ms
  #mark,500,intake on         a mark the code made (vexsim_log::mark), among the rows

Format 1, the calibration routine's before the logger, has only the header and rows, and
its distance sensors only ``d<p>_mm``; both read. Columns (``<p>`` is the smart port):

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
  d<p>_mm d<p>_conf d<p>_size
                             distance (empty when nothing is in range), the sensor's
                             confidence (0-63) and the object's size (0-400)
  gps<p>_x_m gps<p>_y_m gps<p>_heading_deg gps<p>_error_m
                             GPS position, heading and error estimate
  pose_<name>_x_in pose_<name>_y_in pose_<name>_theta_deg
                             a pose the code logged (vexsim_log::pose), as LemLib has them:
                             inches, degrees clockwise from +y
  val_<name>                 a number the code logged (vexsim_log::value)

Motors come first, then the other devices, each by port. Printed logs are framed by
``#vexsim-log begin`` and ``#vexsim-log end`` lines, so a log can be cut out of any terminal
capture or simulator console output.
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
DISTANCE_FIELDS = ("mm", "conf", "size")
GPS_FIELDS = ("x_m", "y_m", "heading_deg", "error_m")
POSE_FIELDS = ("x_in", "y_in", "theta_deg")
_CONSOLE_STAMP = re.compile(r"^\[\s*[-\d.]+\]\s?")  # "[  12.34] " from the simulator console
_PORT = re.compile(r"^(m|r|imu|d|gps)(\d+)_")
_POSE = re.compile(r"^pose_(\w+)_x_in$")
_INFO = re.compile(r"^#\s*([A-Za-z0-9_.-]+):\s?(.*)$")  # "# name: Left 40"


def motor_ports(config: RobotConfig) -> list[int]:
    """Every motor's port: the drive's and the mechanisms'."""
    ports = {abs(p) for g in config.drivetrain.gearing.values() for p in g.motors}
    ports |= {abs(p) for m in config.mechanisms.values() for p in m.motors}
    return sorted(ports)


def columns_for(config: RobotConfig) -> list[str]:
    """The columns vexsim's logger writes for a robot's devices: every motor, then every
    sensor, each by port (before any poses or numbers the code adds)."""
    columns = ["time_ms", "battery_mv", "battery_ma"]
    for port in motor_ports(config):
        columns += [f"m{port}_{name}" for name in MOTOR_FIELDS]
    for sensor in sorted(config.sensors, key=lambda s: s.port):
        p = sensor.port
        if sensor.type == "rotation":
            columns.append(f"r{p}_cdeg")
        elif sensor.type == "imu":
            columns.append(f"imu{p}_deg")
        elif sensor.type == "distance":
            columns += [f"d{p}_{name}" for name in DISTANCE_FIELDS]
        elif sensor.type == "gps":
            columns += [f"gps{p}_{name}" for name in GPS_FIELDS]
    return columns


@dataclass
class RobotLog:
    """Columns of floats (NaN where a reading was empty), one row per sample."""

    columns: dict[str, np.ndarray] = field(default_factory=dict)
    skipped_lines: int = 0  # malformed lines dropped while parsing
    info: dict[str, str] = field(default_factory=dict)  # its "# key: value" lines
    marks: list[tuple[float, str]] = field(default_factory=list)  # (time_ms, text)

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

    def poses(self) -> list[str]:
        """The names of the poses the code logged (``vexsim_log::pose``)."""
        return [m.group(1) for name in self.columns if (m := _POSE.match(name))]

    def pose(self, name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """A logged pose's x and y (inches) and theta (degrees clockwise from +y)."""
        x, y, theta = (self.columns[f"pose_{name}_{k}"] for k in POSE_FIELDS)
        return x, y, theta

    # --- reading and writing ------------------------------------------------------------

    @classmethod
    def from_rows(
        cls,
        names: list[str],
        rows: list[list[float]],
        info: dict[str, str] | None = None,
        marks: list[tuple[float, str]] | None = None,
    ) -> RobotLog:
        data = np.array(rows, dtype=float).reshape(len(rows), len(names))
        columns = {name: data[:, i].copy() for i, name in enumerate(names)}
        return cls(columns, info=dict(info or {}), marks=list(marks or []))

    @classmethod
    def parse(cls, text: str) -> RobotLog:
        """A log from CSV text, or the last framed log in a terminal or console capture."""
        return _parse_body(_bodies(text)[-1])

    @classmethod
    def parse_all(cls, text: str) -> list[RobotLog]:
        """Every framed log in a terminal or console capture, in order, leaving out any that
        doesn't read (the text itself if nothing is framed)."""
        logs = []
        bodies = _bodies(text)
        for body in bodies:
            try:
                logs.append(_parse_body(body))
            except ValueError:
                if len(bodies) == 1:
                    raise
        if not logs:
            raise ValueError("no robot log found (expected a CSV header starting with time_ms)")
        return logs

    @classmethod
    def read(cls, path: str | Path) -> RobotLog:
        return cls.parse(_decoded(Path(path).read_bytes()))

    @classmethod
    def read_all(cls, path: str | Path) -> list[RobotLog]:
        """Every log in a file: a log, or a terminal capture with several."""
        return cls.parse_all(_decoded(Path(path).read_bytes()))

    def to_csv(self) -> str:
        names = list(self.columns)
        out = [f"# {key}: {value}" for key, value in self.info.items()]
        out.append(",".join(names))
        data = np.column_stack([self.columns[n] for n in names])
        marks, m = sorted(self.marks), 0
        for t, row in zip(self.time_ms, data, strict=True):
            for at, text in marks[m:]:
                if at > t:
                    break
                out.append(f"#mark,{_cell(at)},{text}")
                m += 1
            out.append(",".join(_cell(v) for v in row))
        out += [f"#mark,{_cell(at)},{text}" for at, text in marks[m:]]
        return "\n".join(out) + "\n"

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(self.to_csv(), encoding="utf-8")
        return path


def _decoded(data: bytes) -> str:
    # Windows PowerShell's `>` writes UTF-16 with a byte-order mark.
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def _bodies(text: str) -> list[list[str]]:
    """The lines of each framed log in ``text``, or all of it if nothing is framed."""
    lines = [_CONSOLE_STAMP.sub("", line.rstrip("\r")).strip() for line in text.splitlines()]
    bodies, at = [], 0
    while BEGIN in lines[at:]:
        start = lines.index(BEGIN, at)
        end = lines.index(END, start) if END in lines[start:] else len(lines)
        bodies.append(lines[start + 1 : end])
        at = end + 1
    return bodies or [lines]


def _parse_body(body: list[str]) -> RobotLog:
    info: dict[str, str] = {}
    marks: list[tuple[float, str]] = []
    names: list[str] | None = None
    rows, skipped = [], 0
    for line in body:
        if not line:
            continue
        if line.startswith("#"):
            if names is None and (match := _INFO.match(line)):
                info[match.group(1)] = match.group(2).strip()
            elif names is not None and line.startswith("#mark,"):
                _, at, *text = line.split(",", 2)
                try:
                    marks.append((float(at), text[0] if text else ""))
                except ValueError:
                    skipped += 1
            continue
        if names is None:
            if not line.startswith("time_ms"):
                break
            names = line.split(",")
            continue
        cells = line.split(",")
        if len(cells) != len(names):
            skipped += 1
            continue
        try:
            rows.append([float(c) if c else math.nan for c in cells])
        except ValueError:
            skipped += 1
    if names is None:
        raise ValueError("no robot log found (expected a CSV header starting with time_ms)")
    if not rows:
        raise ValueError("the robot log has a header but no rows")
    log = RobotLog.from_rows(names, rows, info, marks)
    log.skipped_lines = skipped
    return log


def _cell(value: float) -> str:
    if math.isnan(value):
        return ""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.6g}"

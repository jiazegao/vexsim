"""A robot log (vexsim's logger, ``vexsim.calibration.log``), to play on the field as an MCL
log plays (``runs.mcl_tape``): where the robot's code thought it was (the first pose it
logged, as LemLib has them), its other logged poses (each with its path, ``LogPath``), and
each distance sensor's reading as a ray from where the robot config mounts it
(``RobotLogTape``).

A calibration program's log has no pose of the code's. One that starts on a spot of the plan's
(the push, the driving tests, the spins) plays from that spot by odometry: the IMU's turn and
the drive motors' travel, through the drive's kinematics. The others (the device check, the
free spin, the IMU still and turned by hand) don't take the robot anywhere on the field, so
they don't play (``NothingToPlay``), nor does the quick fit's routine, which logs no pose.

There's no truth in a real robot's log: only the robot knew where it was.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from vexsim.app.jsonsafe import finite
from vexsim.config.robot import RobotConfig

MAX_FRAMES = 2000  # a long log is played at every so-many rows
MM_PER_IN = 25.4
NO_READING_IN = 10.0  # how long a ray that read nothing is drawn (as MCL logs' are)
POSE_COLORS = ("violet", "aqua", "magenta", "green")  # the code's other poses


class LogTapeError(ValueError):
    """The log can't be played on the field (the message says why)."""


class NothingToPlay(LogTapeError):
    """The log reads, but has no path to play: no pose of its code's, and no spot it started on
    (the quick fit's routine, a calibration test done by hand)."""


def robot_log_tape(path: Path, shown: str, config: RobotConfig | None) -> dict:
    """``RobotLogTape``: the log at ``path`` (``shown``: its path as the user names it), its
    rays drawn from where ``config`` mounts the distance sensors (none without one). Raises
    LogTapeError if it doesn't read, NothingToPlay if it has no path to play."""
    from vexsim.calibration.log import RobotLog
    from vexsim.runtime.follow import set_pose_rows

    try:
        log = RobotLog.read(path)
    except (OSError, ValueError) as exc:
        raise LogTapeError(str(exc)) from None
    if len(log) < 2:
        raise LogTapeError("the log has fewer than two rows")
    names = log.poses()
    if names:
        source = names[0]
        rows = set_pose_rows(log, source)
        x, y, theta = (v[rows] for v in log.pose(source))
        heading = np.unwrap(np.radians(90.0 - theta))
    elif "spot" in log.info:
        if config is None:
            raise LogTapeError("pick the robot it ran on: it's played from its spot by odometry")
        source = "odometry"
        rows, x, y, heading = odometry(log, config)
    else:
        test = log.info.get("test")
        what = f"its test ({test.replace('_', ' ')}) doesn't" if test else "it doesn't"
        raise NothingToPlay(
            f"the log has no pose of its code's (vexsim_log::pose), and {what} start on a spot "
            "of the plan's: there's nothing to play on the field"
        )
    if len(rows) < 2:
        raise LogTapeError(f"the log's {source} pose has fewer than two readings")
    frames = np.unique(np.linspace(0, len(rows) - 1, min(len(rows), MAX_FRAMES)).astype(int))
    rows, x, y, heading = rows[frames], x[frames], y[frames], heading[frames]
    times = log.time_s[rows] - log.time_s[rows[0]]
    sensors = _distance_sensors(log, config)
    others = [n for n in names if n != source]
    drawings = []
    seen = total = 0
    for k, row in enumerate(rows):
        rays: list[list] = []
        for port, (sx, sy), facing in sensors:
            mm = log[f"d{port}_mm"][row]
            total += 1
            ox, oy = _moved(x[k], y[k], heading[k], sx, sy)
            angle = heading[k] + facing
            if math.isfinite(mm) and mm > 0:
                seen += 1
                length = mm / MM_PER_IN
                end = (ox + length * math.cos(angle), oy + length * math.sin(angle))
                rays.append(["line", _r(ox), _r(oy), _r(end[0]), _r(end[1]), "yellow"])
                rays.append(["point", _r(end[0]), _r(end[1]), "yellow", 5])
            else:
                end = (ox + NO_READING_IN * math.cos(angle), oy + NO_READING_IN * math.sin(angle))
                rays.append(["line", _r(ox), _r(oy), _r(end[0]), _r(end[1]), "muted"])
        poses = []
        for n, other in enumerate(others):
            px, py, ptheta = (v[row] for v in log.pose(other))
            if math.isfinite(px) and math.isfinite(py) and math.isfinite(ptheta):
                color = POSE_COLORS[n % len(POSE_COLORS)]
                poses.append(["pose", _r(px), _r(py), _r(90.0 - ptheta), color])
        layers: dict[str, list] = {}
        if sensors:
            layers["rays"] = rays
        if others:
            layers["poses"] = poses
        drawings.append([_r(times[k]), layers])
    paths = [_path(log, other, rows, POSE_COLORS[n % len(POSE_COLORS)])
             for n, other in enumerate(others)]  # fmt: skip
    gaps = np.diff(log.time_ms)
    estimate = [
        [_r(a), _r(b), round(math.degrees(h) % 360, 2)]
        for a, b, h in zip(x, y, heading, strict=True)
    ]
    summary = {
        "rows": len(log),
        "duration_s": _r(times[-1]),
        "interval_ms": _r(float(np.median(gaps))) if len(gaps) else None,
        "pose": source,
        "poses": names,
        "start": estimate[0],
        "distance_sensors": len(sensors),
        "no_reading_pct": _r(100 * (total - seen) / total) if total else None,
        "robot": log.info.get("robot"),
        "field": log.info.get("field"),
        "test": log.info.get("test"),
        "routine": None
        if log.info.get("program") == "vexsim calibration"
        else log.info.get("name"),
    }
    return finite(
        {
            "kind": "robot",
            "name": log.info.get("name") or path.stem,
            "path": shown,
            "summary": summary,
            "times": [_r(t) for t in times],
            "estimate": estimate,
            "drawings": drawings,
            "paths": [p for p in paths if p is not None],
        }
    )


def _path(log, name: str, rows: np.ndarray, color: str) -> dict | None:
    """Another logged pose's path, a point a frame (``LogPath``): from its first reading on,
    a frame without one keeping the point before. None if it has no reading at all."""
    x, y, _ = log.pose(name)
    x, y = x[rows], y[rows]
    known = np.isfinite(x) & np.isfinite(y)
    if not known.any():
        return None
    first = int(np.argmax(known))
    last = np.maximum.accumulate(np.where(known, np.arange(len(rows)), first))[first:]
    return {
        "name": name,
        "color": color,
        "first": first,
        "xs": [_r(v) for v in x[last]],
        "ys": [_r(v) for v in y[last]],
    }


def odometry(log, config: RobotConfig) -> tuple[np.ndarray, ...]:
    """Where a calibration log's robot went from its spot (the log's ``spot`` line: x, y in,
    heading degrees counter-clockwise): its heading by the IMU (its scale error taken out),
    its travel by the drive motors' degrees through the drive's kinematics, least squares
    over the motor groups. The rows it knows, and x, y (in) and heading (radians, unwrapped)
    at each. Raises LogTapeError without an IMU or the drive's motors."""
    from vexsim.physics.kinematics import DriveKinematics
    from vexsim.units import m_to_in

    try:
        sx, sy, sh = (float(v) for v in log.info["spot"].split()[:3])
    except (KeyError, ValueError):
        raise LogTapeError("the log's spot line doesn't read as x, y and a heading") from None
    imu = next((s for s in config.sensors if s.type == "imu" and f"imu{s.port}_deg" in log), None)
    if imu is None:
        raise LogTapeError("odometry turns by the IMU, and the log has none of the robot's")
    kin = DriveKinematics.from_config(config)
    angles = []
    for name, gear in config.drivetrain.gearing.items():
        columns = [
            log[f"m{abs(p)}_deg"] * (1.0 if p > 0 else -1.0)
            for p in gear.motors
            if f"m{abs(p)}_deg" in log
        ]
        if not columns:
            raise LogTapeError(f"the log has none of the {name} motors: is it this robot's?")
        angles.append(np.radians(np.mean(columns, axis=0)))
    turned = log[f"imu{imu.port}_deg"]
    group = np.array(angles)
    rows = np.flatnonzero(np.isfinite(turned) & np.all(np.isfinite(group), axis=0))
    if len(rows) < 2:
        raise LogTapeError("the log's IMU and motors have fewer than two readings together")
    scale = imu.scale_error if imu.scale_error is not None else 0.0
    heading = math.radians(sh) - np.radians(turned[rows] - turned[rows[0]]) / (1.0 + scale)
    motion = np.diff(group[:, rows], axis=1)  # each group's motor turn, row to row (rad)
    turn = np.diff(heading)
    # the robot's own forward and leftward travel (m) each row, given its turn
    rest = motion - kin.matrix[:, 2:3] * turn
    travel = np.linalg.lstsq(kin.matrix[:, :2], rest, rcond=None)[0]
    middle = heading[:-1] + turn / 2
    dx = travel[0] * np.cos(middle) - travel[1] * np.sin(middle)
    dy = travel[0] * np.sin(middle) + travel[1] * np.cos(middle)
    x = sx + m_to_in(np.concatenate([[0.0], np.cumsum(dx)]))
    y = sy + m_to_in(np.concatenate([[0.0], np.cumsum(dy)]))
    return rows, x, y, heading


def _distance_sensors(log, config: RobotConfig | None) -> list[tuple[int, tuple, float]]:
    """The config's distance sensors the log read: port, where (x, y in, the robot's frame)
    and which way the beam points (radians)."""
    if config is None:
        return []
    return [
        (s.port, (float(s.pos_in[0]), float(s.pos_in[1])), math.radians(s.heading_deg))
        for s in config.sensors
        if s.type == "distance" and f"d{s.port}_mm" in log
    ]


def _moved(x: float, y: float, heading: float, sx: float, sy: float) -> tuple[float, float]:
    c, s = math.cos(heading), math.sin(heading)
    return x + c * sx - s * sy, y + s * sx + c * sy


def _r(value: float) -> float:
    return round(float(value), 3)

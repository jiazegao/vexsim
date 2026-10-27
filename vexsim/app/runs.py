"""Recorded runs: every run in the browser app is kept in the workspace's .vexsim/runs/.

A run's folder holds:

- ``run.json``: what ran (the spec, the command, robot and field), how it ended, how far
  the robot code's pose was from the truth (``RunRecord``)
- ``tape.json.gz``: the field as the browser draws it, every ``TAPE_PERIOD_S`` of simulated
  time, for scrubbing back and forth (the scene, frames, and when the motion overlay and
  the screens changed)
- ``telemetry.csv.gz``: the 10 ms telemetry log of ``vexsim run --record`` (for plots;
  ``vexsim plot`` and ``vexsim replay`` read it too)
- ``console.txt``: what the program printed
- ``sd/``: the robot's SD card (``VEXSIM_SD_DIR``), for programs that write logs to it

Only the newest ``KEEP`` runs stay, plus the ones marked kept. ``VEXSIM_RUNS_DIR`` puts
them somewhere else.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from vexsim.app.jsonsafe import finite
from vexsim.app.runspec import RunSpec

RUNS_DIR = ".vexsim/runs"
KEEP = 50
TAPE_PERIOD_S = 0.05
MAX_SAMPLES = 36_000  # 30 min at TAPE_PERIOD_S; past that, every other sample goes
PLOT_POINTS = 5_000  # telemetry rows sent for plots, at most
_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")

Ended = Literal["finished", "stopped", "restarted", "error"]


class PoseErrorSummary(BaseModel):
    """How far the robot code's pose was from the true one (see ``Recorder.pose_error``)."""

    model_config = ConfigDict(extra="forbid")

    mean_in: float
    max_in: float
    max_at_s: float
    final_in: float
    mean_deg: float
    max_deg: float


class RunRecord(BaseModel):
    """A recorded run, as its run.json has it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    created: float  # when it started (Unix time)
    spec: RunSpec
    command: str
    mode: str
    robot: str  # the robot's and the field's names
    field: str
    duration: float  # simulated seconds
    ended: Ended
    message: str | None
    pose_error: PoseErrorSummary | None
    samples: int
    kept: bool = False


def runs_root(workspace: str | Path) -> Path:
    """Where a workspace's runs are recorded."""
    elsewhere = os.environ.get("VEXSIM_RUNS_DIR")
    return Path(elsewhere) if elsewhere else Path(workspace) / RUNS_DIR


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def run_dir(root: Path, run_id: str) -> Path:
    """A run's folder; raises ValueError for anything that isn't a run id."""
    if not _ID.match(run_id):
        raise ValueError(f"no run {run_id!r}")
    return root / run_id


def default_name(spec: RunSpec, robot: str) -> str:
    """What a run is called when it wasn't started from a saved run."""
    if spec.program:
        program = Path(spec.program)
        what = program.parent.name if program.name == "project.pros" else program.name
    else:
        what = "driving"
    auton = spec.env.get("VEXSIM_AUTON")
    return f"{what}{f' ({auton})' if auton else ''} · {robot}"


# --- writing (in the run's worker process) ---------------------------------------------------


class TapeRecorder:
    """Records one run as it goes; ``finish`` writes its folder."""

    def __init__(self, folder: Path, record: dict[str, Any], scene: dict[str, Any]):
        self.folder = folder
        self.record = record  # RunRecord fields known at the start
        self.scene = {k: v for k, v in scene.items() if k != "type"}
        self.samples: list[dict] = []
        self.events: dict[str, list] = {"overlay": [], "lcd": [], "controller_screen": []}
        self.next_t = 0.0
        self.period = TAPE_PERIOD_S
        self.finished = False

    def due(self, t: float) -> bool:
        return not self.finished and t >= self.next_t - 1e-9

    def sample(self, frame: dict, overlay: dict) -> None:
        """Keep a frame (``frames.frame_of``) and anything that changed since the last."""
        t = frame["t"]
        sample = {
            k: v
            for k, v in frame.items()
            if k not in ("type", "state", "speed", "rate", "lcd", "controller_screen")
        }
        self.samples.append(sample)
        self._event("overlay", t, {"path": overlay["path"], "target": overlay["target"]})
        self._event("lcd", t, frame["lcd"])
        self._event("controller_screen", t, frame["controller_screen"])
        self.next_t = t + self.period
        if len(self.samples) > MAX_SAMPLES:  # a long session: keep all of it, more coarsely
            self.samples = self.samples[::2]
            self.period *= 2

    def _event(self, name: str, t: float, value) -> None:
        events = self.events[name]
        if not events or events[-1][1] != value:
            events.append([t, value])

    def finish(
        self,
        ended: Ended,
        message: str | None,
        *,
        duration: float,
        recorder=None,
        console: list[str] = (),
    ) -> RunRecord:
        """Write the run's folder (once) and return its record."""
        self.finished = True
        self.folder.mkdir(parents=True, exist_ok=True)
        error = recorder.pose_error() if recorder is not None and recorder.rows else None
        record = RunRecord(
            **self.record,
            duration=round(duration, 3),
            ended=ended,
            message=message,
            pose_error=None if error is None else PoseErrorSummary(**_rounded(vars(error))),
            samples=len(self.samples),
        )
        tape = {"scene": self.scene, "samples": self.samples, "events": self.events}
        with gzip.open(self.folder / "tape.json.gz", "wt", encoding="utf-8") as f:
            json.dump(finite(tape), f, separators=(",", ":"))
        if recorder is not None and recorder.rows:
            recorder.write_csv(self.folder / "telemetry.csv.gz")
        (self.folder / "console.txt").write_text(
            "".join(f"{line}\n" for line in console), encoding="utf-8"
        )
        _write_record(self.folder, record)
        return record


def _rounded(values: dict) -> dict:
    return {k: round(float(v), 3) for k, v in values.items()}


def _write_record(folder: Path, record: RunRecord) -> None:
    path = folder / "run.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def prune(root: Path, keep: int = KEEP) -> list[str]:
    """Delete all but the newest ``keep`` runs (and the kept ones); returns the ids gone."""
    gone = []
    for record in list_runs(root)[keep:]:
        if not record.kept:
            shutil.rmtree(root / record.id, ignore_errors=True)
            gone.append(record.id)
    return gone


# --- reading (in the server) -----------------------------------------------------------------


def list_runs(root: Path) -> list[RunRecord]:
    """Every recorded run, newest first (folders that don't read are skipped)."""
    records = []
    if root.is_dir():
        for folder in root.iterdir():
            if _ID.match(folder.name) and (folder / "run.json").is_file():
                try:
                    records.append(read_record(root, folder.name))
                except (OSError, ValueError, ValidationError):
                    continue
    return sorted(records, key=lambda r: r.created, reverse=True)


def read_record(root: Path, run_id: str) -> RunRecord:
    path = run_dir(root, run_id) / "run.json"
    return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))


def update_record(root: Path, run_id: str, *, kept: bool | None = None, name=None) -> RunRecord:
    record = read_record(root, run_id)
    changes = {k: v for k, v in (("kept", kept), ("name", name)) if v is not None}
    record = record.model_copy(update=changes)
    _write_record(run_dir(root, run_id), record)
    return record


def delete_run(root: Path, run_id: str) -> None:
    folder = run_dir(root, run_id)
    if not folder.is_dir():
        raise FileNotFoundError(run_id)
    shutil.rmtree(folder)


def read_console(root: Path, run_id: str) -> list[str]:
    path = run_dir(root, run_id) / "console.txt"
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def read_tape(root: Path, run_id: str) -> dict:
    with gzip.open(run_dir(root, run_id) / "tape.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


def telemetry_path(root: Path, run_id: str) -> Path:
    return run_dir(root, run_id) / "telemetry.csv.gz"


def telemetry_columns(path: Path, points: int = PLOT_POINTS) -> dict:
    """A telemetry log as columns for plots: at most ``points`` rows, every column, the
    pose error (in, deg) when there's an estimate, and where each phase begins."""
    from vexsim.runtime.recorder import Log

    log = Log.read(path)
    stride = max(1, math.ceil(len(log) / points))
    rows = slice(None, None, stride)
    columns = {c: _column(log[c][rows]) for c in log.columns}
    dx, dy = log["x_in"] - log["est_x_in"], log["y_in"] - log["est_y_in"]
    turn = (log["heading_deg"] - log["est_heading_deg"] + 180.0) % 360.0 - 180.0
    columns["error_in"] = _column(((dx**2 + dy**2) ** 0.5)[rows])
    columns["error_deg"] = _column(abs(turn)[rows])
    phases, last = [], None
    for t, phase in zip(log["time_s"], log.phase, strict=True):
        if phase != last:
            phases.append([round(float(t), 3), phase])
            last = phase
    return {"columns": columns, "phases": phases}


def _column(values) -> list:
    return [None if not math.isfinite(v) else round(float(v), 4) for v in values]


# --- a telemetry log as a tape ---------------------------------------------------------------


def replay_of(log_path: Path, config, field, robot_path: str, log_name: str | None = None) -> dict:
    """A telemetry log (``vexsim run --record``) as a tape and plot columns, drawn with
    ``config`` on ``field``: the poses, estimate, speed, battery, motors and mechanisms
    move; wheels show no slip, and pieces stay where the field config puts them.
    ``log_name``: the log as the user names it (in the command), if not its file name."""
    from vexsim.app.frames import preview_of
    from vexsim.runtime.recorder import Log

    log = Log.read(log_path)
    preview = preview_of(config, field)
    robot = preview["robot"]
    ports = log.motor_ports
    names = [m["name"] for m in robot["mechanisms"]]
    rows = range(0, len(log), max(1, round(TAPE_PERIOD_S / 0.01)))  # the log: every 10 ms
    still = {"analog": {"LEFT_X": 0, "LEFT_Y": 0, "RIGHT_X": 0, "RIGHT_Y": 0}, "digital": []}
    samples = []
    for i in rows:
        x, y, heading = (float(log[c][i]) for c in ("x_in", "y_in", "heading_deg"))
        est = [float(log[c][i]) for c in ("est_x_in", "est_y_in", "est_heading_deg")]
        c, s = math.cos(math.radians(heading)), math.sin(math.radians(heading))
        samples.append(
            {
                "t": round(float(log["time_s"][i]), 3),
                "phase": log.phase[i],
                "pose": [round(x, 3), round(y, 3), round(heading, 2)],
                "estimate": None if any(math.isnan(v) for v in est) else [round(v, 3) for v in est],
                "speed_in_s": round(float(log["speed_in_s"][i]), 2),
                "battery": [round(float(log["battery_v"][i]), 2), float(log["battery_soc"][i])],
                "wheels": [
                    [
                        round(x + c * w["x"] - s * w["y"], 3),
                        round(y + s * w["x"] + c * w["y"], 3),
                        round(heading + w["heading"], 2),
                        0.0,
                        0.0,
                    ]
                    for w in robot["wheels"]
                ],
                "distance": {},
                "pieces": preview["pieces"],
                "contacts": [],
                "motors": [
                    [
                        p,
                        round(float(log[f"motor{p}_current_a"][i]), 2),
                        round(float(log[f"motor{p}_temp_c"][i]), 1),
                        False,
                    ]
                    for p in ports
                ],
                "controller": still,
                "imu": {},
                "gps": {},
                "mechanisms": [
                    round(float(log[f"{n}_deg"][i]), 1) if f"{n}_deg" in log.columns else 0.0
                    for n in names
                ],
                "period_left": None,
            }
        )
    first = samples[0]["pose"] if samples else [0.0, 0.0, 0.0]
    scene = {
        "robot": robot,
        "field": preview["field"],
        "mode": "replay",
        "start": first,
        "seed": 0,
        "spec": RunSpec(robot=robot_path).model_dump(mode="json"),
        "command": f"vexsim replay {robot_path} {log_name or log_path.name}",
        "run_id": None,
    }
    events = {"overlay": [], "lcd": [], "controller_screen": []}
    return {
        "name": f"{log_path.name} (replay)",
        "tape": finite({"scene": scene, "samples": samples, "events": events}),
        "telemetry": telemetry_columns(log_path),
    }

"""A calibration session's logs, gathered into a folder with what each one is (phase 14.4).

    SESSION/
      session.yaml   the robot, the field, and each run: its log, test and run, how it
                     ended, its warnings and quality, and whether the fit uses it
      runs/          the logs, named as the program named them (vexsim_0007_straight.csv)
      report/        what vexsim calibrate found (calibration/session_fit.py)

``collect(session, files)`` copies in the logs of the calibration program (calibration/
program.py) that aren't there yet, and checks each: that it's the session robot's, how it
ended, what it warned of. ``vexsim calibration collect SESSION`` takes them from the SD card
(``--from-card`` finds it), a folder (``--from``), or over USB as they arrive (``--usb``,
around ``pros terminal``). session.yaml is the students' to edit too: ``use: false`` leaves a
run out of the fit.
"""

from __future__ import annotations

import hashlib
import os
import re
import string
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import yaml

from vexsim.calibration.log import BEGIN, END, RobotLog

PROGRAM = "vexsim calibration"  # the program's logs say so (info "program")
TURN_SLACK = 0.05  # an IMU turns run more than 5% from 10 turns wasn't 10 turns
HEADER = (
    "# A calibration session (vexsim calibration collect adds its runs; vexsim calibrate fits\n"
    "# them). Set a run's use: false to leave it out of the fit.\n"
)


@dataclass
class Run:
    """One log of the session, and what to make of it."""

    file: str  # in runs/
    test: str  # the program's test (device_check, free_spin, ..., straight, sweep_1)
    run: int
    name: str  # the log's own name
    started_ms: int  # by the brain's clock: the order the runs were made in
    ended: str  # "finished", or why it stopped
    quality: str  # "good", or what's wrong with it
    use: bool  # whether the fit uses it
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        out = asdict(self)
        if not self.warnings:
            del out["warnings"]
        return out


@dataclass
class Session:
    folder: Path
    robot: str | None = None  # the robot's name, from its logs
    runs: list[Run] = field(default_factory=list)
    field_name: str | None = None  # the field's name, from its logs

    @property
    def runs_dir(self) -> Path:
        return self.folder / "runs"

    @property
    def file(self) -> Path:
        return self.folder / "session.yaml"

    @classmethod
    def open(cls, folder: str | Path) -> Session:
        """The session in ``folder``, or a new one if it has none yet."""
        folder = Path(folder)
        path = folder / "session.yaml"
        if not path.is_file():
            return cls(folder)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        runs = [
            Run(**{k: v for k, v in r.items() if k in Run.__dataclass_fields__})
            for r in data.get("runs") or []
        ]
        return cls(folder, data.get("robot"), runs, data.get("field"))

    def save(self) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        runs = sorted(self.runs, key=lambda r: (r.started_ms, r.file))
        data = {"robot": self.robot, "field": self.field_name, "runs": [r.to_dict() for r in runs]}
        text = yaml.safe_dump(data, sort_keys=False, width=200, default_flow_style=None)
        self.file.write_text(HEADER + text, encoding="utf-8", newline="\n")
        return self.file

    def logs(self, test: str | None = None, *, used: bool = True) -> list[tuple[Run, RobotLog]]:
        """The session's runs (of one test, if given) and their logs, oldest first; only those
        the fit uses, unless ``used`` is False."""
        out = []
        for run in sorted(self.runs, key=lambda r: (r.started_ms, r.file)):
            if (test is None or run.test == test) and (run.use or not used):
                out.append((run, RobotLog.read(self.runs_dir / run.file)))
        return out


# --- collecting ------------------------------------------------------------------------------


def check(log: RobotLog) -> tuple[str, bool, list[str]]:
    """A calibration log's quality ("good", or what's wrong), whether the fit should use it,
    and its warnings."""
    info = log.info
    warnings = [v for k, v in info.items() if k == "warning"]
    warnings += [text for _, text in log.marks if text == "slowed suddenly"]
    ended = info.get("ended", "")
    test = info.get("test", "")
    if ended.startswith("stopped"):
        return ended, False, warnings
    if ended != "finished":
        return "it didn't finish (the program was stopped?)", False, warnings
    if test == "device_check" and info.get("check") != "passed":
        return "the device check failed", False, warnings
    if test == "imu_turns":
        turned = _turned(log)
        if turned is None or abs(abs(turned) / 3600.0 - 1) > TURN_SLACK:
            shown = "no IMU" if turned is None else f"{abs(turned):.0f} degrees"
            return f"not 10 turns ({shown})", False, warnings
    if "slowed suddenly" in warnings:
        return "it slowed suddenly: did it hit something?", False, warnings
    return "good", True, warnings


def _turned(log: RobotLog) -> float | None:
    ports = log.ports("imu")
    if not ports:
        return None
    rotation = log[f"imu{ports[0]}_deg"]
    known = rotation[np.isfinite(rotation)]
    return float(known[-1] - known[0]) if len(known) > 1 else None


def collect(
    session: Session, paths: Iterable[str | Path], *, say: Callable[[str], None] | None = None
) -> list[Run]:
    """Copy the calibration logs among ``paths`` that the session doesn't have into its
    runs/, check each, and list them in session.yaml; the runs added."""
    say = say or (lambda text: None)
    session.runs_dir.mkdir(parents=True, exist_ok=True)
    have = {
        _digest((session.runs_dir / r.file).read_bytes())
        for r in session.runs
        if (session.runs_dir / r.file).is_file()
    }
    added = []
    for path in sorted(Path(p) for p in paths):
        data = path.read_bytes()
        digest = _digest(data)
        if digest in have:
            continue
        try:
            log = RobotLog.parse(_text(data))
        except ValueError as exc:
            say(f"{path.name}: not a robot log ({exc})")
            continue
        run = add(session, log, data, path.name, say=say)
        if run is not None:
            have.add(digest)
            added.append(run)
    session.save()
    return added


def add(
    session: Session,
    log: RobotLog,
    data: bytes,
    name: str,
    *,
    say: Callable[[str], None] | None = None,
) -> Run | None:
    """Add one log to the session (its bytes as they'll be saved, under ``name``, or a name
    like it if that's taken); None if it isn't one of the session's."""
    say = say or (lambda text: None)
    info = log.info
    if info.get("program") != PROGRAM:
        say(f"{name}: not the calibration program's log; left out")
        return None
    robot = info.get("robot")
    if session.robot is None:
        session.robot = robot
    elif robot != session.robot:
        say(f"{name}: {robot}'s log, not {session.robot}'s; left out")
        return None
    if session.field_name is None:
        session.field_name = info.get("field")
    target = session.runs_dir / name
    stem, suffix = Path(name).stem, Path(name).suffix or ".csv"
    n = 2
    while target.exists():
        target = session.runs_dir / f"{stem}.{n}{suffix}"
        n += 1
    session.runs_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    quality, use, warnings = check(log)
    run = Run(
        file=target.name,
        test=info.get("test", "?"),
        run=int(info.get("run", "1") or 1),
        name=info.get("name", ""),
        started_ms=int(float(info.get("started_ms", "0") or 0)),
        ended=info.get("ended", "?"),
        quality=quality,
        use=use,
        warnings=warnings,
    )
    session.runs.append(run)
    say(f"{target.name}: {run.test}, run {run.run}: {quality}")
    return run


def _digest(data: bytes) -> str:
    return hashlib.sha1(data.replace(b"\r\n", b"\n")).hexdigest()


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


# --- where the logs come from -------------------------------------------------------------------

CARD_LOG = re.compile(r"vexsim_\d{4}_.+\.csv$")


def card_logs(folder: Path) -> list[Path]:
    """The logs vexsim's logger saved at the root of a card (or a folder)."""
    try:
        return sorted(p for p in folder.iterdir() if p.is_file() and CARD_LOG.match(p.name))
    except OSError:
        return []


def find_card() -> Path | None:
    """The mounted SD card with vexsim's logs on it: a drive letter on Windows, under
    /Volumes on macOS, /media or /run/media on Linux. With several, the one written last."""
    if sys.platform == "win32":
        candidates = [Path(f"{letter}:\\") for letter in string.ascii_uppercase[3:]]
    elif sys.platform == "darwin":
        candidates = _children(Path("/Volumes"))
    else:
        user = os.environ.get("USER", "")
        candidates = [
            *_children(Path("/media") / user),
            *_children(Path("/run/media") / user),
            *_children(Path("/media")),
            *_children(Path("/mnt")),
        ]
    found = [(p, logs) for p in candidates if (logs := card_logs(p))]
    if not found:
        return None
    return max(found, key=lambda item: max(f.stat().st_mtime for f in item[1]))[0]


def _children(folder: Path) -> list[Path]:
    try:
        return [p for p in folder.iterdir() if p.is_dir()]
    except OSError:
        return []


def framed_logs(lines: Iterable[str]) -> Iterator[str]:
    """Each log framed between ``#vexsim-log begin`` and ``#vexsim-log end`` lines among the
    lines of a terminal, as it ends."""
    body: list[str] | None = None
    for line in lines:
        text = line.rstrip("\r\n")
        if text.strip() == BEGIN:
            body = [text]
        elif body is not None:
            body.append(text)
            if text.strip() == END:
                yield "\n".join(body) + "\n"
                body = None


def from_usb(
    session: Session,
    command: list[str] | None = None,
    *,
    say: Callable[[str], None] | None = None,
) -> list[Run]:
    """Run ``pros terminal`` (or ``command``) and add each log the program prints over USB
    (with no card in the brain), until it ends or Ctrl+C; the runs added."""
    say = say or (lambda text: None)
    command = command or ["pros", "terminal"]
    added: list[Run] = []
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"
        )
    except OSError as exc:
        raise OSError(f"couldn't run {' '.join(command)}: {exc}") from exc
    say(f"listening to {' '.join(command)}: run the tests; Ctrl+C when done")
    try:
        for text in framed_logs(process.stdout):
            log = RobotLog.parse(text)
            name = "usb_{:04d}_{}.csv".format(
                len(session.runs) + 1, _slug(log.info.get("name", "log"))
            )
            run = add(session, log, text.encode("utf-8"), name, say=say)
            if run is not None:
                added.append(run)
                session.save()
    except KeyboardInterrupt:
        pass
    finally:
        process.terminate()
    session.save()
    return added


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "log"

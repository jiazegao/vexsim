"""What's in a folder: robots, fields, scenarios, Python programs, PROS projects, inputs,
telemetry logs, calibration sessions, robot logs and MCL logs.

The UI works on one folder, its workspace. ``Workspace.scan`` finds what vexsim can use
in it by reading the files, never running them, and ``Workspace.path`` turns the paths the
UI sends back into files, refusing anything outside the folder. ``Workspace.stamp`` is a
cheap mark of what a scan would read (names, sizes and times; nothing is opened), so a scan
of a folder that hasn't changed is answered from the last one.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

ItemKind = Literal[
    "robot",
    "field",
    "scenario",
    "program",
    "project",
    "route",
    "input",
    "log",
    "calsession",
    "robotlog",
    "mcllog",
    "invalid",
]
KIND_ORDER: tuple[str, ...] = (
    "robot",
    "field",
    "program",
    "project",
    "route",
    "scenario",
    "input",
    "log",
    "calsession",
    "robotlog",
    "mcllog",
    "invalid",
)
SKIP_DIRS = {"node_modules", "__pycache__", "build", "dist", "bin", "venv", "env", "site-packages"}
MAX_DEPTH = 8
MAX_FILES = 20_000
MAX_READ = 512 * 1024  # bytes read to classify a file
# A file written this lately could be written again with the same size and the same time (a
# file system's clock ticks every few milliseconds, FAT's every two seconds), so a stamp
# with one in it doesn't stand for the folder's contents yet
RACY_S = 2.0

_PROGRAM_FUNCTION = re.compile(r"^def (initialize|autonomous|opcontrol)\b", re.MULTILINE)
_TELEMETRY_HEADER = "time_s,phase,x_in,y_in,heading_deg"
_ROBOT_LOG_HEADER = "time_ms,battery_mv"  # vexsim.calibration.log
_ROBOT_LOG_INFO = "# vexsim-log:"  # format 2 opens with its "# key: value" lines
_SESSION_FILE = "session.yaml"  # a calibration session's (vexsim.calibration.session)
_SESSION_PARTS = ("runs", "report")  # its logs and its report: the session's, not listed
_ROBOT_LOG_BEGIN = "#vexsim-log begin"  # a robot log in a terminal capture
_CAPTURES = (".txt", ".log")
MAX_CAPTURE = 20 * 1024 * 1024  # bytes: bigger text files aren't looked into
_INPUT_COLUMNS = {"LEFT_X", "LEFT_Y", "RIGHT_X", "RIGHT_Y", "buttons"}
# files that are never MCL logs (vexsim.mcllog), so aren't looked into for one
_NOT_LOGS = {
    ".md", ".json", ".toml", ".cfg", ".ini", ".js", ".ts", ".tsx", ".css", ".html",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".s", ".o", ".a", ".so", ".dll", ".exe", ".bin",
    ".elf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webm", ".mp4", ".pdf", ".zip",
    ".gz", ".tar", ".pyc", ".lock", ".sh", ".bat", ".ps1", ".pros",
}  # fmt: skip


@dataclass(frozen=True)
class WorkspaceItem:
    kind: ItemKind
    path: str  # relative to the workspace, with / separators
    name: str  # what to call it
    detail: str = ""  # a short description, e.g. "differential, 4 motors"
    problem: str = ""  # why it won't work as it is, if it won't

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WorkspaceStamp:
    """What a scan would read, in brief: ``digest`` of the name, size and time of every file
    it looks at. ``settled``: none of them was written in the last RACY_S, so two equal
    digests mean the same files."""

    digest: str
    settled: bool


class Workspace:
    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).resolve()
        self._kept: tuple[str, list[WorkspaceItem]] | None = None  # the last scan, by its stamp
        self.scans = 0  # full scans made (the tests count them)

    @property
    def name(self) -> str:
        return self.root.name or str(self.root)

    def path(self, relative: str) -> Path:
        """The file a workspace path names; raises ValueError for anything outside it."""
        path = (self.root / relative).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError(f"{relative} is outside the workspace")
        return path

    def relative(self, path: str | os.PathLike[str]) -> str:
        return Path(os.path.relpath(Path(path).resolve(), self.root)).as_posix()

    def scan(self, fresh: bool = False) -> list[WorkspaceItem]:
        """Everything vexsim can use in the workspace, grouped by kind, then by path.

        The last scan answers again while the folder's stamp is what it was then (``fresh``:
        read everything anyway)."""
        mark = self.stamp()
        kept = self._kept
        if not fresh and kept is not None and mark.settled and kept[0] == mark.digest:
            return list(kept[1])
        items = self._scan()
        self._kept = (mark.digest, items) if mark.settled else None
        return list(items)

    def stamp(self) -> WorkspaceStamp:
        """A mark of what ``scan`` would read, from the folders' listings alone: every file
        a scan looks at, and for a PROS project its routes and the headers they're checked
        against. It errs on the side of more files: a change that a scan wouldn't see only
        costs a scan."""
        from vexsim.app.routes import FOLDER
        from vexsim.bridge.build import SDK_INCLUDES

        digest = hashlib.sha1()
        newest = 0
        seen = 0

        def note(entry: os.DirEntry) -> None:
            nonlocal newest, seen
            try:
                st = entry.stat()
            except OSError:
                return
            seen += 1
            newest = max(newest, st.st_mtime_ns)
            digest.update(f"{entry.path}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())

        def listing(folder: str) -> list[os.DirEntry]:
            try:
                return sorted(os.scandir(folder), key=lambda e: e.name)
            except OSError:
                return []

        def whole(folder: str, skip=()) -> None:  # every file under a folder
            for entry in listing(folder):
                if entry.name in skip:
                    continue
                if entry.is_dir():
                    whole(entry.path)
                else:
                    note(entry)

        def walk(folder: str, depth: int) -> None:
            entries = listing(folder)
            if any(e.name == "project.pros" and not e.is_dir() for e in entries):
                for entry in entries:  # a project: its routes, and what they're checked against
                    if entry.name == "project.pros":
                        note(entry)
                    elif entry.name == FOLDER and entry.is_dir():
                        whole(entry.path)
                    elif entry.name == "include" and entry.is_dir():
                        whole(entry.path, SDK_INCLUDES)
                        lemlib = os.path.isdir(os.path.join(entry.path, "lemlib"))
                        digest.update(f"{entry.path}\0lemlib={lemlib}\n".encode())
                return
            for entry in entries:
                if not entry.is_dir():
                    note(entry)
                elif (
                    not entry.name.startswith(".")
                    and entry.name not in SKIP_DIRS
                    and depth < MAX_DEPTH
                ):
                    walk(entry.path, depth + 1)

        walk(str(self.root), 0)
        settled = seen <= MAX_FILES and newest <= time.time_ns() - int(RACY_S * 1e9)
        return WorkspaceStamp(digest.hexdigest()[:20], settled)

    def _scan(self) -> list[WorkspaceItem]:
        self.scans += 1
        items: list[WorkspaceItem] = []
        seen = 0
        for folder, dirs, files in os.walk(self.root):
            here = Path(folder)
            depth = len(here.relative_to(self.root).parts)
            if "project.pros" in files:
                items.append(self._project(here))
                items += self._routes(here)
                dirs[:] = []  # a project's sources and headers aren't workspace files
                continue
            session = self._session(here) if _SESSION_FILE in files else None
            if session is not None:
                items.append(session)
            dirs[:] = sorted(
                d
                for d in dirs
                if not d.startswith(".")
                and d not in SKIP_DIRS
                and depth < MAX_DEPTH
                and not (session is not None and d in _SESSION_PARTS)
            )
            for name in sorted(files):
                seen += 1
                if seen > MAX_FILES:
                    break
                item = self._classify(here / name)
                if item is not None:
                    items.append(item)
        order = {kind: i for i, kind in enumerate(KIND_ORDER)}
        return sorted(items, key=lambda i: (order[i.kind], i.path.lower()))

    # --- classifying files -----------------------------------------------------------------

    def _project(self, folder: Path) -> WorkspaceItem:
        lemlib = (folder / "include" / "lemlib").is_dir()
        return WorkspaceItem(
            "project",
            self.relative(folder),
            folder.name,
            "PROS project with LemLib" if lemlib else "PROS project",
        )

    def scan_routes(self, project: str | os.PathLike[str]) -> list[WorkspaceItem]:
        """A PROS project's autonomous routes (the YAML files in its routes/ folder)."""
        return self._routes(Path(project).resolve())

    def _routes(self, project: Path) -> list[WorkspaceItem]:
        """The project's autonomous routes: the YAML files in its routes/ folder."""
        from vexsim.app.routes import FOLDER, load_route

        folder = project / FOLDER
        items = []
        for path in sorted(folder.iterdir()) if folder.is_dir() else []:
            if path.suffix.lower() not in (".yaml", ".yml") or not path.is_file():
                continue
            checked = load_route(path)
            route = checked.route
            if route is None:
                problem = next(
                    (f"{i.location or '(document)'}: {i.message}" for i in checked.errors), ""
                )
                items.append(
                    WorkspaceItem("route", self.relative(path), path.name, problem=problem)
                )
                continue
            x, y, theta = route.start
            steps = len(route.steps)
            detail = (
                f"{steps} step{'s' if steps != 1 else ''}, from setPose({x:g}, {y:g}, {theta:g})"
            )
            errors = checked.errors
            problem = f"{errors[0].location or '(document)'}: {errors[0].message}" if errors else ""
            items.append(WorkspaceItem("route", self.relative(path), route.name, detail, problem))
        return items

    def _session(self, folder: Path) -> WorkspaceItem | None:
        """A calibration session (``vexsim calibration collect``'s folder): its runs, whose
        robot, and whether it's been fitted."""
        import yaml

        try:
            data = yaml.safe_load((folder / _SESSION_FILE).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
            return None
        runs = len(data["runs"])
        detail = f"calibration session: {runs} run{'s' if runs != 1 else ''}"
        if data.get("robot"):
            detail += f" of {data['robot']}"
        if (folder / "report" / "report.md").is_file():
            detail += ", fitted"
        return WorkspaceItem("calsession", self.relative(folder), folder.name, detail)

    def _classify(self, path: Path) -> WorkspaceItem | None:
        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            return self._config(path)
        if suffix == ".py":
            functions = _program_functions(_read(path) or "")
            if functions:
                return WorkspaceItem(
                    "program", self.relative(path), path.name, "Python: " + ", ".join(functions)
                )
            return None
        if suffix == ".csv":
            text = _read(path, 4096) or ""
            lines = text.splitlines()
            header = lines[0].lstrip("\ufeff") if lines else ""
            if header.startswith(_TELEMETRY_HEADER):
                return WorkspaceItem("log", self.relative(path), path.name, "telemetry log")
            if header.startswith(_ROBOT_LOG_HEADER):
                return WorkspaceItem("robotlog", self.relative(path), path.name, "robot log")
            if header.startswith("#"):  # format 2: its "# key: value" lines, then the header
                columns = next((line for line in lines if not line.startswith("#")), "")
                if header.startswith(_ROBOT_LOG_INFO) or columns.startswith(_ROBOT_LOG_HEADER):
                    detail = _robot_log_detail(lines)
                    return WorkspaceItem("robotlog", self.relative(path), path.name, detail)
            columns = {c.strip() for c in header.split(",")}
            if "time_s" in columns and columns & _INPUT_COLUMNS:
                return WorkspaceItem("input", self.relative(path), path.name, "controller input")
        if (
            suffix in _CAPTURES
            and _size(path) <= MAX_CAPTURE
            and _ROBOT_LOG_BEGIN in (_read(path) or "")
        ):
            detail = "robot log, in terminal output"
            return WorkspaceItem("robotlog", self.relative(path), path.name, detail)
        if suffix not in _NOT_LOGS and suffix != ".py":
            return self._mcl_log(path)
        return None

    def _mcl_log(self, path: Path) -> WorkspaceItem | None:
        from vexsim.mcllog import parse

        text = _read(path, 8192)
        if not text or "\0" in text:
            return None
        try:
            first = parse(text)[0]
        except ValueError:
            return None
        x, y, _ = first.estimate
        detail = f"MCL log: {len(first.sensors)} sensors, starts at ({x:.1f}, {y:.1f})"
        return WorkspaceItem("mcllog", self.relative(path), path.name, detail)

    def _config(self, path: Path) -> WorkspaceItem | None:
        from vexsim.config.issues import ConfigError
        from vexsim.config.yaml_io import load_yaml_file

        relative = self.relative(path)
        try:
            data = load_yaml_file(path)
        except ConfigError as exc:
            issue = exc.issues[0]
            where = f" ({issue.location})" if issue.location else ""
            return WorkspaceItem("invalid", relative, path.name, problem=issue.message + where)
        if not isinstance(data, dict):
            return None
        name = str(data.get("name") or path.stem)
        if "drivetrain" in data:
            return self._robot(path, relative, name)
        if "task" in data and "robot" in data:
            task = data.get("task")
            kind = task.get("type", "") if isinstance(task, dict) else ""
            return WorkspaceItem("scenario", relative, name, f"benchmark scenario: {kind}".strip())
        if "size_in" in data or "elements" in data:
            return self._field(path, relative, name)
        return None

    def _robot(self, path: Path, relative: str, name: str) -> WorkspaceItem:
        from vexsim.config.loader import validate_robot

        report = validate_robot(path)
        if report.config is None or not report.ok:
            return WorkspaceItem("robot", relative, name, problem=_first_error(report))
        drive = report.config.drivetrain
        motors = sum(len(g.motors) for g in drive.gearing.values())
        detail = f"{drive.type}, {motors} drive motor{'s' if motors != 1 else ''}"
        return WorkspaceItem("robot", relative, name, detail)

    def _field(self, path: Path, relative: str, name: str) -> WorkspaceItem:
        from vexsim.config.loader import validate_field

        report = validate_field(path)
        if report.config is None or not report.ok:
            return WorkspaceItem("field", relative, name, problem=_first_error(report))
        width, height = report.config.size_in
        count = len(report.config.elements)
        detail = f"{width:g} x {height:g} in"
        if count:
            detail += f", {count} element{'s' if count != 1 else ''}"
        return WorkspaceItem("field", relative, name, detail)


def _robot_log_detail(lines: list[str]) -> str:
    """What a format-2 robot log is, by its opening "# key: value" lines: a calibration
    program's test, or a routine's log."""
    info = {}
    for line in lines:
        if not line.startswith("#"):
            break
        key, _, value = line[1:].partition(":")
        info[key.strip()] = value.strip()
    if info.get("program") == "vexsim calibration" and info.get("test"):
        test = info["test"].replace("_", " ").replace("imu", "IMU")
        detail = f"calibration log: {test}"
        return detail + (f", run {info['run']}" if info.get("run") else "")
    return f"robot log: {info['name']}" if info.get("name") else "robot log"


def _first_error(report) -> str:
    errors = report.errors or report.issues
    if not errors:
        return "invalid config"
    issue = errors[0]
    more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
    return f"{issue.location or '(document)'}: {issue.message}{more}"


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return MAX_CAPTURE + 1


def _program_functions(text: str) -> list[str]:
    """The robot program's functions a Python file defines (initialize, autonomous, opcontrol),
    sorted; none if it isn't a program. By what it defines, not what its text holds: a test
    with a program in a string isn't one. A file that doesn't parse (one being typed) goes by
    its text, so it stays listed, and says what's wrong when it's run."""
    found = sorted(set(_PROGRAM_FUNCTION.findall(text)))
    if not found:
        return []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return found
    defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return [name for name in found if name in defined]


def _read(path: Path, limit: int = MAX_READ) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return None

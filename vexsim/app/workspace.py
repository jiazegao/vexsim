"""What's in a folder: robots, fields, scenarios, Python programs, PROS projects, inputs,
telemetry logs, robot logs and MCL logs.

The UI works on one folder, its workspace. ``Workspace.scan`` finds what vexsim can use
in it by reading the files, never running them, and ``Workspace.path`` turns the paths the
UI sends back into files, refusing anything outside the folder.
"""

from __future__ import annotations

import os
import re
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
    "robotlog",
    "mcllog",
    "invalid",
)
SKIP_DIRS = {"node_modules", "__pycache__", "build", "dist", "bin", "venv", "env", "site-packages"}
MAX_DEPTH = 8
MAX_FILES = 20_000
MAX_READ = 512 * 1024  # bytes read to classify a file

_PROGRAM_FUNCTION = re.compile(r"^def (initialize|autonomous|opcontrol)\b", re.MULTILINE)
_TELEMETRY_HEADER = "time_s,phase,x_in,y_in,heading_deg"
_ROBOT_LOG_HEADER = "time_ms,battery_mv"  # vexsim.calibration.log
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


class Workspace:
    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).resolve()

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

    def scan(self) -> list[WorkspaceItem]:
        """Everything vexsim can use in the workspace, grouped by kind, then by path."""
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
            dirs[:] = sorted(
                d
                for d in dirs
                if not d.startswith(".") and d not in SKIP_DIRS and depth < MAX_DEPTH
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

    def _classify(self, path: Path) -> WorkspaceItem | None:
        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            return self._config(path)
        if suffix == ".py":
            text = _read(path)
            functions = sorted(set(_PROGRAM_FUNCTION.findall(text or "")))
            if functions:
                return WorkspaceItem(
                    "program", self.relative(path), path.name, "Python: " + ", ".join(functions)
                )
            return None
        if suffix == ".csv":
            text = _read(path, 4096) or ""
            header = text.splitlines()[0] if text else ""
            if header.startswith(_TELEMETRY_HEADER):
                return WorkspaceItem("log", self.relative(path), path.name, "telemetry log")
            if header.lstrip("\ufeff").startswith(_ROBOT_LOG_HEADER):
                return WorkspaceItem("robotlog", self.relative(path), path.name, "robot log")
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


def _read(path: Path, limit: int = MAX_READ) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return None

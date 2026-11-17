"""The files a run is made from, and whether they've changed since it started.

A run reads its code and configs once, when it starts: the robot and field are loaded, a
Python program is imported, a PROS project is built. ``RunFiles`` lists those files and
``stamp`` says what they are now (each one's size and time), so the app can tell a run whose
files are as they were (*Restart* starts it again at once, in its own worker) from one whose
code was edited since (it's checked, built and started afresh), and can say "code changed"
without reading a byte of them.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# what a PROS project's build reads, besides project.pros (vexsim.bridge.build)
PROJECT_FOLDERS = ("src", "include", "static", "static.lib")

# a file's time (ns) and size; GONE for one that isn't there
Stamp = dict[str, tuple[int, int]]
GONE = (-1, -1)


@dataclass
class RunFiles:
    """What a run reads: ``files`` once each, and a PROS ``project``'s sources, headers and
    assets, whichever there are when it's built (a new file is a change too)."""

    files: list[Path] = field(default_factory=list)
    project: Path | None = None

    def add(self, paths) -> list[Path]:
        """More files (a Python program's imports, known once it's loaded); the new ones."""
        have = set(self.files)
        new = [p for p in map(Path, paths) if p not in have]
        self.files += new
        return new

    def stamp(self) -> Stamp:
        """Each file's time and size, as they are now."""
        found: Stamp = {str(path): _of(path) for path in self.files}
        if self.project is not None:
            from vexsim.bridge.build import SDK_INCLUDES

            found[str(self.project / "project.pros")] = _of(self.project / "project.pros")
            for top in PROJECT_FOLDERS:
                # the SDK's headers aren't the team's: the build replaces them with vexsim's
                _tree(self.project / top, SDK_INCLUDES if top == "include" else (), found)
        return found


def run_files(prepared) -> RunFiles:
    """The files of a checked run (``vexsim.app.runspec.Prepared``)."""
    spec = prepared.spec
    follow = spec.follow.log if spec.follow else None
    named = [spec.robot, spec.field, spec.route, spec.input, follow]
    files = [Path(path) for path in named if path]
    if prepared.program_file is not None:
        files.append(Path(prepared.program_file))
    project = None if prepared.project is None else Path(prepared.project).resolve()
    return RunFiles(files, project)


def changed(before: Stamp, now: Stamp) -> list[str]:
    """The files that differ between two stamps (changed, new or gone), in order."""
    return sorted(path for path in before.keys() | now.keys() if before.get(path) != now.get(path))


def imported_from(base: str | os.PathLike[str], before: set[str]) -> list[str]:
    """The Python files under ``base`` imported since ``before`` (the names sys.modules
    had then): a program's own modules, not vexsim's or an installed package's."""
    import vexsim

    root = Path(base).resolve()
    ours = Path(vexsim.__file__).resolve().parent
    installed = {Path(p).resolve() for p in (sys.prefix, sys.base_prefix, sys.exec_prefix)}
    found = []
    for name, module in list(sys.modules.items()):
        file = getattr(module, "__file__", None)
        if name in before or not file:
            continue
        path = Path(file).resolve()
        if root not in path.parents or ours in path.parents:
            continue
        if any(prefix in path.parents for prefix in installed) or "site-packages" in path.parts:
            continue
        found.append(str(path))
    return sorted(found)


def _of(path: Path) -> tuple[int, int]:
    try:
        st = path.stat()
    except OSError:
        return GONE
    return (st.st_mtime_ns, st.st_size)


def _tree(root: Path, skip, found: Stamp) -> None:
    """Every file under ``root``, but for what's named ``skip`` at its top."""
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for entry in entries:
        if entry.name in skip:
            continue
        try:
            if entry.is_dir():
                _tree(Path(entry.path), (), found)
            else:
                st = entry.stat()
                found[entry.path] = (st.st_mtime_ns, st.st_size)
        except OSError:
            found[entry.path] = GONE

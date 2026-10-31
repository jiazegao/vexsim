"""vexsim's logger (bridge/cpp/logger): the two files a PROS project needs to log what its
robot's devices read, for vexsim. They're the same in every project; ``vexsim logger add``
copies them in, and the calibration routine comes with them. calibration/log.py reads the
logs they write."""

from __future__ import annotations

from pathlib import Path

LOGGER_DIR = Path(__file__).parent / "cpp" / "logger"
# where each file goes in a project, and where vexsim keeps it
FILES = (
    ("include/vexsim_log.hpp", LOGGER_DIR / "include" / "vexsim_log.hpp"),
    ("src/vexsim_log.cpp", LOGGER_DIR / "src" / "vexsim_log.cpp"),
)


def logger_files(project: str | Path) -> list[tuple[Path, str]]:
    """Where the logger's files go in ``project``, and what they hold."""
    return [(Path(project) / rel, source.read_text(encoding="utf-8")) for rel, source in FILES]


def file_state(path: Path, text: str) -> str:
    """Whether ``path`` is missing ("new"), holds ``text`` ("same") or something else."""
    if not path.is_file():
        return "new"
    return "same" if path.read_text(encoding="utf-8", errors="replace") == text else "different"


def add_logger(project: str | Path) -> list[tuple[Path, str]]:
    """Copy the logger into ``project``; each file, and whether it was "new", "updated" or
    already the "same"."""
    out = []
    for path, text in logger_files(project):
        state = file_state(path, text)
        if state != "same":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        out.append((path, "updated" if state == "different" else state))
    return out

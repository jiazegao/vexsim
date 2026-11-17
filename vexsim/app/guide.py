"""vexsim's own documents, for the app's Guide page: the README and what's in ``docs/``.

They're read from where they sit beside the package (a clone, which is how teams install
vexsim). A copy installed without them has none to show, and the page links to the
repository's instead (``REPOSITORY``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPOSITORY = "https://github.com/jiazegao/vexsim"
PICTURES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

# The documents in the order a student meets them: (id, file, what it's for)
_DOCUMENTS: tuple[tuple[str, str, str], ...] = (
    ("readme", "README.md", "The user guide: installing, configs, running, the app, every command"),
    ("calibration_guide", "docs/calibration_guide.md", "Step by step, for students"),
    ("programming", "docs/programming.md", "Python robot programs"),
    ("cpp", "docs/cpp.md", "Running your PROS 4 project"),
    ("conventions", "docs/conventions.md", "Units, frames and the config files"),
    ("models", "docs/models.md", "What is simulated, and how"),
    ("calibration", "docs/calibration.md", "Calibration, in full: logs, fits, reports"),
    ("benchmarking", "docs/benchmarking.md", "Benchmarks of localizers and controllers"),
    ("porting_1239e", "docs/porting_1239e.md", "How a team's project was brought in"),
    ("1239e_real_vs_sim", "docs/1239e_real_vs_sim.md", "A real robot's logs beside the simulator"),
)


@dataclass(frozen=True)
class Document:
    id: str
    path: str  # from the repository's top, with /
    title: str  # its first heading
    about: str


def root() -> Path | None:
    """Where the documents are: the folder that holds the vexsim package, if the README and
    docs/ are there with it (a clone); None for a copy installed without them."""
    import vexsim

    folder = Path(vexsim.__file__).resolve().parent.parent
    if (folder / "README.md").is_file() and (folder / "docs").is_dir():
        return folder
    return None


def documents(folder: Path | None = None) -> list[Document]:
    """The documents there are to read, in order (none if they aren't installed)."""
    folder = root() if folder is None else folder
    if folder is None:
        return []
    found = []
    for name, path, about in _DOCUMENTS:
        file = folder / path
        if file.is_file():
            found.append(Document(name, path, _title(file) or Path(path).stem, about))
    return found


def listed() -> list[tuple[str, str, str]]:
    """Every document vexsim has (id, path, what it's for), installed here or not."""
    return list(_DOCUMENTS)


def read(name: str, folder: Path | None = None) -> tuple[Document, str]:
    """A document and its text; raises KeyError if there's none by that id."""
    folder = root() if folder is None else folder
    for document in documents(folder):
        if document.id == name:
            return document, (folder / document.path).read_text(encoding="utf-8")
    raise KeyError(name)


def picture(path: str, folder: Path | None = None) -> Path:
    """A picture a document shows (a path from the repository's top); raises ValueError for
    anything that isn't a picture in docs/."""
    folder = root() if folder is None else folder
    if folder is None:
        raise ValueError("vexsim's documents aren't installed here")
    docs = (folder / "docs").resolve()
    file = (folder / path).resolve()
    if docs not in file.parents or file.suffix.lower() not in PICTURES or not file.is_file():
        raise ValueError(f"{path} isn't a picture in vexsim's documents")
    return file


def _title(file: Path) -> str:
    """A document's first heading (``# ...``), without its marks."""
    try:
        with file.open(encoding="utf-8") as lines:
            for line in lines:
                if line.startswith("# "):
                    return line[2:].strip().replace("`", "")
    except OSError:
        pass
    return ""

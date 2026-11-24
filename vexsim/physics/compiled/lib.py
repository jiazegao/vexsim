"""The compiled step's library: found in the build cache or built there, loaded, and checked
against the Python step once on each computer.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import platform
import shutil
import struct
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vexsim.physics.compiled.layout import HEADER, SOURCE, header, layout_id
from vexsim.physics.compiled.modes import ENV, StepMismatch, StepUnavailable, mode

LIB_NAME = {"win32": "vexsim_step.dll", "darwin": "libvexsim_step.dylib"}.get(
    sys.platform, "libvexsim_step.so"
)
FLAGS = ["-std=c11", "-O2", "-ffp-contract=off"]


@dataclass
class Library:
    path: Path
    step: Callable[[int, int, float], int]  # (the block's address, the arrays', dt)
    compiler: str
    built_s: float | None = None  # how long the build took; None: it was in the cache
    worst: float | None = None  # its check's largest difference, when the check ran just now
    agreement: float | None = None  # the same, whenever the check ran (it's kept beside it)


_lock = threading.Lock()
_found: Library | None = None
_looked = False
_why = ""


def library() -> Library | None:
    """The compiled step, built if it has to be; None where there's none (``reason`` says why).
    Looked for once in a process."""
    global _found, _looked, _why
    with _lock:
        if not _looked:
            try:
                _found, _why = _load(), ""
            except StepUnavailable as exc:
                _found, _why = None, str(exc)
            except Exception as exc:  # whatever went wrong, the Python step still steps
                _found, _why = None, f"{type(exc).__name__}: {exc}"
            _looked = True
        return _found


def reason() -> str:
    """Why there's no compiled step here ("" if there is one, or nobody has looked)."""
    return _why


def describe() -> tuple[bool, str]:
    """Whether robots take the compiled step here, and a line that says so (``vexsim doctor``)."""
    chosen = mode()
    if chosen == "python":
        return False, f"the Python step ({ENV}=python)"
    lib = library()
    if lib is None:
        return False, f"the Python step (slower): {reason()}"
    text = "the compiled step, "
    text += "from the build cache" if lib.built_s is None else f"built in {lib.built_s:.1f} s"
    if lib.agreement is not None:
        text += f": on its check it agreed with the Python step to {lib.agreement:.0e}"
    if chosen == "check":
        text += f" ({ENV}=check: both run, every step, and are compared)"
    return True, text


def forget() -> None:
    """Look again next time (the tests', after they change what there is to find)."""
    global _found, _looked, _why
    with _lock:
        _found, _looked, _why = None, False, ""


def _compiler() -> str:
    """The C++ compiler ``vexsim build`` would use, found without running it."""
    from vexsim.bridge import build

    explicit = os.environ.get("VEXSIM_CXX")
    candidates = [explicit, "g++"]
    if sys.platform == "win32":
        candidates += build._msys2_candidates()
    for candidate in candidates:
        if not candidate:
            continue
        path = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if path:
            return path
        if candidate == explicit:
            raise StepUnavailable(f"compiler not found: {candidate}")
    raise StepUnavailable("no C++ compiler (g++) found")


def _key(compiler: str) -> str:
    """What a built library depends on: the source, the tables, the flags, the compiler (as
    its file is, so nothing has to be run to tell) and the machine."""
    stat = Path(compiler).stat()
    parts = (
        SOURCE.read_bytes(), header().encode(), " ".join(FLAGS).encode(), compiler.encode(),
        f"{stat.st_size} {stat.st_mtime_ns}".encode(),
        f"{sys.platform} {platform.machine()} {struct.calcsize('P')}".encode(),
    )  # fmt: skip
    h = hashlib.blake2b(digest_size=8)
    for part in parts:
        h.update(part)
        h.update(b"\0")
    return h.hexdigest()


def _command(compiler: str, out: Path) -> list[str]:
    """Build step.c as C, with the gcc beside a g++ (else the compiler itself, told it's C)."""
    name = Path(compiler).name
    gcc = Path(compiler).with_name(name.replace("g++", "gcc")) if "g++" in name else None
    driver = [str(gcc)] if gcc is not None and gcc.is_file() else [compiler, "-x", "c"]
    cmd = [*driver, *FLAGS, "-shared", f"-I{HEADER.parent}", str(SOURCE), "-o", str(out)]
    if sys.platform == "win32":
        cmd.append("-static")  # nothing of MinGW's needed beside it
    else:
        cmd += ["-fPIC", "-lm"]
    return cmd


def _load() -> Library:
    from vexsim.bridge import build

    if HEADER.read_text(encoding="utf-8") != header():
        raise StepUnavailable(
            f"{HEADER.name} isn't what layout.py's tables say (python -m vexsim.physics.compiled)"
        )
    compiler = _compiler()
    folder = build.cache_root() / f"step-{_key(compiler)}"
    path, failed, checked = folder / LIB_NAME, folder / "failed.txt", folder / "checked.txt"
    if failed.is_file():  # it didn't build, or its check failed: not tried again as it is
        raise StepUnavailable(failed.read_text(encoding="utf-8", errors="replace").strip())

    def fail(why: str) -> StepUnavailable:
        why += f"\n(noted in {failed}, so it isn't tried again: delete that to try)"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            failed.write_text(why, encoding="utf-8")
        except OSError:
            pass
        return StepUnavailable(why)

    built_s = None
    if not path.is_file():
        start = time.perf_counter()
        temporary = folder / f"{os.getpid()}-{threading.get_ident()}-{LIB_NAME}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            result = build._run(_command(compiler, temporary))
        except OSError as exc:
            raise StepUnavailable(f"the compiled step can't be built in {folder}: {exc}") from exc
        if result.returncode != 0 or not temporary.is_file():
            output = (result.stdout + result.stderr).strip() or f"exit code {result.returncode}"
            raise fail(f"the compiled step didn't build with {compiler}:\n{output}")
        try:
            os.replace(temporary, path)
        except OSError:  # another process put its own there first (and has it open, on Windows)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            if not path.is_file():
                raise
        built_s = time.perf_counter() - start

    try:
        dll = ctypes.PyDLL(str(path))
        dll.vexsim_layout.restype = ctypes.c_uint
        dll.vexsim_step.restype = ctypes.c_int
        dll.vexsim_step.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_double]
        built_for = dll.vexsim_layout()
    except (OSError, AttributeError) as exc:
        raise StepUnavailable(f"the compiled step ({path}) doesn't load: {exc}") from exc
    if built_for != layout_id():
        raise StepUnavailable(f"the compiled step ({path}) was built for another layout")
    found = Library(path, dll.vexsim_step, compiler, built_s)
    if checked.is_file():
        try:
            found.agreement = float(checked.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        return found
    from vexsim.physics.compiled.check import self_check  # (it steps a robot)

    try:
        found.worst = found.agreement = self_check(found)
    except StepMismatch as exc:
        raise fail(f"the compiled step ({path}) failed its check: {exc}") from exc
    try:
        checked.write_text(f"{found.worst!r}\n", encoding="utf-8")
    except OSError:
        pass
    return found

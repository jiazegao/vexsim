"""Compile a PROS 4 project against the vexsim shim (``vexsim build``).

The project is never modified. Its ``src/`` and ``include/`` are copied into a
staging directory without the PROS SDK headers (``include/api.h``,
``include/pros/``, ``include/liblvgl/``, ``include/display/``), so every
``#include "api.h"`` finds the shim instead. A quoted include searches the
including file's own directory first, so leaving the SDK in place would win
over any ``-I`` path. Objects are rebuilt only when a source, a header it
includes, or the compiler flags change.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from vexsim.bridge import routines
from vexsim.bridge.routines import Routine

CPP_DIR = Path(__file__).parent / "cpp"
SHIM_INCLUDE = CPP_DIR / "include"
RUNTIME_DIR = CPP_DIR / "runtime"

SDK_INCLUDES = {"api.h", "pros", "liblvgl", "display"}  # replaced by the shim
COMPETITION = ("initialize", "competition_initialize", "disabled", "autonomous", "opcontrol")
SOURCE_SUFFIXES = {".c", ".cpp", ".cc", ".cxx", ".c++"}
DEFINES = ["-DVEXSIM=1", "-D_PROS_KERNEL_SUPPRESS_LLEMU_WARNING"]
MIN_GCC = 11
EXE_NAME = "robot_host.exe" if sys.platform == "win32" else "robot_host"
MSYS2_FOLDERS = ("msys64", "msys2")  # searched on every drive, in ucrt64\bin
# Toolchain programs and the robot host run with no console window of their own: a server
# started without a console (from a shortcut, or VS Code) would show one for each on Windows
NO_CONSOLE = getattr(subprocess, "CREATE_NO_WINDOW", 0)

INSTALL_HELP_WINDOWS = """\
vexsim compiles robot code with MSYS2's MinGW-w64 g++ (UCRT64). To install it:
  1. Install MSYS2 from https://www.msys2.org (default folder C:\\msys64).
  2. In the "MSYS2 UCRT64" terminal run:  pacman -S --needed mingw-w64-ucrt-x86_64-gcc
  3. vexsim finds it in C:\\msys64 or D:\\msys2 (any drive); elsewhere, add its ucrt64\\bin
     folder to your PATH or set VEXSIM_CXX to the full path of g++.exe.
Then run `vexsim doctor` again."""

INSTALL_HELP_UNIX = """\
vexsim compiles robot code with g++ 11 or newer. Install it with your package manager,
for example `sudo apt install g++` (Debian/Ubuntu) or `xcode-select --install` plus
`brew install gcc` (macOS, then set VEXSIM_CXX=g++-14 or similar)."""


class BuildError(Exception):
    """The project could not be built; the message says why and what to do."""


@dataclass(frozen=True)
class Toolchain:
    cxx: str
    version: tuple[int, ...]
    target: str
    thread_model: str

    @property
    def version_text(self) -> str:
        return ".".join(map(str, self.version))

    @property
    def windows(self) -> bool:
        return "mingw" in self.target or "windows" in self.target

    def problems(self) -> list[str]:
        found = []
        if self.version[0] < MIN_GCC:
            found.append(f"g++ {self.version_text} is too old: vexsim needs g++ {MIN_GCC} or newer")
        if sys.platform == "win32" and not self.windows:
            found.append(f"{self.cxx} targets {self.target}; on Windows use MSYS2's MinGW-w64 g++")
        if self.thread_model and self.thread_model not in ("posix", "mcf"):
            found.append(
                f"g++ uses the {self.thread_model!r} thread model; vexsim needs std::thread "
                "(MSYS2 UCRT64 g++ provides it)"
            )
        return found


def install_help() -> str:
    return INSTALL_HELP_WINDOWS if sys.platform == "win32" else INSTALL_HELP_UNIX


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a toolchain program with its own folder first on PATH.

    g++ starts helper programs (cc1plus, as, ld) whose DLLs live next to g++.exe
    in MSYS2. Without that folder on PATH they fail on Windows without a word.
    """
    env = os.environ.copy()
    if Path(cmd[0]).is_absolute():
        env["PATH"] = str(Path(cmd[0]).parent) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        errors="replace",
        env=env,
        creationflags=NO_CONSOLE,
        **kwargs,
    )


def _msys2_candidates() -> list[str]:
    """MSYS2 UCRT64 g++ in the usual install folders, on any drive."""
    found = []
    for drive in "CDEFGH":
        for folder in MSYS2_FOLDERS:
            gxx = Path(f"{drive}:\\") / folder / "ucrt64" / "bin" / "g++.exe"
            if gxx.is_file():
                found.append(str(gxx))
    return found


def find_toolchain(cxx: str | None = None) -> Toolchain:
    """Locate g++: ``cxx``, then $VEXSIM_CXX, then PATH, then MSYS2's usual folders."""
    candidates = [cxx, os.environ.get("VEXSIM_CXX"), shutil.which("g++")]
    if sys.platform == "win32":
        candidates += _msys2_candidates()
    for candidate in candidates:
        if not candidate:
            continue
        path = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if path is None:
            if candidate in (cxx, os.environ.get("VEXSIM_CXX")):
                raise BuildError(f"compiler not found: {candidate}")
            continue
        version = _run([path, "-dumpfullversion", "-dumpversion"])
        target = _run([path, "-dumpmachine"])
        verbose = _run([path, "-v"])
        if version.returncode != 0:
            raise BuildError(f"{path} doesn't run: {version.stderr.strip()}")
        numbers = tuple(int(n) for n in re.findall(r"\d+", version.stdout.strip())[:3]) or (0,)
        model = re.search(r"Thread model:\s*(\S+)", verbose.stderr + verbose.stdout)
        return Toolchain(path, numbers, target.stdout.strip(), model.group(1) if model else "")
    raise BuildError("no C++ compiler (g++) found.\n" + install_help())


def cache_root() -> Path:
    """Where builds go: $VEXSIM_CACHE_DIR, else %LOCALAPPDATA%\\vexsim\\build (Windows) or
    ~/.cache/vexsim/build."""
    if os.environ.get("VEXSIM_CACHE_DIR"):
        return Path(os.environ["VEXSIM_CACHE_DIR"])
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "vexsim" / "build"
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "vexsim" / "build"


def _digest(*parts: str | bytes) -> str:
    h = hashlib.blake2b(digest_size=8)
    for part in parts:
        h.update(part.encode() if isinstance(part, str) else part)
        h.update(b"\0")
    return h.hexdigest()


@dataclass
class BuildResult:
    executable: Path
    compiled: int  # sources compiled this time
    total: int  # sources in the project
    seconds: float
    linked: bool = True  # False when the executable was already up to date
    kernel: str | None = None  # PROS kernel version from project.pros
    notes: list[str] = field(default_factory=list)
    lemlib: str | None = None  # LemLib version built from source, if the project uses it
    routines: list[str] = field(default_factory=list)  # the ones a run can pick (routines.py)


@dataclass(frozen=True)
class Template:
    """A PROS template applied to the project (kernel, LemLib, ...), from project.pros."""

    version: str | None
    system_files: tuple[str, ...] = ()  # files the template owns; vexsim replaces them


def project_templates(project: Path) -> dict[str, Template]:
    """The templates listed in project.pros (empty if there is none or it can't be read)."""
    path = project / "project.pros"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    state = data.get("py/state", data)
    entries = state.get("templates", {}) if isinstance(state, dict) else {}
    templates = {}
    for name, info in entries.items():
        if not isinstance(info, dict):
            continue
        info = info.get("py/state", info)
        files = tuple(str(f).replace("\\", "/") for f in info.get("system_files") or ())
        templates[name] = Template(info.get("version"), files)
    return templates


def is_pros_project(path: Path) -> bool:
    path = Path(path)
    return path.is_dir() and ((path / "project.pros").is_file() or (path / "src").is_dir())


def _stage(project: Path, stage: Path, exclude: set[str]) -> list[Path]:
    """Mirror src/ and include/ into ``stage``, without the SDK and template files
    (``exclude``: project-relative paths or folders, with /); returns staged sources."""
    wanted: dict[Path, Path] = {}
    for top in ("src", "include"):
        root = project / top
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            rel = path.relative_to(project)
            if top == "include" and rel.parts[1] in SDK_INCLUDES:
                continue
            posix = rel.as_posix()
            if posix in exclude or any(posix.startswith(e + "/") for e in exclude):
                continue
            if path.is_file():
                wanted[rel] = path
    for rel, path in wanted.items():
        target = stage / rel
        st = path.stat()
        if target.exists():
            ts = target.stat()
            if ts.st_size == st.st_size and int(ts.st_mtime) == int(st.st_mtime):
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    for top in ("src", "include"):
        root = stage / top
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*"), reverse=True):
            rel = path.relative_to(stage)
            if path.is_file() and rel not in wanted:
                path.unlink()
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    return sorted(
        stage / rel for rel in wanted if rel.parts[0] == "src" and rel.suffix in SOURCE_SUFFIXES
    )


def _deps(dep_file: Path) -> list[Path] | None:
    """Prerequisites listed in a gcc -MMD file, or None if it can't be read."""
    try:
        text = dep_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    text = text.replace("\\\r\n", " ").replace("\\\n", " ")
    match = re.search(r":\s", text)  # end of the target (a drive letter's colon has no space after)
    if match is None:
        return None
    rest = text[match.end() :].split("\n", 1)[0]
    parts = re.split(r"(?<!\\)\s+", rest.strip())
    # gcc escapes spaces and '#' with a backslash and '$' as '$$' (make syntax)
    return [Path(p.replace("\\ ", " ").replace("\\#", "#").replace("$$", "$")) for p in parts if p]


def _stale(obj: Path, dep_file: Path, stamp: Path, flags_key: str) -> bool:
    if not obj.exists() or not stamp.exists() or stamp.read_text() != flags_key:
        return True
    deps = _deps(dep_file)
    if deps is None:
        return True
    built = obj.stat().st_mtime
    for dep in deps:
        try:
            if dep.stat().st_mtime > built:
                return True
        except OSError:
            return True
    return False


def _compile_cmd(
    tc: Toolchain,
    source: Path,
    obj: Path,
    includes: list[Path],
    opt: list[str],
    quote: list[Path] = (),
    first: list[Path] = (),
) -> list[str]:
    """``quote``: folders searched for #include "..." only. PROS's makefile adds
    include/<dir> for every src/<dir>/ source, so "pid.hpp" works in src/lemlib/.
    ``first``: headers included before the source (the routine switch's, see routines.py)."""
    lang = ["-x", "c", "-std=gnu11"] if source.suffix == ".c" else ["-std=gnu++20"]
    return [
        tc.cxx,
        *lang,
        *opt,
        "-pthread",
        *DEFINES,
        "-include",
        str(SHIM_INCLUDE / "vexsim" / "newlib_compat.h"),
        *[arg for header in first for arg in ("-include", str(header))],
        *[f"-iquote{p}" for p in quote],
        *[f"-I{p}" for p in includes],
        "-MMD",
        "-MF",
        str(obj.with_suffix(".d")),
        "-c",
        str(source),
        "-o",
        str(obj),
    ]


def _silent_failure(tc: Toolchain, source: Path, code: int) -> str:
    text = f"{source}: g++ exited with code {code} without printing an error."
    if sys.platform == "win32":
        text += (
            f" On Windows this usually means one of g++'s helper programs couldn't start: "
            f"check that {Path(tc.cxx).parent} holds a complete MSYS2 UCRT64 gcc install "
            "(pacman -S --needed mingw-w64-ucrt-x86_64-gcc)."
        )
    return text


def _compile_all(
    tc: Toolchain,
    jobs: list[tuple[Path, Path, list[str]]],
    workers: int,
    rewrite: Callable[[str], str],
) -> int:
    """Compile (source, obj, cmd) jobs in parallel; raise BuildError with all errors."""
    if not jobs:
        return 0

    def one(job):
        source, obj, cmd = job
        obj.parent.mkdir(parents=True, exist_ok=True)
        result = _run(cmd)
        return source, obj, result

    failures = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for source, obj, result in pool.map(one, jobs):
            output = rewrite((result.stdout + result.stderr).strip())
            if result.returncode != 0:
                obj.unlink(missing_ok=True)
                failures.append(output or _silent_failure(tc, source, result.returncode))
            elif output:
                print(output, file=sys.stderr)
    if failures:
        raise BuildError("compile errors:\n" + "\n".join(failures))
    return len(jobs)


def _tool(tc: Toolchain, name: str) -> str:
    """A binutils program (ar, nm) that belongs to the compiler."""
    prog = _run([tc.cxx, "-print-prog-name=" + name]).stdout.strip() or name
    beside = shutil.which(str(Path(tc.cxx).parent / Path(prog).name))
    return beside or shutil.which(prog) or prog


def _cpp_linkage_notes(tc: Toolchain, objs: list[Path], stage: Path, project: Path) -> list[str]:
    """Competition functions compiled with C++ linkage are never called (as on the robot)."""
    mangled = {f"_Z{len(n)}{n}v": n for n in COMPETITION}
    notes = []
    for obj in objs:
        result = _run([_tool(tc, "nm"), "--defined-only", str(obj)])
        for line in result.stdout.splitlines():
            name = mangled.get(line.split()[-1]) if line.strip() else None
            if name:
                source = project / obj.relative_to(stage.parent / "obj").with_suffix("")
                notes.append(
                    f"{source} defines {name}() with C++ linkage, so "
                    f'it is never called. Declare it extern "C" (PROS\'s main.h does; is '
                    "main.h included?)"
                )
    return notes


def build_runtime(tc: Toolchain, *, workers: int | None = None) -> tuple[list[Path], Path]:
    """Compile the shim runtime once per compiler and vexsim version (shared by all projects)."""
    core = sorted(RUNTIME_DIR.glob("*.cpp"))
    defaults = sorted((RUNTIME_DIR / "defaults").glob("*.cpp"))
    headers = sorted(RUNTIME_DIR.glob("*.hpp")) + sorted(SHIM_INCLUDE.rglob("*.h*"))
    opt = ["-O2"]
    key = _digest(
        tc.cxx,
        tc.version_text,
        tc.target,
        *opt,
        *[p.read_bytes() for p in core + defaults + headers],
    )
    out = cache_root() / f"runtime-{key}"
    lib = out / "libvexsim_defaults.a"
    objs = [out / f"{p.stem}.o" for p in core]
    if lib.exists() and all(o.exists() for o in objs):
        return objs, lib
    out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for src in core + defaults:
        obj = out / ("defaults" if src in defaults else "") / f"{src.stem}.o"
        jobs.append((src, obj, _compile_cmd(tc, src, obj, [SHIM_INCLUDE, RUNTIME_DIR], opt)))
    _compile_all(tc, jobs, workers or os.cpu_count() or 2, lambda s: s)
    _archive(tc, lib, [out / "defaults" / f"{p.stem}.o" for p in defaults])
    return objs, lib


def _archive(tc: Toolchain, lib: Path, objs: list[Path]) -> None:
    """Create the static library ``lib`` from ``objs`` (replaced atomically)."""
    tmp = lib.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    result = _run([_tool(tc, "ar"), "rcs", str(tmp), *map(str, objs)])
    if result.returncode != 0:
        raise BuildError(f"creating {lib.name} failed: {result.stderr.strip()}")
    os.replace(tmp, lib)


def _write_if_changed(path: Path, text: str) -> None:
    """Keep the file's time stamp when nothing changed, so it isn't recompiled."""
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def asset_symbol(rel: str) -> str:
    """The name objcopy gives a static/ file's data: static/example.txt -> static_example_txt."""
    return re.sub(r"[^A-Za-z0-9]", "_", rel)


def _generate_assets(project: Path, path: Path) -> int:
    """Embed every file in static/ and static.lib/ for LemLib's ASSET(name); returns the count."""
    files = sorted(
        f for top in ("static", "static.lib") if (project / top).is_dir()
        for f in (project / top).rglob("*") if f.is_file()
    )  # fmt: skip
    lines = [
        "// Generated by vexsim build: the project's static/ files, for ASSET(name).",
        "#include <cstddef>",
        "#include <cstdint>",
        'extern "C" {',
    ]
    for f in files:
        name = asset_symbol(f.relative_to(project).as_posix())
        data = f.read_bytes()
        padded = data + b"\0"  # NUL-terminated for text parsers; the size excludes it
        lines.append(f"alignas(16) std::uint8_t _binary_{name}_start[] = {{")
        for i in range(0, len(padded), 16):
            lines.append("    " + "".join(f"0x{b:02x}," for b in padded[i : i + 16]))
        lines.append("};")
        lines.append(f"extern const std::size_t _vexsim_asset_size_{name} = {len(data)};")
    lines.append("}")
    _write_if_changed(path, "\n".join(lines) + "\n")
    return len(files)


LEMLIB_POSE_SOURCE = """\
// Generated by vexsim build: shows LemLib's odometry pose in the simulator.
#include "lemlib/api.hpp"
#include "lemlib/chassis/odom.hpp"

extern pros::Task* trackingTask;  // LemLib's odometry task (lemlib/chassis/odom.cpp)
extern "C" void vexsim_set_pose_source(int (*source)(double*, double*, double*));

namespace {
int lemlib_pose(double* x, double* y, double* theta) {
	if (trackingTask == nullptr) return 0;  // odometry hasn't started (chassis.calibrate())
	lemlib::Pose pose = lemlib::getPose();
	*x = pose.x, *y = pose.y, *theta = pose.theta;
	return 1;
}
struct Register {
	Register() { vexsim_set_pose_source(lemlib_pose); }
} register_lemlib_pose;
}  // namespace
"""


def build_project(
    project: str | Path,
    *,
    toolchain: Toolchain | None = None,
    workers: int | None = None,
    debug: bool = False,
    log: Callable[[str], None] | None = None,
) -> BuildResult:
    """Build (incrementally) a PROS 4 project; returns the robot host executable."""
    start = time.perf_counter()
    project = Path(project).resolve()
    if not is_pros_project(project):
        raise BuildError(f"{project} is not a PROS project (no src/ folder or project.pros)")
    tc = toolchain or find_toolchain()
    problems = tc.problems()
    if problems:
        raise BuildError("\n".join(problems) + "\n" + install_help())
    from vexsim.bridge import lemlib

    templates = project_templates(project)
    kernel = templates["kernel"].version if "kernel" in templates else None
    notes = []
    if kernel and not kernel.startswith("4."):
        notes.append(f"project.pros lists PROS kernel {kernel}; vexsim follows the PROS 4 API")
    lemlib_version = lemlib.find_version(project, templates)
    exclude = {f for t in templates.values() for f in t.system_files if f.startswith("include/")}
    if lemlib_version:
        edited = lemlib.edited_headers(project, lemlib_version, log)
        # As on the robot, a project with edited LemLib headers compiles against its own
        # copies, while the library is LemLib's own build (so edits must keep class layouts).
        # Otherwise the headers come from the matching LemLib source.
        for top in ("include/lemlib", "include/fmt"):
            if any(f.startswith(top + "/") for f in edited):
                exclude = {f for f in exclude if not f.startswith(top + "/")}
            else:
                exclude.add(top)
        if edited:
            shown = ", ".join(edited[:3]) + (
                f" and {len(edited) - 3} more" if len(edited) > 3 else ""
            )
            notes.append(
                f"the project's LemLib headers differ from LemLib {lemlib_version}'s ({shown}); "
                "its code compiles against its own copies, as on the robot"
            )
        if not lemlib.tested(lemlib_version):
            notes.append(f"LemLib {lemlib_version} is untested in vexsim (tested: 0.5.x)")

    out = cache_root() / f"{project.name}-{_digest(str(project))}"
    stage = out / "stage"
    sources = _stage(project, stage, exclude)
    if not sources:
        raise BuildError(f"{project / 'src'} has no C or C++ sources")
    opt = ["-O0", "-g"] if debug else ["-O2"]
    includes = [stage / "include", SHIM_INCLUDE]
    libraries = []
    if lemlib_version:
        lemlib_include, lemlib_lib = lemlib.build_library(
            tc, lemlib_version, workers=workers, log=log
        )
        includes.append(lemlib_include)
        libraries.append(lemlib_lib)
    flags_key = _digest(tc.cxx, tc.version_text, *opt, *map(str, includes), *DEFINES)

    generated = out / "generated"
    _generate_assets(project, generated / "vexsim_assets.cpp")
    sources.append(generated / "vexsim_assets.cpp")
    if lemlib_version:
        _write_if_changed(generated / "vexsim_lemlib_pose.cpp", LEMLIB_POSE_SOURCE)
        sources.append(generated / "vexsim_lemlib_pose.cpp")

    def rewrite(text: str) -> str:
        """Point compiler messages at the project's files, not the staged copies."""
        for form in {str(stage), stage.as_posix()}:
            text = text.replace(form + os.sep, str(project) + os.sep).replace(
                form + "/", f"{project}/"
            )
        return text

    # The routine switch (routines.py): a routine vexsim can't switch is left out of it
    found = routines.find_routines(project)
    switchable = [r for r in found.routines if r.source] if found else []
    for r in found.routines if found else []:
        if r.source is None:
            notes.append(
                f"{r.name}() is declared in {routines.AUTON_HEADER}, but vexsim can't tell "
                "which file defines it, so a run can't pick it"
            )
    user_sources = [s for s in sources if s.is_relative_to(stage)]
    runtime_objs, runtime_lib = build_runtime(tc, workers=workers)
    exe = out / EXE_NAME
    left_out: dict[str, str] = {}  # routine: why, as linking found
    compiled_user = 0
    while True:
        switched = [r for r in switchable if r.name not in left_out]
        first = _routine_files(switched, generated, stage)
        units = sources + ([generated / "vexsim_routines.cpp"] if switched else [])
        jobs, objs = [], []
        for src in units:
            rel = src.relative_to(stage if src.is_relative_to(stage) else out)
            obj = out / "obj" / rel.with_suffix(rel.suffix + ".o")
            objs.append(obj)
            header = first.get(src)
            key = flags_key if header is None else _digest(flags_key, header.read_text())
            quote = [stage / "include" / Path(*rel.parts[1:-1])] if rel.parts[0] == "src" else []
            if _stale(obj, obj.with_suffix(".d"), obj.with_suffix(".flags"), key):
                cmd = _compile_cmd(tc, src, obj, includes, opt, quote, [header] if header else [])
                jobs.append((src, obj, cmd, key))
        count = sum(src.is_relative_to(stage) for src, *_ in jobs)
        if log and count:
            total = len(user_sources)
            log(f"compiling {count} of {total} source file(s) with g++ {tc.version_text}")
        parallel = workers or os.cpu_count() or 2
        compiled = _compile_all(tc, [job[:3] for job in jobs], parallel, rewrite)
        for _, obj, _, key in jobs:
            obj.with_suffix(".flags").write_text(key)
        compiled_user += count
        result = BuildResult(
            exe, compiled_user, len(user_sources), 0.0, kernel=kernel, notes=notes,
            lemlib=lemlib_version, routines=[r.name for r in switched],
        )  # fmt: skip
        inputs = objs + libraries + runtime_objs + [runtime_lib]
        if (
            exe.exists()
            and all(p.stat().st_mtime <= exe.stat().st_mtime for p in inputs)
            and not compiled
            and not left_out
        ):
            result.linked = False
            result.seconds = time.perf_counter() - start
            return result
        if not left_out:
            user_objs = [o for o in objs if "generated" not in o.parts]
            notes += _cpp_linkage_notes(tc, user_objs, stage, project)
            for note in notes if log else ():
                log(f"note: {note}")
        failed = _link(tc, exe, inputs, rewrite)
        if failed is None:
            break
        why = _unswitchable(failed, switched)
        if not why:
            raise BuildError("link failed:\n" + failed)
        for name, reason in why.items():
            left_out[name] = reason
            note = f"{name}() {reason}, so a run can't pick it"
            notes.append(note)
            if log:
                log(f"note: {note}")
    result.executable = _install(exe)
    result.seconds = time.perf_counter() - start
    return result


def _link(
    tc: Toolchain, exe: Path, inputs: list[Path], rewrite: Callable[[str], str]
) -> str | None:
    """Link the robot host into a temporary file beside ``exe``; None if it linked, else
    what went wrong."""
    link = [tc.cxx, "-o", str(_linked(exe)), *map(str, inputs), "-pthread"]
    if tc.windows:
        link.append("-static")  # no MinGW DLLs needed at run time
    result = _run(link)
    if result.returncode == 0:
        return None
    message = rewrite((result.stdout + result.stderr).strip())
    if "_binary_static_" in message:
        message += (
            "\n\nASSET(name) needs a file static/<name with . for _> in the project, "
            "for example ASSET(example_txt) needs static/example.txt."
        )
    return message


def _linked(exe: Path) -> Path:
    return exe.with_name("robot_host.tmp" + (".exe" if sys.platform == "win32" else ""))


def _install(exe: Path) -> Path:
    """Put the linked executable in place; where it went."""
    linked = _linked(exe)
    try:
        os.replace(linked, exe)
    except PermissionError:  # Windows: the old executable is still running (open viewer)
        exe = exe.with_name(f"robot_host-{int(time.time())}.exe")
        os.replace(linked, exe)
    return exe


def _routine_files(switched: list[Routine], generated: Path, stage: Path) -> dict[Path, Path]:
    """Write the routine switch's sources (routines.py) for ``switched``: a header for each
    file that defines some, and the switch itself. Returns {staged source: its header}."""
    by_source: dict[str, list[Routine]] = {}
    for routine in switched:
        by_source.setdefault(routine.source, []).append(routine)
    first = {}
    for rel, defined in by_source.items():
        header = generated / "routines" / f"{rel}.h"
        _write_if_changed(header, routines.rename_header(defined))
        first[stage / rel] = header
    if switched:
        _write_if_changed(generated / "vexsim_routines.cpp", routines.switch_source(switched))
    return first


def _unswitchable(message: str, switched: list[Routine]) -> dict[str, str]:
    """Routines a failed link says the switch can't take: the definition vexsim found isn't
    compiled (the name the switch calls it by is undefined), or another file defines it
    too (two definitions of its own name)."""
    why = {}
    for routine in switched:
        symbol, name = re.escape(routine.symbol), re.escape(routine.name)
        twice = rf"(multiple definition of|duplicate symbol)[^\n]*({symbol}|{name}\(\))"
        if re.search(rf"vexsim_routine_{symbol}\b", message):
            why[routine.name] = "has no definition that vexsim's build compiles"
        elif re.search(twice, message):
            why[routine.name] = "is defined in more than one place"
    return why

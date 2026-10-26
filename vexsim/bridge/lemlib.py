"""LemLib, built from source for the simulator.

PROS installs LemLib as a template whose library (``firmware/LemLib.a``) is
compiled for the V5's ARM CPU. vexsim fetches the LemLib source for the version
the project lists in ``project.pros`` (git, else a zip download; cached), and
compiles it against the PROS shim once per version and compiler.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from vexsim.bridge.build import (
    SHIM_INCLUDE,
    BuildError,
    Template,
    Toolchain,
    _archive,
    _compile_all,
    _compile_cmd,
    _digest,
    cache_root,
)

REPO = "https://github.com/LemLib/LemLib"
TESTED = ("0.5.",)  # release lines vexsim is tested against
KEEP = ("include/lemlib", "include/fmt", "src/lemlib", "LICENSE")


def find_version(project: Path, templates: dict[str, Template]) -> str | None:
    """The LemLib version this project uses, or None if it doesn't use LemLib."""
    for name, template in templates.items():
        if name.lower() == "lemlib":
            if template.version:
                return template.version
    if not (project / "include" / "lemlib").is_dir() and not any(
        name.lower() == "lemlib" for name in templates
    ):
        return None
    version = os.environ.get("VEXSIM_LEMLIB_VERSION")
    if version:
        return version
    raise BuildError(
        "this project uses LemLib (include/lemlib), but project.pros doesn't say which version. "
        "Set VEXSIM_LEMLIB_VERSION (for example 0.5.6)."
    )


def _fetch_git(version: str, dest: Path) -> None:
    errors = []
    for tag in (f"v{version}", version):
        result = subprocess.run(
            ["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1",
             "--branch", tag, REPO, str(dest)],
            capture_output=True, text=True, errors="replace",
        )  # fmt: skip
        if result.returncode == 0:
            return
        errors.append(result.stderr.strip())
        shutil.rmtree(dest, ignore_errors=True)
    raise BuildError("git clone failed: " + " | ".join(errors))


def _fetch_zip(version: str, dest: Path) -> None:
    errors = []
    for tag in (f"v{version}", version):
        url = f"{REPO}/archive/refs/tags/{tag}.zip"
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
        except OSError as exc:
            errors.append(f"{url}: {exc}")
            continue
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            archive.extractall(dest.parent / (dest.name + "-zip"))
        (top,) = list((dest.parent / (dest.name + "-zip")).iterdir())
        os.replace(top, dest)
        shutil.rmtree(dest.parent / (dest.name + "-zip"), ignore_errors=True)
        return
    raise BuildError("download failed: " + " | ".join(errors))


def source_dir(version: str, log: Callable[[str], None] | None = None) -> Path:
    """LemLib's sources for ``version``: $VEXSIM_LEMLIB_SOURCE, or fetched once into the cache."""
    override = os.environ.get("VEXSIM_LEMLIB_SOURCE")
    if override:
        path = Path(override)
        if not (path / "src" / "lemlib").is_dir() or not (path / "include" / "lemlib").is_dir():
            raise BuildError(f"VEXSIM_LEMLIB_SOURCE={path} is not a LemLib source checkout")
        return path
    dest = cache_root() / "lemlib-src" / version
    if (dest / "src" / "lemlib").is_dir():
        return dest
    if log:
        log(f"fetching LemLib {version} source from {REPO}")
    work = dest.with_name(version + ".download")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    repo = work / "repo"
    try:
        try:
            _fetch_git(version, repo)
        except (BuildError, OSError) as git_error:
            try:
                _fetch_zip(version, repo)
            except BuildError as zip_error:
                raise BuildError(f"{git_error}; {zip_error}") from None
        keep = work / "keep"
        for rel in KEEP:
            src = repo / rel
            if src.is_dir():
                shutil.copytree(src, keep / rel)
            elif src.is_file():
                (keep / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, keep / rel)
        if not (keep / "src" / "lemlib").is_dir():
            raise BuildError(f"LemLib {version} has no src/lemlib")
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(keep, dest)
    except BuildError as exc:
        raise BuildError(
            f"couldn't get LemLib {version}'s source ({exc}). Check your internet connection, "
            "or point VEXSIM_LEMLIB_SOURCE at a LemLib checkout of that version."
        ) from None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return dest


def build_library(
    tc: Toolchain,
    version: str,
    *,
    workers: int | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[Path, Path]:
    """Compile LemLib (cached); returns its include folder and its static library."""
    src = source_dir(version, log)
    sources = sorted((src / "src" / "lemlib").rglob("*.cpp"))
    headers = sorted((src / "include").rglob("*.h*")) + sorted(SHIM_INCLUDE.rglob("*.h*"))
    opt = ["-O2", "-w"]  # LemLib's own warnings aren't the user's business
    key = _digest(
        tc.cxx, tc.version_text, tc.target, version, *opt,
        *[p.read_bytes() for p in sources + headers],
    )  # fmt: skip
    out = cache_root() / f"lemlib-{version}-{key}"
    lib = out / "liblemlib.a"
    include = src / "include"
    if lib.exists():
        return include, lib
    if log:
        log(f"compiling LemLib {version} ({len(sources)} files, once per version)")
    jobs = []
    for source in sources:
        rel = source.relative_to(src / "src")
        obj = out / rel.with_suffix(".o")
        quote = [include / rel.parent]  # as PROS's makefile does
        cmd = _compile_cmd(tc, source, obj, [SHIM_INCLUDE, include], opt, quote)
        jobs.append((source, obj, cmd))
    _compile_all(tc, jobs, workers or os.cpu_count() or 2, lambda s: s)
    _archive(tc, lib, [obj for _, obj, _ in jobs])
    return include, lib


def tested(version: str) -> bool:
    return version.startswith(TESTED)

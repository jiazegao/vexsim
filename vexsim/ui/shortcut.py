"""Shortcuts that open a workspace in vexsim's window: ``vexsim shortcut [FOLDER]``.

A shortcut runs ``vexsim ui FOLDER --window`` with this Python, so it works for as long as
this Python has vexsim installed:

- Windows: a shortcut in the Start menu and one on the desktop (run with pythonw, so no
  console window opens)
- Linux: an entry in the applications menu (``~/.local/share/applications``)
- macOS: an app in ``~/Applications``, which Launchpad and Spotlight find

``vexsim shortcut --remove`` takes a folder's shortcuts away again.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from vexsim import __version__
from vexsim.bridge.build import NO_CONSOLE

ICONS = Path(__file__).parent / "static" / "icons"


class ShortcutError(RuntimeError):
    """A shortcut couldn't be made."""


@dataclass(frozen=True)
class Shortcut:
    """A shortcut that opens ``folder`` (absolute) in vexsim's window."""

    folder: Path

    @property
    def name(self) -> str:
        return f"vexsim ({self.folder.name or self.folder})"  # a drive's root has no name

    @property
    def slug(self) -> str:
        """A file name for it: the folder's name and a hash of its path (two folders may
        have the same name)."""
        stem = re.sub(r"[^A-Za-z0-9.-]+", "-", self.folder.name).strip("-.") or "folder"
        digest = hashlib.sha1(str(self.folder).encode()).hexdigest()[:6]
        return f"vexsim-{stem}-{digest}"

    def command(self) -> list[str]:
        """What it runs: ``python -m vexsim ui FOLDER --window``."""
        return [python(), "-m", "vexsim", "ui", str(self.folder), "--window"]


def python() -> str:
    """This Python; on Windows its pythonw.exe, which opens no console window."""
    executable = Path(sys.executable)
    if sys.platform == "win32" and executable.with_name("pythonw.exe").is_file():
        return str(executable.with_name("pythonw.exe"))
    return str(executable)


def places() -> dict[str, Path]:
    """Where this computer's shortcuts go: the menu's folder (and on Windows, the desktop)."""
    if sys.platform == "win32":
        return {"Start menu": _windows_folder(0x02), "desktop": _windows_folder(0x10)}
    if sys.platform == "darwin":
        return {"Applications folder": Path.home() / "Applications"}
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return {"applications menu": data / "applications"}


def _windows_folder(csidl: int) -> Path:
    """A folder of the Windows shell's (CSIDL_PROGRAMS, CSIDL_DESKTOPDIRECTORY), wherever it
    has been moved to (OneDrive, say)."""
    import ctypes

    buffer = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buffer) != 0:
        raise ShortcutError("Windows didn't say where its Start menu and desktop are")
    return Path(buffer.value)


def path_in(place: Path, shortcut: Shortcut) -> Path:
    """The shortcut's file (or app) in the folder ``place``."""
    if sys.platform == "win32":
        return place / f"{shortcut.name}.lnk"
    if sys.platform == "darwin":
        return place / f"{shortcut.name}.app"
    return place / f"{shortcut.slug}.desktop"


def make(folder: Path, where: dict[str, Path] | None = None) -> dict[str, Path]:
    """Make the shortcuts to open ``folder`` in each of ``where``'s folders (default:
    ``places()``); what each made."""
    shortcut = Shortcut(Path(folder).resolve())
    made = {}
    for label, place in (where or places()).items():
        path = path_in(place, shortcut)
        place.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            write_lnk(path, shortcut, ICONS / "vexsim.ico")
        elif sys.platform == "darwin":
            write_app(path, shortcut, ICONS / "vexsim.icns")
        else:
            path.write_text(desktop_entry(shortcut, ICONS / "vexsim-512.png"), encoding="utf-8")
            path.chmod(0o755)  # a launcher on the desktop has to be executable
        made[label] = path
    return made


def remove(folder: Path, where: dict[str, Path] | None = None) -> dict[str, Path]:
    """Remove the shortcuts ``make`` made for ``folder``; the ones there were."""
    shortcut = Shortcut(Path(folder).resolve())
    removed = {}
    for label, place in (where or places()).items():
        path = path_in(place, shortcut)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        else:
            continue
        removed[label] = path
    return removed


# --- Windows: a .lnk file, made by the Windows shell ------------------------------------------

_LNK = """\
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($env:VEXSIM_LNK)
$link.TargetPath = $env:VEXSIM_TARGET
$link.Arguments = $env:VEXSIM_ARGUMENTS
$link.WorkingDirectory = $env:VEXSIM_FOLDER
$link.IconLocation = $env:VEXSIM_ICON
$link.Description = $env:VEXSIM_DESCRIPTION
$link.Save()
"""


def write_lnk(path: Path, shortcut: Shortcut, icon: Path) -> None:
    target, *arguments = shortcut.command()
    env = {
        **os.environ,
        "VEXSIM_LNK": str(path),
        "VEXSIM_TARGET": target,
        "VEXSIM_ARGUMENTS": subprocess.list2cmdline(arguments),
        "VEXSIM_FOLDER": str(shortcut.folder),
        "VEXSIM_ICON": f"{icon},0",
        "VEXSIM_DESCRIPTION": f"Open {shortcut.folder} in vexsim",
    }
    powershell(_LNK, env)


def powershell(script: str, env: dict[str, str] | None = None) -> str:
    """Run a PowerShell script (the values it uses in environment variables); its output."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            errors="replace",
            env=env,
            creationflags=NO_CONSOLE,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ShortcutError(f"PowerShell didn't run: {exc}") from exc
    if result.returncode != 0:
        raise ShortcutError(f"PowerShell failed: {result.stderr.strip()}")
    return result.stdout


# --- Linux: a desktop entry -------------------------------------------------------------------

_RESERVED = set(" \t\n\"'\\><~|&;$*?#()`")


def desktop_entry(shortcut: Shortcut, icon: Path) -> str:
    """The shortcut as a desktop entry (the freedesktop.org format)."""
    command = " ".join(_exec_argument(arg) for arg in shortcut.command())
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={_value(shortcut.name)}",
        f"Comment={_value(f'Open {shortcut.folder} in vexsim')}",
        f"Exec={_value(command)}",
        f"Path={_value(str(shortcut.folder))}",
        f"Icon={_value(str(icon))}",
        "Terminal=false",
        "Categories=Development;",
    ]
    return "\n".join(lines) + "\n"


def _exec_argument(arg: str) -> str:
    """An argument of an Exec line: quoted if it has to be, with what's special in quotes
    escaped; a % is %%."""
    arg = arg.replace("%", "%%")
    if _RESERVED.intersection(arg):
        arg = '"' + re.sub(r'(["`$\\])', r"\\\1", arg) + '"'
    return arg


def _value(text: str) -> str:
    """A string value, its backslashes and line breaks escaped."""
    escapes = {"\\": "\\\\", "\n": "\\n", "\t": "\\t", "\r": "\\r"}
    return "".join(escapes.get(c, c) for c in text)


# --- macOS: an app ----------------------------------------------------------------------------


def write_app(path: Path, shortcut: Shortcut, icon: Path) -> None:
    """An app bundle whose program is a shell script running the command. It keeps this
    PATH: apps start with a bare one, without Homebrew's g++ for building robot code."""
    contents = path / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Resources").mkdir(exist_ok=True)
    launcher = contents / "MacOS" / "vexsim"
    script = ["#!/bin/sh", f"export PATH={shlex.quote(os.environ.get('PATH', ''))}"]
    script.append(f"exec {shlex.join(shortcut.command())}")
    launcher.write_text("\n".join(script) + "\n", encoding="utf-8")
    launcher.chmod(0o755)
    shutil.copyfile(icon, contents / "Resources" / "vexsim.icns")
    info = {
        "CFBundleExecutable": "vexsim",
        "CFBundleIconFile": "vexsim.icns",
        "CFBundleIdentifier": f"local.vexsim.{shortcut.slug}",
        "CFBundleName": shortcut.name,
        "CFBundleDisplayName": shortcut.name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": __version__,
        "LSUIElement": True,  # the launcher has no Dock icon of its own: the window has one
    }
    with open(contents / "Info.plist", "wb") as file:
        plistlib.dump(info, file)

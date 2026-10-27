"""vexsim in a window of its own: the app in a browser's app mode.

``vexsim ui --window`` opens the app with ``--app=URL`` in a browser that has an app mode
(Microsoft Edge, which every Windows has, Google Chrome, Chromium or Brave): a window with
no tabs or address bar, under the app's own title and icon. It runs on a browser profile of
its own, so it's a window apart from your browsing and keeps its size and place. With none
of those browsers, the app opens in your default browser.

``$VEXSIM_BROWSER`` names the browser to use instead. The server stops when the app's last
page closes (``vexsim.ui.server``), so a window started from a shortcut doesn't leave it
running.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

WINDOW_SIZE = (1440, 920)

# Where each platform keeps the browsers that have an app mode, best first
_WINDOWS = [
    ("Microsoft", "Edge", "Application", "msedge.exe"),
    ("Google", "Chrome", "Application", "chrome.exe"),
    ("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
    ("Chromium", "Application", "chrome.exe"),
]
_MACOS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]
_LINUX = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "microsoft-edge-stable",
    "brave-browser",
]


def user_folder() -> Path:
    """vexsim's own folder for this user: %LOCALAPPDATA%\\vexsim on Windows, else
    ~/.cache/vexsim (where builds go too)."""
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "vexsim"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "vexsim"


def find_browser() -> str | None:
    """A browser with an app mode: $VEXSIM_BROWSER, else the first one installed."""
    chosen = os.environ.get("VEXSIM_BROWSER")
    if chosen:
        return chosen
    if sys.platform == "win32":
        roots = [os.environ.get(v) for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        for parts in _WINDOWS:
            for root in filter(None, roots):
                path = Path(root, *parts)
                if path.is_file():
                    return str(path)
        return None
    if sys.platform == "darwin":
        return next((path for path in _MACOS if Path(path).is_file()), None)
    return next(filter(None, (shutil.which(name) for name in _LINUX)), None)


def window_command(browser: str, url: str, profile: Path) -> list[str]:
    """The command that opens ``url`` in ``browser``'s app mode, on ``profile``."""
    width, height = WINDOW_SIZE
    return [
        browser,
        f"--app={url}",
        f"--user-data-dir={profile}",
        f"--window-size={width},{height}",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def open_window(url: str) -> bool:
    """Open the app at ``url`` in a window of its own; in the default browser if there's no
    browser with an app mode, or it doesn't start. True if it's a window of its own."""
    browser = find_browser()
    if browser is not None:
        try:
            subprocess.Popen(
                window_command(browser, url, user_folder() / "window"),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=sys.platform != "win32",  # it outlives a Ctrl+C here
            )
            return True
        except OSError:
            pass
    webbrowser.open(url)
    return False

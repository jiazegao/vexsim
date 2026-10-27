"""The app on the desktop: a window of its own that stops the server when it closes
(vexsim/ui/window.py, the server's presence), and shortcuts (vexsim/ui/shortcut.py)."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from tests.conftest import ROOT
from vexsim.cli import _log_when_windowless, build_parser, main
from vexsim.ui import shortcut, window

TOKEN = "test-token"


@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    app = create_app(
        ROOT, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as test_client:
        yield test_client


# --- a window of its own ----------------------------------------------------------------------


def test_a_browser_with_an_app_mode_is_found(tmp_path, monkeypatch):
    monkeypatch.setenv("VEXSIM_BROWSER", "/my/browser")
    assert window.find_browser() == "/my/browser"
    monkeypatch.delenv("VEXSIM_BROWSER")
    if sys.platform == "win32":
        for name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            monkeypatch.setenv(name, str(tmp_path / name))
        assert window.find_browser() is None
        chrome = tmp_path / "LOCALAPPDATA" / "Google" / "Chrome" / "Application" / "chrome.exe"
        edge = tmp_path / "ProgramFiles" / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    elif sys.platform == "darwin":
        chrome, edge = tmp_path / "Google Chrome", tmp_path / "Microsoft Edge"
        monkeypatch.setattr(window, "_MACOS", [str(chrome), str(edge)])
    else:
        monkeypatch.setenv("PATH", str(tmp_path))
        assert window.find_browser() is None
        edge, chrome = tmp_path / "google-chrome", tmp_path / "chromium"
    chrome.parent.mkdir(parents=True, exist_ok=True)
    chrome.write_text("")
    chrome.chmod(0o755)
    assert window.find_browser() == str(chrome)
    edge.parent.mkdir(parents=True, exist_ok=True)
    edge.write_text("")
    edge.chmod(0o755)
    assert window.find_browser() == str(edge)  # the better one


def test_the_window_is_the_browsers_app_mode_on_a_profile_of_its_own(tmp_path):
    command = window.window_command("chrome", "http://127.0.0.1:8642/?token=t", tmp_path)
    assert command[:3] == [
        "chrome",
        "--app=http://127.0.0.1:8642/?token=t",
        f"--user-data-dir={tmp_path}",
    ]
    assert "--window-size=1440,920" in command and "--no-first-run" in command


def test_without_such_a_browser_the_default_one_opens_it(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(window.webbrowser, "open", opened.append)
    monkeypatch.setattr(window, "find_browser", lambda: None)
    assert window.open_window("http://127.0.0.1:1/") is False and opened == ["http://127.0.0.1:1/"]
    monkeypatch.setattr(window, "find_browser", lambda: str(tmp_path / "gone"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert window.open_window("http://127.0.0.1:2/") is False  # it didn't start
    assert opened[-1] == "http://127.0.0.1:2/"


def test_ui_takes_a_window_or_no_browser():
    args = build_parser().parse_args(["ui", "--window"])
    assert args.window and not args.no_browser and not args.stop_when_closed
    with pytest.raises(SystemExit):
        build_parser().parse_args(["ui", "--window", "--no-browser"])


def test_with_no_console_what_it_says_goes_to_a_log(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert _log_when_windowless() is False  # it has one
    monkeypatch.setattr(sys, "stdout", None)  # as under pythonw
    monkeypatch.setattr(sys, "stderr", None)
    assert _log_when_windowless() is True
    print("hello")
    log = sys.stdout
    log.close()
    assert sys.stderr is log
    assert (window.user_folder() / "ui.log").read_text() == "hello\n"


# --- the server knows when its pages have closed ----------------------------------------------


def test_the_server_counts_the_apps_pages_and_its_files_need_no_token(client):
    def pages():
        return client.get("/api/info", headers={"authorization": f"Bearer {TOKEN}"}).json()["pages"]

    assert pages() == 0
    with client.websocket_connect(f"/api/presence?token={TOKEN}"):
        assert pages() == 1
        with client.websocket_connect(f"/api/presence?token={TOKEN}"):
            assert pages() == 2
    deadline = time.monotonic() + 5
    while pages() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pages() == 0
    page = client.get(f"/?token={TOKEN}").text
    script = re.search(r'src="(/assets/[^"]+\.js)"', page).group(1)
    client.cookies.clear()
    assert client.get(script).status_code == 200  # no token: a framed page gets no cookie
    assert client.get("/").status_code == 401 and client.get("/api/info").status_code == 401
    encoded = client.get(f"/api/info?embed=vscode&token%3D{TOKEN}")  # VS Code's Uri writes =
    assert encoded.status_code == 200
    assert client.get(script, headers={"host": "evil.example"}).status_code == 403


def test_the_server_stops_once_its_pages_have_closed():
    from vexsim.ui.server import Pages, stop_when_closed_for

    def watch(pages, grace, first):
        server = SimpleNamespace(should_exit=False)
        started = time.monotonic()
        thread = threading.Thread(target=stop_when_closed_for, args=(server, pages, grace, first))
        thread.start()
        return server, thread, started

    pages = Pages()
    server, thread, started = watch(pages, 0.2, 0.6)  # no page ever opens
    thread.join(5)
    assert server.should_exit and time.monotonic() - started >= 0.6

    pages = Pages()
    server, thread, _ = watch(pages, 0.3, 60)
    pages.opened()
    time.sleep(0.5)
    pages.closed()
    pages.opened()  # a reload
    time.sleep(0.5)
    assert not server.should_exit
    pages.closed()
    closed = time.monotonic()
    thread.join(5)
    assert server.should_exit and time.monotonic() - closed >= 0.3


FAKE_BROWSER = """\
import sys
import time
from urllib.parse import urlsplit

from websockets.sync.client import connect

with open(sys.argv[1], "w") as record:
    record.write("\\n".join(sys.argv[2:]))
url = urlsplit(next(arg[6:] for arg in sys.argv if arg.startswith("--app=")))
with connect(f"ws://{url.netloc}/api/presence?{url.query}"):
    time.sleep(1.0)  # the window is open for a second, then closed
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_vexsim_ui_window_stops_when_its_window_closes(tmp_path):
    pytest.importorskip("uvicorn")
    pytest.importorskip("websockets")
    script, record = tmp_path / "fake_browser.py", tmp_path / "browser-args.txt"
    script.write_text(FAKE_BROWSER)
    # The "browser" is a program: a batch file on Windows, a shell script elsewhere
    if sys.platform == "win32":
        browser = tmp_path / "browser.cmd"
        browser.write_text(f'@"{sys.executable}" "{script}" "{record}" %*\n')
    else:
        browser = tmp_path / "browser"
        browser.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "{record}" "$@"\n')
        browser.chmod(0o755)
    env = {
        **os.environ,
        "VEXSIM_BROWSER": str(browser),
        "VEXSIM_UI_GRACE_S": "0.5",
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "LOCALAPPDATA": str(tmp_path / "local"),
    }
    port = free_port()
    started = time.monotonic()
    finished = subprocess.run(
        [
            sys.executable,
            "-m",
            "vexsim",
            "ui",
            str(ROOT / "examples"),
            "--window",
            "--port",
            str(port),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
    )
    output = finished.stdout + finished.stderr
    assert finished.returncode == 0, output
    assert "It stops when you close the app" in output and "The app was closed" in output
    assert time.monotonic() - started < 30
    args = record.read_text().splitlines()
    assert args[0].startswith(f"--app=http://127.0.0.1:{port}/?token=")
    profile = tmp_path / ("local" if sys.platform == "win32" else "cache") / "vexsim" / "window"
    assert args[1] == f"--user-data-dir={profile}"


# --- shortcuts --------------------------------------------------------------------------------


def test_a_shortcut_is_named_for_its_folder():
    one = shortcut.Shortcut(Path("/teams/1239E 2026_27"))
    assert one.name == "vexsim (1239E 2026_27)"
    assert re.fullmatch(r"vexsim-1239E-2026-27-[0-9a-f]{6}", one.slug)
    assert shortcut.Shortcut(Path("/other/1239E 2026_27")).slug != one.slug  # same name


def test_a_desktop_entry_quotes_what_it_runs(monkeypatch):
    monkeypatch.setattr(shortcut, "python", lambda: "/usr/bin/python3")
    folder, icon = PurePosixPath("/home/me/robots/$100 bot"), PurePosixPath("/icons/vexsim.png")
    entry = shortcut.desktop_entry(shortcut.Shortcut(folder), icon)  # Linux's paths, anywhere
    lines = entry.splitlines()
    assert lines[0] == "[Desktop Entry]" and "Name=vexsim ($100 bot)" in lines
    # quoted, its $ escaped for the quotes, and that backslash escaped for the file
    exec_line = 'Exec=/usr/bin/python3 -m vexsim ui "/home/me/robots/\\\\$100 bot" --window'
    assert exec_line in lines
    assert "Path=/home/me/robots/$100 bot" in lines and "Icon=/icons/vexsim.png" in lines
    assert shortcut._exec_argument("50%") == "50%%"


def test_a_macos_shortcut_is_an_app(tmp_path, monkeypatch):
    monkeypatch.setattr(shortcut, "python", lambda: "/usr/local/bin/python3")
    monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/bin")
    one = shortcut.Shortcut(PurePosixPath("/Users/me/my robot"))  # macOS's paths, anywhere
    app = tmp_path / "vexsim (my robot).app"
    shortcut.write_app(app, one, shortcut.ICONS / "vexsim.icns")
    import plistlib

    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "vexsim" and info["LSUIElement"] is True
    assert info["CFBundleIdentifier"] == f"local.vexsim.{one.slug}"
    launcher = app / "Contents" / "MacOS" / "vexsim"
    assert launcher.read_text().splitlines() == [
        "#!/bin/sh",
        "export PATH=/opt/homebrew/bin:/usr/bin",
        "exec /usr/local/bin/python3 -m vexsim ui '/Users/me/my robot' --window",
    ]
    if sys.platform != "win32":
        assert launcher.stat().st_mode & 0o111
    assert (app / "Contents" / "Resources" / "vexsim.icns").read_bytes()[:4] == b"icns"


def test_vexsim_shortcut_makes_and_removes_them(tmp_path, monkeypatch, capsys):
    pytest.importorskip("fastapi")
    menu = tmp_path / "menu"
    monkeypatch.setattr(shortcut, "places", lambda: {"menu": menu})
    folder = tmp_path / "my robot"
    folder.mkdir()
    assert main(["shortcut", str(folder)]) == 0
    made = shortcut.path_in(menu, shortcut.Shortcut(folder.resolve()))
    assert made.exists() and f"menu: {made}" in capsys.readouterr().out
    if sys.platform == "win32":  # the shell reads it back
        script = (
            "$link = (New-Object -ComObject WScript.Shell).CreateShortcut($env:VEXSIM_LNK); "
            "$link.TargetPath; $link.Arguments; $link.IconLocation; $link.WorkingDirectory"
        )
        target, arguments, icon, start_in = shortcut.powershell(
            script, {**os.environ, "VEXSIM_LNK": str(made)}
        ).splitlines()
        assert target.lower().endswith("pythonw.exe")
        assert arguments == f'-m vexsim ui "{folder.resolve()}" --window'
        assert icon.lower() == f"{shortcut.ICONS / 'vexsim.ico'},0".lower()
        assert start_in == str(folder.resolve())
    elif sys.platform != "darwin":
        assert f"Exec={shortcut.python()} -m vexsim ui " in made.read_text()
    assert main(["shortcut", str(folder), "--remove"]) == 0
    assert not made.exists() and f"Removed from the menu: {made}" in capsys.readouterr().out
    assert main(["shortcut", str(folder), "--remove"]) == 0
    assert "has no shortcuts to remove" in capsys.readouterr().out
    assert main(["shortcut", str(tmp_path / "gone")]) == 1


# --- the VS Code panel ------------------------------------------------------------------------


def test_the_vscode_extension_packs_into_a_vsix(tmp_path):
    import json
    import zipfile
    from xml.etree import ElementTree

    from vexsim import __version__
    from vexsim.ui import vsix

    out = vsix.build(tmp_path / "vexsim.vsix", python="/my/python")
    with zipfile.ZipFile(out) as package:
        names = set(package.namelist())
        assert {"[Content_Types].xml", "extension.vsixmanifest", "extension/package.json"} <= names
        assert {
            "extension/extension.js",
            "extension/panel.js",
            "extension/media/vexsim.png",
        } <= names
        manifest = json.loads(package.read("extension/package.json"))
        xml = ElementTree.fromstring(package.read("extension.vsixmanifest"))
        icon = package.read("extension/media/vexsim.png")
    assert manifest["version"] == __version__ and manifest["main"] == "./extension.js"
    setting = manifest["contributes"]["configuration"]["properties"]["vexsim.python"]
    assert setting["default"] == "/my/python"
    namespace = {"v": "http://schemas.microsoft.com/developer/vsx-schema/2011"}
    identity = xml.find("v:Metadata/v:Identity", namespace)
    assert identity.get("Id") == "vexsim" and identity.get("Version") == __version__
    assert f"{identity.get('Publisher')}.{identity.get('Id')}" == vsix.ID
    assert icon[:4] == b"\x89PNG"
    commands = {c["command"] for c in manifest["contributes"]["commands"]}
    assert {"vexsim.open", "vexsim.openFolder", "vexsim.stop"} == commands


def test_vexsim_vscode_installs_it_with_vs_codes_command(tmp_path, monkeypatch, capsys):
    pytest.importorskip("fastapi")
    from vexsim.ui import vsix

    record = tmp_path / "code-args.txt"
    script = tmp_path / "fake_code.py"
    script.write_text(
        "import sys\n"
        f"open({str(record)!r}, 'w').write('\\n'.join(sys.argv[1:]))\n"
        "print(\"Extension 'vexsim.vsix' was successfully installed.\")\n"
    )
    if sys.platform == "win32":
        code = tmp_path / "code.cmd"
        code.write_text(f'@"{sys.executable}" "{script}" %*\n')
    else:
        code = tmp_path / "code"
        code.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        code.chmod(0o755)
    out = tmp_path / "out" / "vexsim.vsix"
    assert main(["vscode", "--no-install", "--out", str(out)]) == 0
    assert out.is_file() and not record.exists()
    assert main(["vscode", "--out", str(out), "--code", str(code)]) == 0
    assert record.read_text().splitlines() == ["--install-extension", str(out), "--force"]
    said = capsys.readouterr().out
    assert "successfully installed" in said and "vexsim: Open the app" in said
    monkeypatch.setattr(vsix, "find_code", lambda name: None)
    assert main(["vscode", "--out", str(out)]) == 1
    assert "Install from VSIX" in capsys.readouterr().out

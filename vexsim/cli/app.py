"""The app: ``vexsim ui``, ``shortcut`` and ``vscode``."""

from __future__ import annotations

import argparse
import sys

from vexsim.cli.common import EXIT_INVALID, EXIT_OK


def add_app(sub) -> None:
    """The parser's commands: ui, shortcut, vscode."""
    p = sub.add_parser(
        "ui",
        help="open the vexsim app in your browser",
        description=(
            "Start the vexsim app for a folder (its workspace) and open it in your browser. "
            "It finds the robots, fields, programs and PROS projects in the folder; run "
            "and watch simulations from there. It listens on this computer only."
        ),
    )
    p.add_argument("folder", nargs="?", default=".", help="workspace folder (default: here)")
    p.add_argument("--port", type=int, help="port (default: 8642, or any free one)")
    where = p.add_mutually_exclusive_group()
    where.add_argument(
        "--window",
        action="store_true",
        help="open it in a window of its own (Edge's or Chrome's app mode); "
        "it stops when you close the window",
    )
    where.add_argument("--no-browser", action="store_true", help="don't open a browser")
    # stop when the app's last page closes (the VS Code panel opens it itself)
    p.add_argument("--stop-when-closed", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--token", help=argparse.SUPPRESS)  # fixed token, for tests
    p.add_argument("--dev", action="store_true", help=argparse.SUPPRESS)  # Vite dev server
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser(
        "shortcut",
        help="make shortcuts that open a folder in the vexsim app's window",
        description=(
            "Make shortcuts that open a workspace folder in the vexsim app, in a window of its "
            "own (vexsim ui FOLDER --window): in the Start menu and on the desktop on Windows, "
            "in the applications menu on Linux, in ~/Applications on macOS. They use this "
            "Python, so they work for as long as it has vexsim installed."
        ),
    )
    p.add_argument("folder", nargs="?", default=".", help="workspace folder (default: here)")
    p.add_argument("--remove", action="store_true", help="remove the folder's shortcuts")
    p.set_defaults(func=cmd_shortcut)

    p = sub.add_parser(
        "vscode",
        help="install the VS Code extension that shows the app in a panel",
        description=(
            "Install vexsim's VS Code extension. Then 'vexsim: Open the app' (Command Palette) "
            "or 'Open in vexsim' (on a folder in the Explorer) shows the app in a panel beside "
            "your code, where file:line links open in the editor. It runs vexsim with this "
            "Python."
        ),
    )
    p.add_argument(
        "--code",
        default="code",
        help="the editor's command (default: code; or code-insiders, cursor, codium)",
    )
    p.add_argument("--out", help="where to write the .vsix (default: vexsim's own folder)")
    p.add_argument("--no-install", action="store_true", help="only write the .vsix")
    p.set_defaults(func=cmd_vscode)


def cmd_ui(args: argparse.Namespace) -> int:
    from pathlib import Path

    windowless = _log_when_windowless()
    folder = Path(args.folder)
    if not folder.is_dir():
        return _ui_error(f"{args.folder} is not a folder", windowless)
    try:
        from vexsim.ui.server import serve
    except ModuleNotFoundError as exc:
        return _ui_error(
            f'the UI needs {exc.name}; install it with: pip install -e ".[ui]"', windowless
        )
    try:
        serve(
            folder,
            port=args.port,
            open_browser=not args.no_browser,
            window=args.window,
            stop_when_closed=args.stop_when_closed,
            token=args.token,
            dev=args.dev,
        )
    except OSError as exc:
        return _ui_error(str(exc), windowless)
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def cmd_shortcut(args: argparse.Namespace) -> int:
    from pathlib import Path

    from vexsim.ui import shortcut

    folder = Path(args.folder).resolve()
    try:
        if args.remove:
            removed = shortcut.remove(folder)
            for label, path in removed.items():
                print(f"Removed from the {label}: {path}")
            if not removed:
                print(f"{folder} has no shortcuts to remove")
            return EXIT_OK
        if not folder.is_dir():
            print(f"error: {args.folder} is not a folder")
            return EXIT_INVALID
        if _ui_missing():
            return EXIT_INVALID
        made = shortcut.make(folder)
    except (shortcut.ShortcutError, OSError) as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    print(f"Shortcuts that open {folder} in the vexsim app:")
    for label, path in made.items():
        print(f"  {label}: {path}")
    return EXIT_OK


def cmd_vscode(args: argparse.Namespace) -> int:
    from pathlib import Path

    from vexsim.ui import vsix
    from vexsim.ui.window import user_folder

    if _ui_missing():
        return EXIT_INVALID
    out = Path(args.out) if args.out else user_folder() / "vexsim.vsix"
    try:
        vsix.build(out)
    except OSError as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    print(f"Wrote the extension: {out}")
    if args.no_install:
        return EXIT_OK
    code = vsix.find_code(args.code)
    if code is None:
        print(
            f"error: can't find VS Code's command ({args.code}). In VS Code, install {out} "
            "from the Extensions view: its ... menu, Install from VSIX..."
        )
        return EXIT_INVALID
    try:
        said = vsix.install(out, code)
    except vsix.VsixError as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    if said:
        print(said)
    print(
        "In VS Code: 'vexsim: Open the app' from the Command Palette (Ctrl+Shift+P), or "
        "'Open in vexsim' on a folder in the Explorer."
    )
    return EXIT_OK


def _ui_missing() -> bool:
    """Say so if the app's packages (the [ui] extra) aren't installed."""
    from importlib.util import find_spec

    missing = [name for name in ("fastapi", "uvicorn", "websockets") if not find_spec(name)]
    if missing:
        print(f'error: the app needs {missing[0]}; install it with: pip install -e ".[ui]"')
    return bool(missing)


def _log_when_windowless() -> bool:
    """Started with no console (pythonw, from a shortcut): what it prints goes to ui.log in
    vexsim's own folder instead, to find out why if it doesn't open. True if so."""
    if sys.stdout is not None and sys.stderr is not None:
        return False
    from vexsim.ui.window import user_folder

    try:
        user_folder().mkdir(parents=True, exist_ok=True)
        log = open(user_folder() / "ui.log", "w", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return True
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log
    return True


def _ui_error(message: str, windowless: bool) -> int:
    print(f"error: {message}")
    if windowless and sys.platform == "win32":  # there's nowhere else to see it
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "vexsim", 0x10)  # an error icon
    return EXIT_INVALID

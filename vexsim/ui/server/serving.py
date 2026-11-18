"""``vexsim ui``: the server on a port of this computer, stopped when its last page closes."""

from __future__ import annotations

import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from vexsim.ui.server.app import create_app
from vexsim.ui.server.state import Pages

DEFAULT_PORT = 8642


DEV_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")  # Vite's dev server


def _listen(port: int | None) -> socket.socket:
    """A listening socket on 127.0.0.1: ``port``, else the default, else any free port."""
    candidates = [port] if port else [DEFAULT_PORT, 0]
    error: OSError | None = None
    for candidate in candidates:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if sys.platform != "win32":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", candidate))
            sock.listen(128)
            return sock
        except OSError as exc:
            sock.close()
            error = exc
    raise OSError(f"can't listen on 127.0.0.1:{port or DEFAULT_PORT}: {error}")


def serve(
    folder: str | Path = ".",
    *,
    port: int | None = None,
    open_browser: bool = True,
    window: bool = False,
    stop_when_closed: bool = False,
    token: str | None = None,
    dev: bool = False,
) -> None:
    """Run the UI for ``folder`` until Ctrl+C, or with ``stop_when_closed`` until its last
    page has been closed for ``CLOSED_GRACE_S`` (a reload is no close). ``window`` opens it
    in a window of its own (``vexsim.ui.window``), and stops with it."""
    import uvicorn

    from vexsim.ui.window import open_window

    workspace = Path(folder).resolve()
    token = token or secrets.token_urlsafe(24)
    sock = _listen(port)
    actual = sock.getsockname()[1]
    origins = {f"http://127.0.0.1:{actual}", f"http://localhost:{actual}"}
    if dev:
        origins |= set(DEV_ORIGINS)
    app = create_app(workspace, token=token, port=actual, origins=origins)
    url = f"http://127.0.0.1:{actual}/?token={token}"
    stop_when_closed = stop_when_closed or window
    print(f"vexsim UI for {workspace}")
    print(f"  {url}")
    if stop_when_closed:
        print("It stops when you close the app (or press Ctrl+C here).", flush=True)
    else:
        print("Keep this window open while you use it; press Ctrl+C to stop.", flush=True)
    if window:
        threading.Timer(0.5, open_window, args=(url,)).start()
    elif open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    config = uvicorn.Config(
        app, log_level="warning", lifespan="on", ws="auto", timeout_graceful_shutdown=5
    )
    server = uvicorn.Server(config)
    if stop_when_closed:
        pages = app.state.server.pages
        grace = float(os.environ.get("VEXSIM_UI_GRACE_S") or CLOSED_GRACE_S)
        watch = threading.Thread(
            target=stop_when_closed_for, args=(server, pages, grace), daemon=True
        )
        watch.start()
    server.run(sockets=[sock])


CLOSED_GRACE_S = 10.0  # after the last page closes ($VEXSIM_UI_GRACE_S): a reload is no close
FIRST_PAGE_S = 120.0  # for the first page to open


def stop_when_closed_for(server, pages: Pages, grace: float, first: float = FIRST_PAGE_S) -> None:
    """Stop the uvicorn ``server`` (its ``should_exit``) once its pages have all been closed
    for ``grace`` seconds, or if none has opened in ``first`` seconds."""
    while not server.should_exit:
        time.sleep(min(0.25, max(grace / 4, 0.05)))
        idle = pages.idle_for()
        if idle is not None and idle > (grace if pages.ever else first):
            print("The app was closed: vexsim stops.", flush=True)
            server.should_exit = True

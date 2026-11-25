"""The UI's server: the service layer over HTTP and WebSockets, plus the built app.

``vexsim ui [folder]`` runs ``serve``: a FastAPI app on 127.0.0.1 that serves the browser
app from ``static/`` and an API under ``/api``:

- ``GET /api/info``, ``GET /api/workspace[?unless=stamp]``: about the server and what's in
  the folder (nothing is read again while the folder is as it was)
- ``POST /api/sessions`` (``StartSession``): start a run; 422 with a ``RunProblem`` if it
  can't. ``GET /api/sessions[/{id}]``, ``DELETE /api/sessions/{id}`` (stop),
  ``POST /api/sessions/{id}/restart``: its run again, with its code as it is now
- ``WS /api/sessions/{id}/ws``: the session's messages (``ServerMessage``) out, commands
  (``ClientCommand``) in
- ``POST /api/jobs`` (``StartJob``: a build, a benchmark, a sweep, ...),
  ``GET /api/jobs[/{id}?since=n&items_since=k]``, ``DELETE /api/jobs/{id}`` (cancel)
- ``GET /api/results/{kind}[/{id}[/files/{path}]]``, ``DELETE /api/results/{kind}/{id}``:
  what benchmarks, sweeps and calibrations found
- ``GET``/``PUT /api/configurations`` and ``/api/sweeps``: the saved runs and sweeps
- ``GET``/``PUT /api/config``, ``POST /api/config/{check,patch,overrides}``: the editors
- ``GET /api/guide[/doc?id=|/file?path=]``: vexsim's own documents, for the Guide page;
  ``POST /api/programs/starter``: a first program, written into the folder
- ``WS /api/presence``: held open by each of the app's pages, so the server knows when the
  last one closes (``serve(stop_when_closed=True)`` then stops)

The server can build and run code, so every request needs the random token ``serve``
prints (in the URL once, then in a cookie, or with each request as a bearer token), the
Host header must be this server, and WebSockets must come from its own pages.

The package: ``state`` (the server's state, ``UIServer``), ``hub`` (a run's messages fanned
out to the pages watching it), ``guard`` (who may talk to it), then a module of endpoints a
feature (``workspace``, ``configs``, ``routes``, ``runs``, ``sessions``, ``jobs``,
``calibration``, ``guide``), each a function that adds its endpoints to the app; ``app`` adds
them all in order (``create_app``), and ``serving`` runs it (``serve``).
"""

from __future__ import annotations

# the server is FastAPI's: importing this says so at once where it isn't installed
import fastapi  # noqa: F401

from vexsim.ui.server.app import (
    create_app,
)
from vexsim.ui.server.common import (
    STATIC,
)
from vexsim.ui.server.guard import (
    Guard,
)
from vexsim.ui.server.hub import (
    Hub,
    Subscriber,
)
from vexsim.ui.server.serving import (
    CLOSED_GRACE_S,
    DEFAULT_PORT,
    DEV_ORIGINS,
    FIRST_PAGE_S,
    prepare_step,
    serve,
    stop_when_closed_for,
)
from vexsim.ui.server.state import (
    WATCH_S,
    Pages,
    UIServer,
)

__all__ = [
    "STATIC",
    "Subscriber",
    "Hub",
    "WATCH_S",
    "Pages",
    "UIServer",
    "Guard",
    "create_app",
    "DEFAULT_PORT",
    "DEV_ORIGINS",
    "serve",
    "prepare_step",
    "CLOSED_GRACE_S",
    "FIRST_PAGE_S",
    "stop_when_closed_for",
]

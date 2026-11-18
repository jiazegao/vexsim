"""The app: every feature's endpoints added in order, then the built page and the guard."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from vexsim import __version__
from vexsim.app.workspace import Workspace
from vexsim.ui.server.calibration import add_quick_fit, add_session
from vexsim.ui.server.common import STATIC
from vexsim.ui.server.configs import add_configs, add_new
from vexsim.ui.server.guard import Guard
from vexsim.ui.server.guide import add_guide
from vexsim.ui.server.jobs import add_jobs
from vexsim.ui.server.routes import add_routes, add_routines
from vexsim.ui.server.runs import add_runs
from vexsim.ui.server.sessions import add_sessions
from vexsim.ui.server.state import UIServer
from vexsim.ui.server.workspace import add_workspace


def create_app(
    workspace: str | Path,
    *,
    token: str,
    port: int,
    hosts: set[str] | None = None,
    origins: set[str] | None = None,
) -> FastAPI:
    """The UI's app for ``workspace``. ``hosts`` and ``origins`` default to this server's
    own addresses on ``port``."""
    server = UIServer(Workspace(workspace))

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        server.hub.loop = asyncio.get_running_loop()
        yield
        await run_in_threadpool(server.shutdown)

    # (no pages of generated documentation: what each endpoint answers with is in
    # protocol.RESPONSES, and every route here is in it)
    app = FastAPI(title="vexsim", version=__version__, lifespan=lifespan, openapi_url=None)
    app.state.server = server

    add_workspace(app, server)
    add_configs(app, server)
    add_routes(app, server)
    add_new(app, server)
    add_runs(app, server)
    add_routines(app, server)
    add_sessions(app, server)
    add_jobs(app, server)
    add_session(app, server)
    add_guide(app, server)
    add_quick_fit(app, server)

    if (STATIC / "index.html").is_file():
        app.mount("/", StaticFiles(directory=STATIC, html=True), name="app")
    else:

        @app.get("/")
        def not_built() -> HTMLResponse:
            return HTMLResponse(
                "<!doctype html><title>vexsim</title><p>The browser app isn't built: run "
                "<code>npm ci && npm run build</code> in <code>frontend/</code>.</p>"
            )

    app.add_middleware(GZipMiddleware, minimum_size=2048)  # tapes and telemetry are big
    hosts = hosts or {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = origins or {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    app.add_middleware(
        Guard, token=token, cookie=f"vexsim_token_{port}", hosts=hosts, origins=origins
    )
    return app

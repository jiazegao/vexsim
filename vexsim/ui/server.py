"""The UI's server: the service layer over HTTP and WebSockets, plus the built app.

``vexsim ui [folder]`` runs ``serve``: a FastAPI app on 127.0.0.1 that serves the browser
app from ``static/`` and an API under ``/api``:

- ``GET /api/info``, ``GET /api/workspace``: about the server and what's in the folder
- ``POST /api/sessions`` (``StartSession``): start a run; 422 with a ``RunProblem`` if it
  can't. ``GET /api/sessions[/{id}]``, ``DELETE /api/sessions/{id}`` (stop)
- ``WS /api/sessions/{id}/ws``: the session's messages (``ServerMessage``) out, commands
  (``ClientCommand``) in
- ``POST /api/jobs`` (``StartJob``), ``GET /api/jobs[/{id}?since=n]``,
  ``DELETE /api/jobs/{id}`` (cancel)

The server can build and run code, so every request needs the random token ``serve``
prints (in the URL once, then in a cookie), the Host header must be this server, and
WebSockets must come from its own pages.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import math
import platform
import secrets
import socket
import sys
import threading
import webbrowser
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders

from vexsim import __version__
from vexsim.app.frames import preview_of
from vexsim.app.jobs import JobManager
from vexsim.app.launch import (
    LAUNCH_FILE,
    LaunchFileError,
    read_configurations,
    write_configurations,
)
from vexsim.app.runspec import RunError, RunSpec, check
from vexsim.app.session import Session
from vexsim.app.workspace import Workspace
from vexsim.config.field import FieldConfig
from vexsim.ui.protocol import (
    AppInfo,
    ClientCommand,
    JobInfo,
    Preview,
    PreviewRequest,
    RunConfigurations,
    RunProblem,
    SaveConfigurations,
    SessionInfo,
    StartJob,
    StartSession,
    WorkspaceInfo,
)

STATIC = Path(__file__).parent / "static"
DEFAULT_PORT = 8642
DEV_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")  # Vite's dev server
_COMMANDS = TypeAdapter(ClientCommand)
_FRAME = object()  # a frame is waiting in a Subscriber


def _finite(value):
    """JSON-safe: NaN and infinities (which browsers can't parse) become null."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_finite(v) for v in value]
    return value


def dumps(message: dict) -> str:
    return json.dumps(_finite(message), separators=(",", ":"))


# --- fanning messages out to browsers -----------------------------------------------------


class Subscriber:
    """One browser's queue of a session's messages. Frames don't pile up: a slow viewer
    gets the newest frame, never an old one, and every other message in order."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.frame: dict | None = None
        self.floor = 0  # messages numbered up to this were covered by the catch-up

    def push(self, message: dict) -> None:
        if message.get("type") == "frame":
            if self.frame is None:
                self.queue.put_nowait(_FRAME)
            self.frame = message
        else:
            self.queue.put_nowait(message)

    def deliver(self, seq: int, message: dict) -> None:
        if seq > self.floor:
            self.push(message)

    async def next(self) -> dict:
        item = await self.queue.get()
        if item is _FRAME:
            item, self.frame = self.frame, None
        return item


class Hub:
    """Delivers messages published from any thread to the subscribers of a channel."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.channels: dict[str, set[Subscriber]] = {}

    def publish(self, channel: str, seq: int, message: dict) -> None:
        loop = self.loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._deliver, channel, seq, message)

    def _deliver(self, channel: str, seq: int, message: dict) -> None:
        for subscriber in list(self.channels.get(channel, ())):
            subscriber.deliver(seq, message)

    def subscribe(self, channel: str) -> Subscriber:
        subscriber = Subscriber()
        self.channels.setdefault(channel, set()).add(subscriber)
        return subscriber

    def unsubscribe(self, channel: str, subscriber: Subscriber) -> None:
        self.channels.get(channel, set()).discard(subscriber)


# --- the server's state -----------------------------------------------------------------------


class UIServer:
    """Sessions, jobs and the workspace, shared by every request."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.jobs = JobManager()
        self.hub = Hub()
        self.sessions: dict[str, Session] = {}
        self._waiting: dict[str, list[Session]] = {}  # build job id -> sessions
        self._ids = itertools.count(1)
        self._lock = threading.RLock()
        self.jobs.add_listener(self._on_job)

    def info(self) -> AppInfo:
        return AppInfo(
            version=__version__,
            workspace=str(self.workspace.root),
            workspace_name=self.workspace.name,
            python=platform.python_version(),
            platform=sys.platform,
        )

    def _publish(self, session: Session, seq: int, message: dict) -> None:
        self.hub.publish(f"session:{session.id}", seq, message)

    def check(self, spec: RunSpec):
        """``check`` the spec's files, which must be inside the workspace (raises RunError)."""
        for path in (spec.robot, spec.program, spec.field, spec.input):
            if path:
                try:
                    self.workspace.path(path)
                except ValueError as exc:
                    raise RunError(str(exc)) from None
        return check(spec, self.workspace.root)

    def start_session(self, request: StartSession) -> Session:
        """Check and start a run (raises RunError if it can't start)."""
        spec = request.spec
        prepared = self.check(spec)
        if request.replace:
            for other in list(self.sessions.values()):
                other.stop()
        session = Session(
            f"s{next(self._ids)}", spec, base=self.workspace.root, listener=self._publish
        )
        with self._lock:
            self.sessions[session.id] = session
        if prepared.project is None:
            threading.Thread(target=session.start, daemon=True).start()
            return session
        project = prepared.project.resolve()
        job = self.submit_build(project)
        session.building()
        with self._lock:
            self._waiting.setdefault(job.id, []).append(session)
            session.sync_build_log(job.log)
            finished = not job.active
        if finished:
            self._job_done(job)
        return session

    def submit_build(self, project: Path):
        """Build a PROS project (or join its build already running)."""
        title, key = f"Build {project.name}", f"build:{project}"
        return self.jobs.submit("build", {"project": str(project)}, title=title, key=key)

    def _on_job(self, event: str, job, line) -> None:
        if event == "log":
            with self._lock:
                for session in self._waiting.get(job.id, ()):
                    session.sync_build_log(job.log)
        elif event == "state" and not job.active:
            self._job_done(job)

    def _job_done(self, job) -> None:
        with self._lock:
            sessions = self._waiting.pop(job.id, [])
        for session in sessions:
            session.sync_build_log(job.log)
            if job.state == "succeeded":
                executable = job.result["executable"]
                threading.Thread(target=session.start, args=(executable,), daemon=True).start()
            else:
                session.fail(job.error or f"the build was {job.state}")

    def stop_session(self, session: Session) -> None:
        session.stop()

    def shutdown(self) -> None:
        for session in list(self.sessions.values()):
            session.stop()
        self.jobs.shutdown()


# --- who may talk to the server -----------------------------------------------------------


_UNAUTHORIZED = """<!doctype html><meta charset="utf-8"><title>vexsim</title>
<body style="font-family: system-ui, sans-serif; margin: 3em; max-width: 36em">
<h1>This page needs its key</h1>
<p>Open vexsim with the link <code>vexsim ui</code> printed when it started: it ends with
<code>?token=...</code>. If you closed that terminal, run <code>vexsim ui</code> again.</p>
"""


class Guard:
    """ASGI middleware: the right Host, a valid token (URL, cookie or bearer header), and,
    for WebSockets, an Origin of our own. A token in the URL is traded for a cookie."""

    def __init__(self, app, *, token: str, cookie: str, hosts: set[str], origins: set[str]):
        self.app = app
        self.token = token
        self.cookie = cookie
        self.hosts = hosts
        self.origins = origins

    def _valid(self, value: str | None) -> bool:
        return bool(value) and secrets.compare_digest(value.encode(), self.token.encode())

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        if headers.get("host", "") not in self.hosts:
            return await self._deny(scope, receive, send, 403, "wrong host")
        if scope["type"] == "websocket":
            origin = headers.get("origin")
            if origin is not None and origin not in self.origins:
                return await self._deny(scope, receive, send, 403, "wrong origin")
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        from_url = (query.get("token") or [None])[0]
        cookies = SimpleCookie()
        with contextlib.suppress(Exception):
            cookies.load(headers.get("cookie", ""))
        from_cookie = cookies[self.cookie].value if self.cookie in cookies else None
        bearer = headers.get("authorization", "")
        from_header = bearer[7:] if bearer.lower().startswith("bearer ") else None
        if not any(self._valid(v) for v in (from_cookie, from_header, from_url)):
            return await self._deny(scope, receive, send, 401, "no valid token")
        if scope["type"] == "http" and self._valid(from_url) and not self._valid(from_cookie):
            send = self._setting_cookie(send)
        await self.app(scope, receive, send)

    def _setting_cookie(self, send):
        async def wrapped(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append(
                    "set-cookie",
                    f"{self.cookie}={self.token}; Path=/; HttpOnly; SameSite=Strict",
                )
            await send(message)

        return wrapped

    async def _deny(self, scope, receive, send, status: int, reason: str):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4000 + status, "reason": reason})
            return
        wants_page = "text/html" in Headers(scope=scope).get("accept", "")
        if wants_page and status == 401:
            response: Response = HTMLResponse(_UNAUTHORIZED, status_code=status)
        else:
            response = JSONResponse({"detail": reason}, status_code=status)
        await response(scope, receive, send)


# --- the app ----------------------------------------------------------------------------------


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

    app = FastAPI(title="vexsim", version=__version__, lifespan=lifespan, docs_url=None)
    app.state.server = server

    @app.get("/api/info")
    def info() -> AppInfo:
        return server.info()

    @app.get("/api/workspace")
    def workspace_items() -> WorkspaceInfo:
        ws = server.workspace
        items = [item.to_dict() for item in ws.scan()]
        return WorkspaceInfo(root=str(ws.root), name=ws.name, items=items)

    def _problem(exc: RunError) -> JSONResponse:
        issues = [
            {"severity": i.severity, "location": i.location, "message": i.message}
            for i in exc.issues
        ]
        problem = RunProblem(error=exc.message, issues=issues)
        return JSONResponse(problem.model_dump(), status_code=422)

    @app.post("/api/preview", responses={422: {"model": RunProblem}})
    def preview(request: PreviewRequest):
        """The robot and field before a run: the field view, and drag-to-start."""
        try:
            prepared = server.check(RunSpec(robot=request.robot, field=request.field))
        except RunError as exc:
            return _problem(exc)
        field = prepared.field or FieldConfig()
        return Preview.model_validate(preview_of(prepared.config, field))

    @app.get("/api/configurations")
    def configurations() -> RunConfigurations:
        try:
            found = read_configurations(server.workspace.root)
        except LaunchFileError as exc:
            return RunConfigurations(file=LAUNCH_FILE, configurations=[], error=str(exc))
        return RunConfigurations(file=LAUNCH_FILE, configurations=found)

    @app.put("/api/configurations", responses={409: {}, 422: {}})
    def save_configurations(request: SaveConfigurations):
        root = server.workspace.root
        try:
            read_configurations(root)
        except LaunchFileError as exc:  # never overwrite a file that may hold someone's work
            return JSONResponse({"detail": f"{exc} (fix the file first)"}, status_code=409)
        try:
            write_configurations(root, request.configurations)
        except LaunchFileError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        except OSError as exc:
            return JSONResponse({"detail": f"can't save {LAUNCH_FILE}: {exc}"}, status_code=500)
        return RunConfigurations(file=LAUNCH_FILE, configurations=read_configurations(root))

    @app.post("/api/sessions", responses={422: {"model": RunProblem}})
    def start_session(request: StartSession):
        try:
            session = server.start_session(request)
        except RunError as exc:
            return _problem(exc)
        return SessionInfo.model_validate(session.info())

    @app.get("/api/sessions")
    def sessions() -> list[SessionInfo]:
        return [SessionInfo.model_validate(s.info()) for s in server.sessions.values()]

    def _session(session_id: str) -> Session:
        session = server.sessions.get(session_id)
        if session is None:
            from fastapi import HTTPException

            raise HTTPException(404, f"no session {session_id}")
        return session

    @app.get("/api/sessions/{session_id}")
    def session_info(session_id: str) -> SessionInfo:
        return SessionInfo.model_validate(_session(session_id).info())

    @app.delete("/api/sessions/{session_id}", status_code=204)
    def stop_session(session_id: str) -> Response:
        server.stop_session(_session(session_id))
        return Response(status_code=204)

    @app.websocket("/api/sessions/{session_id}/ws")
    async def session_socket(websocket: WebSocket, session_id: str):
        session = server.sessions.get(session_id)
        if session is None:
            await websocket.close(code=4404, reason=f"no session {session_id}")
            return
        await websocket.accept()
        channel = f"session:{session_id}"
        subscriber = server.hub.subscribe(channel)
        catch_up, subscriber.floor = session.catch_up()
        for message in catch_up:
            subscriber.push(message)

        async def send_messages():
            while True:
                await websocket.send_text(dumps(await subscriber.next()))

        sender = asyncio.create_task(send_messages())
        try:
            while True:
                data = await websocket.receive_json()
                try:
                    command = _COMMANDS.validate_python(data)
                except ValidationError as exc:
                    problem = {"type": "error", "message": f"bad command: {exc.errors()[0]['msg']}"}
                    subscriber.push({**problem, "issues": [], "traceback": None})
                    continue
                await run_in_threadpool(session.command, command.model_dump())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sender.cancel()
            server.hub.unsubscribe(channel, subscriber)

    @app.post("/api/jobs")
    def start_job(request: StartJob) -> JobInfo:
        try:
            project = server.workspace.path(request.project)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        if not (project / "project.pros").is_file() and not (project / "src").is_dir():
            return JSONResponse({"detail": f"{request.project} isn't a PROS project"}, 422)
        return JobInfo.model_validate(server.submit_build(project).to_dict())

    @app.get("/api/jobs")
    def jobs() -> list[JobInfo]:
        return [JobInfo.model_validate(j.to_dict(since=len(j.log))) for j in server.jobs.list()]

    def _job(job_id: str):
        job = server.jobs.get(job_id)
        if job is None:
            from fastapi import HTTPException

            raise HTTPException(404, f"no job {job_id}")
        return job

    @app.get("/api/jobs/{job_id}")
    def job_info(job_id: str, since: int = 0) -> JobInfo:
        return JobInfo.model_validate(_job(job_id).to_dict(since=max(0, since)))

    @app.delete("/api/jobs/{job_id}")
    def cancel_job(job_id: str) -> JobInfo:
        job = _job(job_id)
        server.jobs.cancel(job)
        return JobInfo.model_validate(job.to_dict(since=len(job.log)))

    if (STATIC / "index.html").is_file():
        app.mount("/", StaticFiles(directory=STATIC, html=True), name="app")
    else:

        @app.get("/")
        def not_built() -> HTMLResponse:
            return HTMLResponse(
                "<!doctype html><title>vexsim</title><p>The browser app isn't built: run "
                "<code>npm ci && npm run build</code> in <code>frontend/</code>.</p>"
            )

    hosts = hosts or {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = origins or {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    app.add_middleware(
        Guard, token=token, cookie=f"vexsim_token_{port}", hosts=hosts, origins=origins
    )
    return app


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
    token: str | None = None,
    dev: bool = False,
) -> None:
    """Run the UI for ``folder`` until Ctrl+C."""
    import uvicorn

    workspace = Path(folder).resolve()
    token = token or secrets.token_urlsafe(24)
    sock = _listen(port)
    actual = sock.getsockname()[1]
    origins = {f"http://127.0.0.1:{actual}", f"http://localhost:{actual}"}
    if dev:
        origins |= set(DEV_ORIGINS)
    app = create_app(workspace, token=token, port=actual, origins=origins)
    url = f"http://127.0.0.1:{actual}/?token={token}"
    print(f"vexsim UI for {workspace}")
    print(f"  {url}")
    print("Keep this window open while you use it; press Ctrl+C to stop.", flush=True)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    config = uvicorn.Config(app, log_level="warning", lifespan="on", ws="auto")
    uvicorn.Server(config).run(sockets=[sock])

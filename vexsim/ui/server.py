"""The UI's server: the service layer over HTTP and WebSockets, plus the built app.

``vexsim ui [folder]`` runs ``serve``: a FastAPI app on 127.0.0.1 that serves the browser
app from ``static/`` and an API under ``/api``:

- ``GET /api/info``, ``GET /api/workspace``: about the server and what's in the folder
- ``POST /api/sessions`` (``StartSession``): start a run; 422 with a ``RunProblem`` if it
  can't. ``GET /api/sessions[/{id}]``, ``DELETE /api/sessions/{id}`` (stop)
- ``WS /api/sessions/{id}/ws``: the session's messages (``ServerMessage``) out, commands
  (``ClientCommand``) in
- ``POST /api/jobs`` (``StartJob``: a build, a benchmark, a sweep, ...),
  ``GET /api/jobs[/{id}?since=n&items_since=k]``, ``DELETE /api/jobs/{id}`` (cancel)
- ``GET /api/results/{kind}[/{id}[/files/{path}]]``, ``DELETE /api/results/{kind}/{id}``:
  what benchmarks, sweeps and calibrations found
- ``GET``/``PUT /api/configurations`` and ``/api/sweeps``: the saved runs and sweeps
- ``GET``/``PUT /api/config``, ``POST /api/config/{check,patch,overrides}``: the editors

The server can build and run code, so every request needs the random token ``serve``
prints (in the URL once, then in a cookie), the Host header must be this server, and
WebSockets must come from its own pages.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import platform
import secrets
import socket
import sys
import threading
import webbrowser
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders

from vexsim import __version__
from vexsim.app import configs, results, runs
from vexsim.app.benchmarks import ScenarioProblem, describe_scenario
from vexsim.app.frames import preview_of
from vexsim.app.jobs import JobManager
from vexsim.app.jsonsafe import dumps
from vexsim.app.launch import (
    LAUNCH_FILE,
    LaunchFileError,
    read_configurations,
    write_configurations,
)
from vexsim.app.runspec import RunError, RunSpec, check
from vexsim.app.session import Session
from vexsim.app.sweeps import SWEEPS_FILE, SweepError, expand, read_sweeps, write_sweeps
from vexsim.app.workspace import Workspace
from vexsim.config.field import FieldConfig
from vexsim.config.robot import RobotConfig
from vexsim.ui.protocol import (
    AppInfo,
    CalibrationSetup,
    ClientCommand,
    ConfigCheck,
    ConfigCheckRequest,
    ConfigFile,
    ConfigOverridesRequest,
    ConfigPatched,
    ConfigPatchRequest,
    ConfigSave,
    ConfigSaved,
    JobInfo,
    PlacedIssue,
    Preview,
    PreviewRequest,
    ReplayRequest,
    ResultAbout,
    ResultReplayRequest,
    RoutinePlan,
    RoutineRequest,
    RunConfigurations,
    RunDetails,
    RunProblem,
    RunRecord,
    RunUpdate,
    SaveConfigurations,
    SaveSweeps,
    ScenarioInfo,
    SessionInfo,
    StartJob,
    StartSession,
    SweepsFile,
    TextSpan,
    WorkspaceInfo,
)

STATIC = Path(__file__).parent / "static"
JSON = "application/json"
FILE_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".png": "image/png",
    ".csv": "text/csv; charset=utf-8",
    ".yaml": "text/yaml; charset=utf-8",
    ".json": JSON,
}
DEFAULT_PORT = 8642
DEV_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")  # Vite's dev server
_COMMANDS = TypeAdapter(ClientCommand)
_JOBS = TypeAdapter(StartJob)
_FRAME = object()  # a frame is waiting in a Subscriber


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
        self.saving = threading.Lock()  # one config save at a time
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
            f"s{next(self._ids)}",
            spec,
            base=self.workspace.root,
            listener=self._publish,
            name=request.name,
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

    def submit_build(self, project: Path, debug: bool = False):
        """Build a PROS project (or join its build already running)."""
        title, key = f"Build {project.name}" + (" (debug)" if debug else ""), f"build:{project}"
        params = {"project": str(project), "debug": debug}
        return self.jobs.submit("build", params, title=title, key=key)

    def submit_job(self, request):
        """Start a job the browser asked for (a ``StartJob``), its workspace paths checked
        and made absolute. Raises ValueError (or RunError, ScenarioProblem, SweepError)
        when it can't start."""
        ws, kind = self.workspace, request.kind
        root = str(ws.root)
        if kind == "build":
            project = ws.path(request.project)
            if not (project / "project.pros").is_file() and not (project / "src").is_dir():
                raise ValueError(f"{request.project} isn't a PROS project")
            return self.submit_build(project, request.debug)
        if kind == "doctor":
            return self.jobs.submit("doctor", {}, title="Check the compiler", key="doctor")
        params = request.model_dump(exclude={"kind"})
        if kind == "motor_curves":
            title = f"Motor curves: {request.cartridge} at {request.supply_voltage:g} V"
            return self.jobs.submit(kind, params, title=title)
        if kind in ("drift", "odometry"):
            robot = self.robot_file(request.robot)
            params.update(robot=str(robot), robot_name=request.robot)
            title = f"{'Drift' if kind == 'drift' else 'Odometry'}: {robot.name}"
            return self.jobs.submit(kind, params, title=title)
        if kind == "bench":
            scenario = ws.path(request.scenario)
            info = describe_scenario(scenario, ws.root)  # fails early on a broken one
            store = results.results_root(ws.root, "bench")
            params.update(scenario=str(scenario), root=root, results=str(store))
            return self.jobs.submit(kind, params, title=f"Bench: {info['name']}")
        if kind == "calibrate":
            robot, log = self.robot_file(request.robot), ws.path(request.log)
            if not log.is_file():
                raise ValueError(f"{request.log} doesn't exist")
            store = results.results_root(ws.root, "calibrations")
            params.update(
                robot=str(robot),
                robot_name=request.robot,
                log=str(log),
                log_name=request.log,
                results=str(store),
            )
            return self.jobs.submit(kind, params, title=f"Calibrate: {log.name}")
        if kind == "sweep":
            expand(request.sweep, read_configurations(ws.root))  # fails early on a bad one
            store = results.results_root(ws.root, "sweeps")
            params.update(root=root, results=str(store))
            return self.jobs.submit(kind, params, title=f"Sweep: {request.sweep.name}")
        raise ValueError(f"unknown job kind {kind}")

    def robot_file(self, relative: str) -> Path:
        """A robot config in the workspace (raises ValueError if it isn't one)."""
        path = self.workspace.path(relative)
        if not path.is_file():
            raise ValueError(f"{relative} doesn't exist")
        return path

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


def _checked(checked: configs.CheckedConfig) -> ConfigCheck:
    """A checked config as the protocol has it."""

    def span(place: configs.Span | None) -> TextSpan | None:
        if place is None:
            return None
        return TextSpan(
            line=place.line,
            column=place.column,
            end_line=place.end_line,
            end_column=place.end_column,
        )

    config = checked.config
    return ConfigCheck(
        issues=[
            PlacedIssue(
                severity=issue.severity,
                location=issue.location,
                message=issue.message,
                span=span(issue.span),
            )
            for issue in checked.issues
        ],
        robot=config if isinstance(config, RobotConfig) else None,
        field=config if isinstance(config, FieldConfig) else None,
        summary=checked.summary,
        places={item: span(place) for item, place in checked.places.items()},
    )


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

    # --- robot and field configs, for the editors ------------------------------------------

    def _config_file(relative: str) -> Path:
        path = server.workspace.path(relative)
        if path.suffix.lower() not in (".yaml", ".yml"):
            raise ValueError(f"{relative} isn't a YAML file")
        return path

    @app.get("/api/config", responses={400: {}, 404: {}, 422: {}})
    def open_config(path: str):
        """A robot or field config to edit (``ConfigFile``), checked."""
        try:
            file = _config_file(path)
            read = configs.read_config(file)
        except FileNotFoundError:
            return JSONResponse({"detail": f"{path} doesn't exist"}, status_code=404)
        except UnicodeDecodeError:
            return JSONResponse({"detail": f"{path} isn't UTF-8 text"}, status_code=422)
        except (OSError, ValueError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        kind = configs.kind_of(read.text)
        if kind is None:
            detail = f"{path} isn't a robot or field config"
            return JSONResponse({"detail": detail}, status_code=422)
        return ConfigFile(
            path=server.workspace.relative(file),
            kind=kind,
            text=read.text,
            version=read.version,
            check=_checked(configs.check_text(read.text, kind)),
        )

    @app.post("/api/config/check")
    def check_config(request: ConfigCheckRequest) -> ConfigCheck:
        """A config's text as it's being typed, checked."""
        return _checked(configs.check_text(request.text, request.kind))

    @app.post("/api/config/patch", responses={422: {}})
    def patch_config(request: ConfigPatchRequest):
        """Numbers changed in place in a config's text (a drag on the editor's diagram)."""
        edits = [configs.Edit(e.location, e.value) for e in request.edits]
        try:
            text = configs.patch_text(request.text, edits)
        except configs.PatchError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return ConfigPatched(text=text, check=_checked(configs.check_text(text, request.kind)))

    @app.post("/api/config/overrides", responses={422: {}})
    def config_overrides(request: ConfigOverridesRequest):
        """Fitted values set under a robot config's ``overrides``, in its text."""
        try:
            text = configs.set_overrides(request.text, request.values)
        except configs.PatchError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return ConfigPatched(text=text, check=_checked(configs.check_text(text, "robot")))

    @app.put("/api/config", responses={400: {}, 404: {}, 409: {}})
    def save_config(request: ConfigSave):
        """Write a config, in its own line endings; refused (409, with the version on disk)
        if it changed since it was opened."""
        try:
            file = _config_file(request.path)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        with server.saving:
            try:
                current = configs.read_config(file)
            except FileNotFoundError:
                detail = f"{request.path} doesn't exist any more"
                return JSONResponse({"detail": detail}, status_code=404)
            except (OSError, UnicodeDecodeError) as exc:
                return JSONResponse({"detail": str(exc)}, status_code=400)
            if request.version is not None and request.version != current.version:
                detail = f"{request.path} changed on disk since you opened it"
                return JSONResponse({"detail": detail, "version": current.version}, status_code=409)
            try:
                version = configs.write_config(file, request.text, current)
            except OSError as exc:
                return JSONResponse(
                    {"detail": f"can't save {request.path}: {exc}"}, status_code=500
                )
        return ConfigSaved(version=version)

    # --- recorded runs (.vexsim/runs) ------------------------------------------------------

    def _runs_root() -> Path:
        return runs.runs_root(server.workspace.root)

    def _missing(run_id: str) -> JSONResponse:
        return JSONResponse({"detail": f"no run {run_id}"}, status_code=404)

    @app.get("/api/runs")
    def list_runs() -> list[RunRecord]:
        return runs.list_runs(_runs_root())

    @app.get("/api/runs/{run_id}", responses={404: {}})
    def run_details(run_id: str):
        try:
            record = runs.read_record(_runs_root(), run_id)
        except (OSError, ValueError):
            return _missing(run_id)
        return RunDetails(run=record, console=runs.read_console(_runs_root(), run_id))

    @app.patch("/api/runs/{run_id}", responses={404: {}})
    def update_run(run_id: str, update: RunUpdate):
        try:
            return runs.update_record(_runs_root(), run_id, kept=update.kept, name=update.name)
        except (OSError, ValueError):
            return _missing(run_id)

    @app.delete("/api/runs/{run_id}", status_code=204, responses={404: {}})
    def delete_run(run_id: str) -> Response:
        try:
            runs.delete_run(_runs_root(), run_id)
        except (OSError, ValueError):
            return _missing(run_id)
        return Response(status_code=204)

    @app.get("/api/runs/{run_id}/tape", responses={404: {}})
    def run_tape(run_id: str) -> Response:
        """The run to scrub (``Tape``), passed through from its file unchecked: it's big."""
        try:
            tape = runs.read_tape(_runs_root(), run_id)
        except (OSError, ValueError):
            return _missing(run_id)
        return Response(dumps(tape), media_type="application/json")

    @app.get("/api/runs/{run_id}/telemetry", responses={404: {}})
    def run_telemetry(run_id: str) -> Response:
        """The run's telemetry for plots (``Telemetry``)."""
        try:
            columns = runs.telemetry_columns(runs.telemetry_path(_runs_root(), run_id))
        except (OSError, ValueError):
            return _missing(run_id)
        return Response(dumps(columns), media_type="application/json")

    @app.get("/api/runs/{run_id}/telemetry.csv", responses={404: {}})
    def run_csv(run_id: str) -> Response:
        """The 10 ms telemetry log, as ``vexsim run --record`` writes it."""
        import gzip

        try:
            path = runs.telemetry_path(_runs_root(), run_id)
            text = gzip.decompress(path.read_bytes()).decode("utf-8")
        except (OSError, ValueError):
            return _missing(run_id)
        name = f"{run_id}.csv"
        return PlainTextResponse(
            text,
            media_type="text/csv",
            headers={"content-disposition": f'attachment; filename="{name}"'},
        )

    @app.post("/api/replay", responses={422: {"model": RunProblem}})
    def replay(request: ReplayRequest) -> Response:
        """A telemetry log from the workspace as a tape (``Replay``), drawn with a robot."""
        try:
            prepared = server.check(RunSpec(robot=request.robot, field=request.field))
            log = server.workspace.path(request.log)
            result = runs.replay_of(
                log, prepared.config, prepared.field or FieldConfig(), request.robot, request.log
            )
        except RunError as exc:
            return _problem(exc)
        except (OSError, ValueError) as exc:
            return JSONResponse(RunProblem(error=str(exc), issues=[]).model_dump(), 422)
        return Response(dumps(result), media_type="application/json")

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

    @app.post("/api/jobs", responses={422: {}})
    async def start_job(request: Request):
        """Start a job (``StartJob``); 422 with a ``detail`` (and ``issues``) if it can't."""
        try:
            wanted = _JOBS.validate_python(await request.json())
        except ValidationError as exc:
            error = exc.errors()[0]
            where = ".".join(str(part) for part in error["loc"])
            detail = f"{where}: {error['msg']}" if where else error["msg"]
            return JSONResponse({"detail": detail}, status_code=422)
        try:
            job = await run_in_threadpool(server.submit_job, wanted)
        except RunError as exc:
            return _problem(exc)
        except ScenarioProblem as exc:
            return _problem(RunError(str(exc), exc.issues))
        except (ValueError, OSError, LaunchFileError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return JobInfo.model_validate(job.to_dict())

    @app.get("/api/jobs")
    def jobs() -> list[JobInfo]:
        return [JobInfo.model_validate(j.to_dict(brief=True)) for j in server.jobs.list()]

    def _job(job_id: str):
        job = server.jobs.get(job_id)
        if job is None:
            from fastapi import HTTPException

            raise HTTPException(404, f"no job {job_id}")
        return job

    @app.get("/api/jobs/{job_id}")
    def job_info(job_id: str, since: int = 0, items_since: int = 0) -> Response:
        job = _job(job_id)
        return Response(dumps(job.to_dict(max(0, since), max(0, items_since))), media_type=JSON)

    @app.delete("/api/jobs/{job_id}")
    def cancel_job(job_id: str) -> JobInfo:
        job = _job(job_id)
        server.jobs.cancel(job)
        return JobInfo.model_validate(job.to_dict(brief=True))

    # --- what the long jobs found (.vexsim/bench, sweeps, calibrations) ------------------

    def _results_root(kind: str) -> Path:
        if kind not in results.KINDS:
            from fastapi import HTTPException

            raise HTTPException(404, f"no results of kind {kind}")
        return results.results_root(server.workspace.root, kind)

    def _no_result(kind: str, result_id: str) -> JSONResponse:
        return JSONResponse({"detail": f"no {kind} result {result_id}"}, status_code=404)

    @app.get("/api/results/{kind}")
    def list_results(kind: str) -> list[ResultAbout]:
        return [ResultAbout.model_validate(a) for a in results.list_results(_results_root(kind))]

    @app.get("/api/results/{kind}/{result_id}", responses={404: {}})
    def read_result(kind: str, result_id: str) -> Response:
        """A ``BenchResult``, ``SweepResult`` or ``CalibrationResult``."""
        try:
            data = results.read_result(_results_root(kind), result_id)
        except (OSError, ValueError):
            return _no_result(kind, result_id)
        return Response(dumps(data), media_type=JSON)

    @app.delete("/api/results/{kind}/{result_id}", status_code=204, responses={404: {}})
    def delete_result(kind: str, result_id: str) -> Response:
        try:
            results.delete_result(_results_root(kind), result_id)
        except (OSError, ValueError):
            return _no_result(kind, result_id)
        return Response(status_code=204)

    @app.get("/api/results/{kind}/{result_id}/files/{name:path}", responses={404: {}})
    def result_file(kind: str, result_id: str, name: str) -> Response:
        """A file a job wrote: a benchmark's report.html and its charts, CSVs, ..."""
        try:
            path = results.result_file(_results_root(kind), result_id, name)
        except (OSError, ValueError):
            return JSONResponse({"detail": f"no file {name} in {result_id}"}, status_code=404)
        media = FILE_TYPES.get(path.suffix.lower(), "application/octet-stream")
        headers = {"Content-Security-Policy": "sandbox"}  # a report is a page of its own
        if path.suffix.lower() in (".csv", ".yaml"):
            headers["Content-Disposition"] = f'attachment; filename="{path.name}"'
        return FileResponse(path, media_type=media, headers=headers)

    @app.post("/api/results/bench/{result_id}/replay", responses={404: {}, 422: {}})
    def bench_replay(result_id: str, request: ResultReplayRequest) -> Response:
        """A benchmark's worst case on the field, drawn with its scenario's robot and field."""
        store = _results_root("bench")
        try:
            data = results.read_result(store, result_id)
            log = results.result_file(store, result_id, request.file)
        except (OSError, ValueError):
            return JSONResponse({"detail": f"no file {request.file} in {result_id}"}, 404)
        scenario = data["scenario"]
        ws = server.workspace
        inside = ws.root in log.parents
        try:
            prepared = server.check(RunSpec(robot=scenario["robot"], field=scenario["field"]))
            result = runs.replay_of(
                log,
                prepared.config,
                prepared.field or FieldConfig(),
                scenario["robot"],
                ws.relative(log) if inside else str(log),
            )
        except RunError as exc:
            return _problem(exc)
        except (OSError, ValueError) as exc:
            return JSONResponse(RunProblem(error=str(exc), issues=[]).model_dump(), 422)
        for worst in data.get("worst", []):
            if worst["file"] == request.file:
                result["name"] = (
                    f"{scenario['name']}: the worst of {worst['localizer']} / "
                    f"{worst['controller']} (seed {worst['seed']})"
                )
        return Response(dumps(result), media_type=JSON)

    # --- benchmark scenarios, sweeps, calibration ------------------------------------------

    @app.get("/api/bench/scenario", responses={422: {"model": RunProblem}})
    def scenario_info(path: str):
        """A scenario, described for the Bench page (``ScenarioInfo``)."""
        try:
            info = describe_scenario(server.workspace.path(path), server.workspace.root)
        except ScenarioProblem as exc:
            return _problem(RunError(str(exc), exc.issues))
        except (OSError, ValueError) as exc:
            return JSONResponse(RunProblem(error=str(exc), issues=[]).model_dump(), 422)
        return ScenarioInfo.model_validate(info)

    @app.get("/api/sweeps")
    def sweeps() -> SweepsFile:
        try:
            found = read_sweeps(server.workspace.root)
        except SweepError as exc:
            return SweepsFile(file=SWEEPS_FILE, sweeps=[], error=str(exc))
        return SweepsFile(file=SWEEPS_FILE, sweeps=found)

    @app.put("/api/sweeps", responses={409: {}, 422: {}})
    def save_sweeps(request: SaveSweeps):
        root = server.workspace.root
        try:
            read_sweeps(root)
        except SweepError as exc:  # never overwrite a file that may hold someone's work
            return JSONResponse({"detail": f"{exc} (fix the file first)"}, status_code=409)
        try:
            write_sweeps(root, request.sweeps)
        except SweepError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        except OSError as exc:
            return JSONResponse({"detail": f"can't save {SWEEPS_FILE}: {exc}"}, status_code=500)
        return SweepsFile(file=SWEEPS_FILE, sweeps=read_sweeps(root))

    def _robot_config(path: str) -> RobotConfig:
        prepared = server.check(RunSpec(robot=path))  # raises RunError
        return prepared.config

    @app.get("/api/calibrate/parameters", responses={422: {"model": RunProblem}})
    def calibration_setup(robot: str):
        """The parameters a fit adjusts unless told otherwise, with their values now."""
        from vexsim.app.calibrate import parameters

        try:
            config = _robot_config(robot)
        except RunError as exc:
            return _problem(exc)
        return CalibrationSetup(robot=robot, parameters=parameters(config))

    @app.post("/api/calibrate/routine", responses={422: {"model": RunProblem}})
    def calibration_routine(request: RoutineRequest):
        """The calibration routine in a PROS project: what adding it does, or (``write``)
        adding it."""
        from vexsim.app.calibrate import routine_plan, write_routine

        try:
            config = _robot_config(request.robot)
            project = server.workspace.path(request.project)
            if not (project / "project.pros").is_file() and not (project / "src").is_dir():
                raise ValueError(f"{request.project} isn't a PROS project")
            root = server.workspace.root
            plan = (write_routine if request.write else routine_plan)(config, project, root)
        except RunError as exc:
            return _problem(exc)
        except (OSError, ValueError) as exc:
            return JSONResponse(RunProblem(error=str(exc), issues=[]).model_dump(), 422)
        return RoutinePlan.model_validate(plan)

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

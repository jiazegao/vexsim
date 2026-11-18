"""The server's state: its workspace, its live runs and jobs, the pages that have it open, and
the watch it keeps on a run's files."""

from __future__ import annotations

import contextlib
import hashlib
import itertools
import platform
import sys
import threading
import time
from pathlib import Path

from vexsim import __version__
from vexsim.app import results
from vexsim.app.benchmarks import describe_scenario
from vexsim.app.jobs import JobManager
from vexsim.app.launch import read_configurations
from vexsim.app.runfiles import run_files
from vexsim.app.runspec import RunError, RunSpec, check
from vexsim.app.session import Session
from vexsim.app.sweeps import expand
from vexsim.app.workspace import Workspace
from vexsim.ui.protocol import AppInfo, StartSession
from vexsim.ui.server.hub import Hub

WATCH_S = 0.5  # how often a run's files are looked at, while a page shows it


class Pages:
    """The app's pages open on this server: each holds a presence socket while it's open."""

    def __init__(self) -> None:
        self.open = 0
        self.ever = False  # whether a page has opened yet
        self._since = time.monotonic()  # when the last page closed (or the server started)
        self._lock = threading.Lock()

    def opened(self) -> None:
        with self._lock:
            self.open += 1
            self.ever = True

    def closed(self) -> None:
        with self._lock:
            self.open -= 1
            if self.open == 0:
                self._since = time.monotonic()

    def idle_for(self) -> float | None:
        """Seconds with no page open; None while one is."""
        with self._lock:
            return None if self.open else time.monotonic() - self._since


class UIServer:
    """Sessions, jobs and the workspace, shared by every request."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.pages = Pages()
        self.jobs = JobManager()
        self.hub = Hub()
        self.sessions: dict[str, Session] = {}
        self._waiting: dict[str, list[Session]] = {}  # build job id -> sessions
        self._ids = itertools.count(1)
        self._lock = threading.RLock()
        self._closing = threading.Event()
        self._watcher: threading.Thread | None = None  # looks at watched runs' files
        self.saving = threading.Lock()  # one config save at a time
        self.jobs.add_listener(self._on_job)

    def info(self) -> AppInfo:
        return AppInfo(
            version=__version__,
            workspace=str(self.workspace.root),
            workspace_name=self.workspace.name,
            python=platform.python_version(),
            platform=sys.platform,
            pages=self.pages.open,
        )

    def _publish(self, session: Session, seq: int, message: dict) -> None:
        self.hub.publish(f"session:{session.id}", seq, message)

    def check(self, spec: RunSpec):
        """``check`` the spec's files, which must be inside the workspace (raises RunError)."""
        follow = spec.follow.log if spec.follow else None
        for path in (spec.robot, spec.program, spec.route, spec.field, spec.input, follow):
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
        session.watching(run_files(prepared))  # as they are before the program is read
        with self._lock:
            self.sessions[session.id] = session
        self._watch()
        if prepared.project is None:
            threading.Thread(target=session.start, daemon=True).start()
            return session
        project = prepared.project.resolve()
        route = list(prepared.route.route.functions) if prepared.route is not None else None
        job = self.submit_build(project, route=route)
        session.building()
        with self._lock:
            self._waiting.setdefault(job.id, []).append(session)
            session.sync_build_log(job.log)
            finished = not job.active
        if finished:
            self._job_done(job)
        return session

    def restart_session(self, session: Session) -> Session:
        """The session's run from the start, with its code as it is now; the session that
        runs it. If none of its files has changed since it started, that's the session
        itself, at once, in its own worker. Otherwise the run is checked, built and started
        afresh, as a new session in its place (raises RunError if it can't be: the old one
        stays as it is)."""
        if session.state in ("building", "starting") and not session.stopped:
            return session  # on its way already
        if session.fresh() and session.command({"cmd": "restart"}):
            return session
        return self.start_session(StartSession(spec=session.spec, name=session.name))

    def _watch(self) -> None:
        """Start looking at the files of the runs on show, now and then (once)."""
        with self._lock:
            if self._watcher is None:
                self._watcher = threading.Thread(
                    target=self._look, name="vexsim-watch", daemon=True
                )
                self._watcher.start()

    def _look(self) -> None:
        while not self._closing.wait(WATCH_S):
            for session in list(self.sessions.values()):
                if self.hub.listening(f"session:{session.id}"):  # a page shows it
                    with contextlib.suppress(Exception):
                        session.look()

    def submit_build(self, project: Path, debug: bool = False, route: list[str] | None = None):
        """Build a PROS project (or join its build already running); ``route``: a route
        build, with the team's functions from these headers."""
        title, key = f"Build {project.name}" + (" (debug)" if debug else ""), f"build:{project}"
        params = {"project": str(project), "debug": debug}
        if route is not None:
            title += " for a route"
            key += ":route:" + "|".join(route)
            params["route"] = route
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
        if kind == "route":
            route = ws.path(request.route)
            if not route.is_file():
                raise ValueError(f"{request.route} doesn't exist")
            params.update(route=ws.relative(route), root=root)
            title = f"Route: {route.name}"
            text = hashlib.blake2b((request.text or "").encode(), digest_size=8).hexdigest()
            key = f"route:{route}:{request.seed}:{request.noise}:{text}"  # the same run, joined
            return self.jobs.submit(kind, params, title=title, key=key)
        if kind.startswith("calibration_"):
            return self.submit_calibration(request, params)
        raise ValueError(f"unknown job kind {kind}")

    def submit_calibration(self, request, params: dict):
        """A calibration session's jobs (``vexsim.app.calsession``), their files checked."""
        ws, kind = self.workspace, request.kind
        root = str(ws.root)

        def folder(relative: str) -> Path:
            path = ws.path(relative)
            if path == ws.root or path.is_file():
                raise ValueError(f"{relative} isn't a folder of its own")
            return path

        if kind == "calibration_program":
            target = folder(request.folder)
            params.update(
                robot=str(self.robot_file(request.robot)),
                field=str(self.robot_file(request.field)),
                folder=str(target),
                root=root,
            )
            title = f"Plan and write the calibration program: {target.name}"
            return self.jobs.submit(kind, params, title=title, key=f"{kind}:{target}")
        if kind == "calibration_practice":
            session = folder(request.session)
            params.update(
                robot=str(self.robot_file(request.robot)),
                field=str(self.robot_file(request.field)),
                program=str(folder(request.program)),
                session=str(session),
            )
            title = f"Practice in vexsim: {session.name}"
            return self.jobs.submit(kind, params, title=title, key=f"{kind}:{session}")
        if kind == "calibration_usb":
            session = folder(request.session)
            params.update(session=str(session))
            title = f"Collect over USB: {session.name}"
            return self.jobs.submit(kind, params, title=title, key=kind)  # one port, one listener
        if kind == "calibration_fit":
            session = folder(request.session)
            params.update(
                robot=str(self.robot_file(request.robot)),
                robot_name=request.robot,
                session=str(session),
                field=str(self.robot_file(request.field)) if request.field else None,
            )
            title = f"Fit the session: {session.name}"
            return self.jobs.submit(kind, params, title=title, key=f"{kind}:{session}")
        if kind == "calibration_check":
            if len(request.ends) != len(request.logs):
                raise ValueError("give where each run ended: two corners' tape marks per log")
            logs = [self.robot_file(log) for log in request.logs]
            program = folder(request.program)
            params.update(
                robot=str(self.robot_file(request.robot)),
                robot_name=request.robot,
                field=str(self.robot_file(request.field)),
                field_name=request.field,
                program=str(program),
                program_name=request.program,
                logs=[str(log) for log in logs],
                log_names=list(request.logs),
                root=root,
                results=str(results.results_root(ws.root, "checks")),
            )
            title = f"Autonomous check: {', '.join(log.name for log in logs)}"
            return self.jobs.submit(kind, params, title=title)
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
        self._closing.set()
        for session in list(self.sessions.values()):
            session.stop()
        self.jobs.shutdown()

"""One live simulation, seen from the server: its worker process, its state, its messages.

A session waits for its program's build when the program is a PROS project ("building"),
then starts a worker process (``vexsim.app.worker``) and relays everything the worker
says to ``listener(session, message)``. It also keeps what a viewer that connects late
needs: the latest scene, overlay, frame and status, what the robot code has drawn, where a
run that follows a log began to, the build log and the console's last lines (``catch_up``).

A session knows the files its run was made from (``watch``, ``vexsim.app.runfiles``) and
what they were when it started (``stamp``). ``look``, called now and then while someone is
watching, says when they've changed since (a ``changed`` message), and ``fresh`` says
whether the worker's run is still the code on disk.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from vexsim.app.runfiles import RunFiles, Stamp, changed
from vexsim.app.runspec import RunSpec

CONSOLE_LINES = 2000
# a worker in one of these states starts its run again by itself ("restart")
RESTARTABLE = ("running", "paused", "finished")

# listener(session, seq, message): every message, numbered in order (see ``catch_up``)
Listener = Callable[["Session", int, dict], None]


class Session:
    def __init__(
        self,
        session_id: str,
        spec: RunSpec,
        *,
        base: str | Path | None = None,
        listener: Listener | None = None,
        name: str | None = None,
    ):
        self.id = session_id
        self.spec = spec
        self.base = None if base is None else str(base)  # the workspace; runs record there
        self.name = name  # what to call its recorded runs
        self.listener = listener
        self.created = time.time()
        self.state = "starting"
        self.message: str | None = None
        self.mode = ""
        self.scene: dict | None = None
        self.overlay: dict | None = None
        self.drawings: dict | None = None  # what the robot code has drawn, as last sent
        self.following: dict | None = None  # where a run that follows a log began to
        self.frame: dict | None = None
        self.error: dict | None = None
        self.build_log: list[str] = []
        self.console: deque[str] = deque(maxlen=CONSOLE_LINES)
        self.child = None
        self.run_id: str | None = None  # where its current (or last) run is recorded
        self.seq = 0  # number of the last message published
        self.watch: RunFiles | None = None  # the files its run was made from
        self.stamp: Stamp = {}  # what they were when it started
        self.changed: list[str] = []  # the ones that have changed since, as last told
        self._looked: Stamp = {}  # what they were at the last look
        self._told: Stamp = {}  # what they were when viewers were last told
        self._lock = threading.RLock()
        self._stopped = False

    # --- what viewers see ------------------------------------------------------------------

    def info(self) -> dict:
        return {
            "id": self.id,
            "spec": self.spec.model_dump(mode="json"),
            "command": self.spec.command_line(),
            "state": self.state,
            "message": self.message,
            "mode": self.mode,
            "created": self.created,
            "run_id": self.run_id,
        }

    def catch_up(self) -> tuple[list[dict], int]:
        """Messages that bring a newly connected viewer up to date, oldest first, and the
        number of the last message they cover: skip published messages up to it."""
        with self._lock:
            messages: list[dict] = [{"type": "session", "session": self.info()}]
            if self.build_log:
                messages.append({"type": "build", "lines": list(self.build_log)})
            if self.scene is not None:
                messages.append(self.scene)
            if self.overlay is not None:
                messages.append(self.overlay)
            if self.drawings is not None:
                messages.append(self.drawings)
            if self.following is not None:
                messages.append(self.following)
            if self.console:
                messages.append({"type": "console", "lines": list(self.console)})
            if self.error is not None:
                messages.append(self.error)
            if self.frame is not None:
                messages.append(self.frame)
            if self.changed:
                messages.append({"type": "changed", "files": list(self.changed)})
            messages.append(
                {"type": "status", "state": self.state, "message": self.message, "mode": self.mode}
            )
            return messages, self.seq

    def _publish(self, message: dict) -> None:
        """Number and pass on a message (with the lock held, so numbers follow the state)."""
        with self._lock:
            self.seq += 1
            if self.listener is not None:
                try:
                    self.listener(self, self.seq, message)
                except Exception:
                    pass

    def _set_state(self, state: str, message: str | None = None) -> None:
        with self._lock:
            self.state, self.message = state, message
            self._publish({"type": "status", "state": state, "message": message, "mode": self.mode})

    # --- its files -------------------------------------------------------------------------

    def watching(self, files: RunFiles) -> None:
        """The files this run is made from, as they are now (before any of them is read)."""
        with self._lock:
            self.watch = files
            self.stamp = files.stamp()
            self._looked = self._told = self.stamp

    def fresh(self) -> bool:
        """Whether the run in the worker is still the one on disk, and the worker can start
        it again by itself: none of its files has changed since it started."""
        with self._lock:
            if self._stopped or self.child is None or self.state not in RESTARTABLE:
                return False
            watch, stamp = self.watch, self.stamp
        return watch is not None and watch.stamp() == stamp

    def look(self) -> None:
        """Tell the viewers when the run's files have changed since it started (``changed``:
        the files, as the workspace names them), once they've stopped changing: an editor
        saves in steps, and a file half written isn't one to build."""
        with self._lock:
            watch = self.watch
        if watch is None:
            return
        now = watch.stamp()
        with self._lock:
            if now != self._looked:  # still being written
                self._looked = now
                return
            if now == self._told:
                return
            self._told = now
            self.changed = [self._name(path) for path in changed(self.stamp, now)]
            self._publish({"type": "changed", "files": list(self.changed)})

    def _name(self, path: str) -> str:
        """A file as the workspace names it (relative, with /), or as it is outside it."""
        if self.base is not None:
            try:
                return Path(path).relative_to(self.base).as_posix()
            except ValueError:
                pass
        return path

    def _sources(self, files: list[str]) -> None:
        """Python files the worker's program imported: they're the run's too."""
        with self._lock:
            if self.watch is None:
                return
            new = self.watch.add(files)
            marks = RunFiles(new).stamp()
            # as they are now: the worker read them a moment ago
            self.stamp = {**self.stamp, **marks}
            self._looked = {**self._looked, **marks}
            self._told = {**self._told, **marks}

    # --- building --------------------------------------------------------------------------

    def building(self) -> None:
        """The program is being built (see ``sync_build_log``)."""
        self._set_state("building")

    def sync_build_log(self, log: list[str]) -> None:
        """Catch up with the build's log (all of it so far; lines already seen are skipped)."""
        with self._lock:
            new = log[len(self.build_log) :]
            if new:
                self.build_log.extend(new)
                self._publish({"type": "build", "lines": list(new)})

    def fail(self, message: str, issues: list[dict] | None = None) -> None:
        """The session can't run (its build failed, say)."""
        error = {"type": "error", "message": message, "issues": issues or [], "traceback": None}
        with self._lock:
            self.error = error
            self._publish(error)
            self._set_state("error", message)

    # --- running ---------------------------------------------------------------------------

    def start(self, executable: str | None = None) -> None:
        """Start the worker process (blocks briefly while it starts)."""
        from vexsim.app.child import ChildError, ChildProcess

        with self._lock:
            if self._stopped or self.child is not None:
                return
        arguments = {
            "spec": self.spec.model_dump(mode="json"),
            "base": self.base,
            "executable": None if executable is None else str(executable),
            "name": self.name,
        }
        try:
            child = ChildProcess(
                "vexsim.app.worker:run_worker", arguments, on_output=self._output, cwd=self.base
            )
        except (ChildError, OSError) as exc:
            self.fail(str(exc))
            return
        with self._lock:
            if self._stopped:  # stopped while starting
                child.send({"cmd": "stop"})
                child.close()
                return
            self.child = child
        threading.Thread(target=self._read, name=f"vexsim-{self.id}", daemon=True).start()

    def _output(self, line: str) -> None:
        """What the worker process printed outside the robot program's console."""
        self._receive({"type": "console", "lines": [line]})

    def _read(self) -> None:
        child = self.child
        while True:
            try:
                message = child.recv()
            except (EOFError, OSError):
                break
            self._receive(message)
        with self._lock:
            ended = not self._stopped and self.state not in ("stopped",)
        if ended:  # the worker died on its own
            code = child.wait(5)
            self._set_state("error", f"the simulation's process stopped (exit code {code})")

    def _receive(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "sources":  # for the session, not its viewers
            self._sources(message.get("files", []))
            return
        with self._lock:
            if kind == "status":
                self.state, self.message = message["state"], message.get("message")
                self.mode = message.get("mode") or self.mode
            elif kind == "scene":  # a run begins: nothing of the one before is left
                self.scene, self.overlay, self.frame, self.error = message, None, None, None
                self.drawings = self.following = None
                self.console.clear()
                self.run_id = message.get("run_id")
            elif kind == "frame":
                self.frame = message
            elif kind == "overlay":
                self.overlay = message
            elif kind == "drawings":
                self.drawings = message
            elif kind == "following":
                self.following = message
            elif kind == "console":
                self.console.extend(message["lines"])
            elif kind == "error":
                self.error = message
            self._publish(message)

    def command(self, command: dict) -> bool:
        """Send a command to the worker; False if it isn't running."""
        child = self.child
        if child is None:
            return False
        try:
            child.send(command)
        except (OSError, EOFError):
            return False
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the simulation and its process (idempotent)."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            child = self.child
        if child is not None:
            try:
                child.send({"cmd": "stop"})
            except (OSError, EOFError):
                pass
            child.close(timeout)
        with self._lock:
            already = self.state == "stopped"
        if not already:
            self._set_state("stopped")

    @property
    def stopped(self) -> bool:
        return self._stopped

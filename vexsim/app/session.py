"""One live simulation, seen from the server: its worker process, its state, its messages.

A session waits for its program's build when the program is a PROS project ("building"),
then starts a worker process (``vexsim.app.worker``) and relays everything the worker
says to ``listener(session, message)``. It also keeps what a viewer that connects late
needs: the latest scene, overlay, frame and status, the build log and the console's last
lines (``catch_up``).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from vexsim.app.runspec import RunSpec

CONSOLE_LINES = 2000

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
    ):
        self.id = session_id
        self.spec = spec
        self.base = None if base is None else str(base)
        self.listener = listener
        self.created = time.time()
        self.state = "starting"
        self.message: str | None = None
        self.mode = ""
        self.scene: dict | None = None
        self.overlay: dict | None = None
        self.frame: dict | None = None
        self.error: dict | None = None
        self.build_log: list[str] = []
        self.console: deque[str] = deque(maxlen=CONSOLE_LINES)
        self.child = None
        self.seq = 0  # number of the last message published
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
            if self.console:
                messages.append({"type": "console", "lines": list(self.console)})
            if self.error is not None:
                messages.append(self.error)
            if self.frame is not None:
                messages.append(self.frame)
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
        with self._lock:
            if kind == "status":
                self.state, self.message = message["state"], message.get("message")
                self.mode = message.get("mode") or self.mode
            elif kind == "scene":
                self.scene, self.overlay, self.frame, self.error = message, None, None, None
                self.console.clear()
            elif kind == "frame":
                self.frame = message
            elif kind == "overlay":
                self.overlay = message
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

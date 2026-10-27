"""The process behind a live simulation: it paces simulated time and streams what happens.

``run_worker`` runs in its own process (``vexsim.app.child``). It gets the run ready (see
``vexsim.app.runspec``), then loops: apply the commands that arrived, advance simulated
time by real time x speed, and about 60 times a second send a frame. Messages out are
dicts with a ``type``:

- ``status``: ``state`` (starting, running, paused, finished, error, stopped), ``message``
- ``scene``: the robot and field (``vexsim.app.frames.scene_of``), after every (re)start
- ``frame``: where everything is (``frame_of``)
- ``overlay``: a Python chassis motion's path and target, when they change
- ``console``: new lines of program output
- ``error``: ``message``, config ``issues``, ``traceback``

Commands in are dicts with a ``cmd``: pause, resume, step (``ms``), speed (``value``; 0
or less = as fast as possible), restart, input (``analog``, ``digital``), stop.
"""

from __future__ import annotations

import io
import math
import sys
import time
import traceback
from collections import deque
from typing import Any

FRAME_S = 1 / 60
MAX_LAG_S = 0.25  # simulate at most this much per frame; slower than that, fall behind
MAX_STEP_MS = 60_000


class RemoteInput:
    """Controller input from the UI (keyboard, gamepad, on-screen controller)."""

    def __init__(self) -> None:
        self.analog: dict[str, float] = {}
        self.digital: set[str] = set()

    def set(self, analog: dict[str, float], digital) -> None:
        self.analog = {str(k): float(v) for k, v in analog.items()}
        self.digital = {str(b) for b in digital}

    def poll(self, time_s: float) -> tuple[dict[str, float], set[str]]:
        return dict(self.analog), set(self.digital)


class _ConsoleStream(io.TextIOBase):
    """sys.stdout/stderr for the robot program: whole lines go to the UI's console."""

    def __init__(self, emit) -> None:
        self._emit = emit
        self._partial = ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        lines = (self._partial + text).split("\n")
        self._partial = lines.pop()
        if lines:
            self._emit(lines)
        return len(text)

    def flush(self) -> None:
        if self._partial:
            self._emit([self._partial])
            self._partial = ""


class Worker:
    def __init__(self, conn, spec: dict, base: str | None, executable: str | None):
        self.conn = conn
        self.spec_data = spec
        self.base = base
        self.executable = executable
        self.sim = None
        self.factory = None
        self.mode = ""
        self.input = None
        self.state = "starting"
        self.speed: float = 1.0  # math.inf: as fast as possible
        self.stopping = False
        self.console_sent = 0
        self.overlay_key: Any = None
        self.warnings: list[str] = []  # about the start, for the console
        self.debt = 0.0  # simulated seconds owed to real time
        self.rate_samples: deque[tuple[float, float]] = deque(maxlen=90)

    # --- messages --------------------------------------------------------------------------

    def send(self, message: dict) -> None:
        try:
            self.conn.send(message)
        except (OSError, EOFError):
            self.stopping = True  # the server is gone

    def status(self, state: str, message: str | None = None) -> None:
        self.state = state
        self.send({"type": "status", "state": state, "message": message, "mode": self.mode})
        if state in ("paused", "finished", "error"):
            self.send_frame()  # exactly where it stopped

    def error(self, message: str, *, issues=(), trace: str | None = None) -> None:
        self.send(
            {
                "type": "error",
                "message": message,
                "issues": [
                    {"severity": i.severity, "location": i.location, "message": i.message}
                    for i in issues
                ],
                "traceback": trace,
            }
        )
        self.status("error", message)

    def console(self, lines: list[str]) -> None:
        if lines:
            self.send({"type": "console", "lines": [str(line) for line in lines]})

    # --- getting ready ---------------------------------------------------------------------

    def prepare(self) -> bool:
        from vexsim.app.runspec import (
            RunError,
            RunSpec,
            check,
            program_factory,
            simulation_factory,
        )
        from vexsim.runtime.simulation import ScriptedInput

        try:
            spec = RunSpec.model_validate(self.spec_data)
            prepared = check(spec, self.base)
            make_program, self.mode = program_factory(prepared, self.executable)
            if prepared.spec.input:
                self.input = ScriptedInput.from_csv(prepared.spec.input)
            else:
                self.input = RemoteInput()
            self.factory = simulation_factory(
                prepared, make_program, self.mode, input_source=self.input, echo=None
            )
        except RunError as exc:
            self.error(exc.message, issues=exc.issues)
            return False
        except Exception as exc:  # the robot program failed to import, say
            self.error(f"{type(exc).__name__}: {exc}", trace=traceback.format_exc())
            return False
        self.command_line = spec.command_line()
        self.warnings = [
            f"warning: {w.message}" for w in prepared.warnings if w.location == "start"
        ]
        return True

    def create(self) -> bool:
        """A fresh simulation from the start; False if it failed (reported)."""
        from vexsim.app.frames import scene_of

        self.close_sim()
        self.console_sent = 0
        self.overlay_key = None
        self.debt = 0.0
        self.rate_samples.clear()
        try:
            self.sim = self.factory()
        except Exception as exc:
            self.sim = None
            self.error(f"{type(exc).__name__}: {exc}", trace=traceback.format_exc())
            return False
        self.send(
            scene_of(self.sim, mode=self.mode, spec=self.spec_data, command=self.command_line)
        )
        self.console(self.warnings)
        self.status("running")
        self.send_frame()
        return True

    def close_sim(self) -> None:
        if self.sim is not None:
            try:
                self.sim.close()
            except Exception:
                pass
            self.sim = None

    # --- the loop --------------------------------------------------------------------------

    def run(self) -> None:
        if self.prepare():
            self.create()
        next_frame = time.perf_counter()
        last = next_frame
        while not self.stopping:
            if self.state != "running":
                timeout = 0.5  # idle: wait for a command
            elif math.isinf(self.speed):
                timeout = 0.0
            else:
                timeout = max(0.0, next_frame - time.perf_counter())
            try:
                while self.conn.poll(timeout):
                    self.handle(self.conn.recv())
                    timeout = 0.0
                    if self.stopping:
                        break
            except (EOFError, OSError):
                break  # the server is gone
            now = time.perf_counter()
            wall_dt, last = now - last, now
            if self.state != "running":
                next_frame = now
                continue
            self.advance(wall_dt)
            if self.state == "running" and time.perf_counter() >= next_frame:
                self.send_frame()
                next_frame = max(next_frame + FRAME_S, time.perf_counter())
        self.close_sim()
        self.status("stopped")

    def advance(self, wall_dt: float) -> None:
        """Simulate the time real time owes (x speed), at most MAX_LAG_S of it."""
        if math.isinf(self.speed):
            deadline = time.perf_counter() + FRAME_S * 0.8
            while self.state == "running" and time.perf_counter() < deadline:
                self.step(10)
            return
        self.debt = min(self.debt + wall_dt * self.speed, MAX_LAG_S)
        steps = int(self.debt * 1000)
        if steps:
            self.debt -= steps / 1000
            self.step(steps)

    def step(self, ms: int) -> None:
        """Advance ``ms`` simulated milliseconds, stopping at the end of the program."""
        from vexsim.bridge.host import HostError

        sim = self.sim
        if sim is None:
            return
        try:
            for _ in range(ms):
                sim.world.step()
                if sim.finished:
                    break
        except HostError as exc:
            self.flush_console()
            self.error(str(exc))
            return
        except Exception as exc:
            self.flush_console()
            self.error(f"{type(exc).__name__}: {exc}", trace=traceback.format_exc())
            return
        if sim.finished and self.state in ("running", "paused"):
            self.flush_console()
            self.status("finished", f"{sim.mode} finished at {sim.world.time:.2f} s")

    def flush_console(self) -> None:
        sim = self.sim
        if sim is not None and len(sim.console) > self.console_sent:
            self.console(sim.console[self.console_sent :])
            self.console_sent = len(sim.console)

    def send_frame(self) -> None:
        from vexsim.app.frames import frame_of, overlay_of

        sim = self.sim
        if sim is None:
            return
        self.flush_console()
        now = time.perf_counter()
        self.rate_samples.append((now, sim.world.time))
        (w0, t0), (w1, t1) = self.rate_samples[0], self.rate_samples[-1]
        rate = (t1 - t0) / (w1 - w0) if w1 - w0 > 0.05 else 0.0
        speed = None if math.isinf(self.speed) else self.speed
        self.send(frame_of(sim, state=self.state, speed=speed, rate=rate))
        overlay = overlay_of(sim)
        key = (overlay["path"] and len(overlay["path"]), overlay["target"])
        if key != self.overlay_key:
            self.overlay_key = key
            self.send(overlay)

    # --- commands --------------------------------------------------------------------------

    def handle(self, command: dict) -> None:
        cmd = command.get("cmd")
        if cmd == "stop":
            self.stopping = True
        elif cmd == "pause" and self.state == "running":
            self.status("paused")
        elif cmd == "resume" and self.state == "paused":
            self.debt = 0.0
            self.status("running")
        elif cmd == "step" and self.state == "paused":
            self.step(max(1, min(int(command.get("ms", 10)), MAX_STEP_MS)))
            self.send_frame()
        elif cmd == "speed":
            value = float(command.get("value", 1.0))
            self.speed = math.inf if value <= 0 else value
            self.send_frame()
        elif cmd == "restart" and self.factory is not None:
            self.create()
        elif cmd == "input" and hasattr(self.input, "set"):
            self.input.set(command.get("analog", {}), command.get("digital", ()))


def run_worker(conn, spec: dict, base: str | None = None, executable: str | None = None) -> None:
    """Run one live simulation until told to stop (see the module docstring)."""
    worker = Worker(conn, spec, base, executable)
    stream = _ConsoleStream(worker.console)
    sys.stdout = sys.stderr = stream  # a Python program's print() goes to the console
    try:
        worker.run()
    finally:
        stream.flush()

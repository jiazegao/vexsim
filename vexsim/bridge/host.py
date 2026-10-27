"""The robot host process and its line protocol (see cpp/runtime/host.cpp).

``RobotHost`` starts a ``vexsim build`` executable and talks to it over its
stdin/stdout. Each ``run(now_us, lines)`` sends sensor readings and a RUN
command; the host runs every due PROS task until all of them are blocked
again and replies with motor commands, console text and the next time it
needs to run. Simulated time never moves while robot code runs.
"""

from __future__ import annotations

import os
import subprocess
import weakref
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from vexsim.bridge.build import NO_CONSOLE


class HostError(RuntimeError):
    """The robot code crashed or hung, or the host process died."""

    def __init__(self, message: str, console: list[str] | None = None):
        self.console = list(console or [])
        tail = "\n".join(f"  | {line}" for line in self.console[-10:])
        super().__init__(f"{message}\nlast console lines:\n{tail}" if tail else message)


@dataclass
class Reply:
    """What the robot code did during one run."""

    commands: list[list[str]] = field(default_factory=list)  # M / B / L / I lines, split
    console: list[str] = field(default_factory=list)  # output and "vexsim: " warnings, in order
    warnings: list[str] = field(default_factory=list)
    lcd: dict[int, str] = field(default_factory=dict)
    controller_screen: dict[int, str] = field(default_factory=dict)
    pose: tuple[float, float, float] | None = None  # last vexsim::report_pose (LemLib convention)
    drawings: list[str] = field(default_factory=list)  # vexsim::draw_* commands, in order
    finished: list[int] = field(
        default_factory=list
    )  # serials of competition functions that returned
    next_wake_us: int | None = None


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
        proc.wait()
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        if stream is not None:
            stream.close()


class RobotHost:
    def __init__(
        self,
        executable: str | Path,
        devices: list[tuple[int, str, str]],
        *,
        spin_calls_per_ms: int = 1000,
        busy_timeout_s: float = 5.0,
        env: dict[str, str] | None = None,
    ):
        """``devices``: (port, kind, detail) with kind motor/imu/rotation/distance and,
        for motors, the cartridge name as detail. ``env`` adds environment variables
        the robot code can read with getenv()."""
        self.executable = Path(executable)
        if not self.executable.is_file():
            raise HostError(f"robot host not found: {self.executable} (run `vexsim build` first)")
        self.console_tail: deque[str] = deque(maxlen=50)
        try:
            self.proc = subprocess.Popen(
                [str(self.executable)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, **env} if env else None,
                creationflags=NO_CONSOLE,
            )
        except OSError as exc:
            raise HostError(f"cannot start the robot host {self.executable}: {exc}") from exc
        self._finalizer = weakref.finalize(self, _kill, self.proc)
        lines = [f"INIT {int(spin_calls_per_ms)} {round(busy_timeout_s * 1000)}"]
        lines += [f"DEV {port} {kind} {detail}".rstrip() for port, kind, detail in devices]
        lines.append("GO")
        self._send(lines)
        self.startup = self._read_reply(until="READY")

    # --- protocol ---------------------------------------------------------------------------

    def run(self, now_us: int, lines: list[str] | None = None) -> Reply:
        """Send readings/mode lines, run robot code at ``now_us``, return what it did."""
        self._send([*(lines or []), f"RUN {int(now_us)}"])
        return self._read_reply(until="W")

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self._send(["STOP"])
                self.proc.wait(timeout=2)
            except (OSError, HostError, subprocess.TimeoutExpired):
                pass
        self._finalizer()

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def _send(self, lines: list[str]) -> None:
        data = ("\n".join(lines) + "\n").encode("utf-8")
        try:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()
        except OSError:
            self._died()

    def _read_reply(self, until: str) -> Reply:
        reply = Reply()
        while True:
            raw = self.proc.stdout.readline()
            if not raw:
                self._died()
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            verb, _, rest = line.partition(" ")
            if verb == until:
                if verb == "W":
                    reply.next_wake_us = None if rest.strip() == "-1" else int(rest)
                return reply
            if verb == "T":
                reply.console.append(rest)
                self.console_tail.append(rest)
            elif verb in ("M", "B", "L", "I"):
                reply.commands.append(line.split())
            elif verb == "E":
                reply.warnings.append(rest)
                reply.console.append(f"vexsim: {rest}")
                self.console_tail.append(f"vexsim: {rest}")
            elif verb == "P":
                x, y, theta = (float(v) for v in rest.split())
                reply.pose = (x, y, theta)
            elif verb == "D":
                reply.drawings.append(rest)
            elif verb == "F":
                reply.finished.append(int(rest))
            elif verb in ("LCD", "CTRL"):
                number, _, text = rest.partition(" ")
                target = reply.lcd if verb == "LCD" else reply.controller_screen
                target[int(number)] = text
            elif verb == "BUSY":
                task, _, seconds = rest.partition("\t")
                self._finalizer()
                raise HostError(
                    f"robot code hung: task {task!r} ran for {seconds} s of real time without "
                    "calling pros::delay() or any other PROS function (an infinite loop without a "
                    "delay?). On the robot this would starve every other task.",
                    list(self.console_tail),
                )
            elif verb == "CRASH":
                task, _, what = rest.partition("\t")
                self._finalizer()
                raise HostError(
                    f"robot code crashed in task {task!r}: {what}", list(self.console_tail)
                )
            else:  # not protocol: treat as console text
                reply.console.append(line)
                self.console_tail.append(line)

    def _died(self) -> None:
        try:
            code = self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            code = None
        stderr = b""
        try:
            stderr = self.proc.stderr.read() or b""
        except (OSError, ValueError):
            pass
        console = [*self.console_tail, *stderr.decode("utf-8", errors="replace").splitlines()]
        self._finalizer()
        raise HostError(f"the robot host exited unexpectedly (exit code {code})", console)

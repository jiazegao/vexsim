"""A function from vexsim running in a fresh Python process, connected by a pipe.

Jobs and live simulations run this way, so a crash, a hang or a cancel can't take the UI
down, and nothing (environment variables, imported robot programs) leaks between runs.

The child (``python -m vexsim.app.child``) opens a connection listener, prints its
address on stdout, and waits; the parent connects with a random key it passed in the
environment, then sends the function to call and its keyword arguments. From then on
both sides exchange messages over the connection, and whatever the child writes to
stdout or stderr (a Python program's ``print()``, say) reaches the parent's ``on_output``.

Unlike ``multiprocessing``'s spawn, this never re-runs the parent's main script, and the
child exits by itself if the parent dies: it watches its stdin for the end, or on Windows,
where a thread blocked reading a pipe can stall other calls on it, the parent's process (the
child's stdin is empty there).

``VEXSIM_CHILD_DUMP_S=N`` makes a child print where each of its threads is after N seconds,
for finding where one is stuck.
"""

from __future__ import annotations

import importlib
import os
import secrets
import subprocess
import sys
import threading
from collections.abc import Callable
from multiprocessing.connection import Client, Connection, Listener
from pathlib import Path

ADDRESS_PREFIX = "VEXSIM-CHILD-ADDRESS "
AUTHKEY_ENV = "VEXSIM_CHILD_AUTHKEY"
PARENT_ENV = "VEXSIM_CHILD_PARENT"
DUMP_ENV = "VEXSIM_CHILD_DUMP_S"
START_TIMEOUT_S = 60.0  # a fresh Python on a busy Windows machine can take a while
WINDOWS = sys.platform == "win32"


class ChildError(RuntimeError):
    """The child process didn't start."""


class ChildProcess:
    """``function`` ("module:name") running in its own process as ``function(conn, **kwargs)``."""

    def __init__(
        self,
        function: str,
        kwargs: dict | None = None,
        *,
        on_output: Callable[[str], None] | None = None,
        cwd: str | os.PathLike[str] | None = None,
    ):
        key = secrets.token_bytes(32)
        env = dict(os.environ)
        env[AUTHKEY_ENV] = key.hex()
        env[PARENT_ENV] = str(os.getpid())
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        here = str(Path(__file__).resolve().parents[2])  # the folder vexsim is in
        env["PYTHONPATH"] = os.pathsep.join(p for p in (here, env.get("PYTHONPATH")) if p)
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-m", "vexsim.app.child"],
            stdin=subprocess.DEVNULL if WINDOWS else subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        stdout = self.process.stdout
        assert stdout is not None
        early: list[str] = []
        found: list[str] = []

        def read_address() -> None:
            for line in stdout:
                if line.startswith(ADDRESS_PREFIX):
                    found.append(line[len(ADDRESS_PREFIX) :].strip())
                    return
                early.append(line.rstrip("\r\n"))

        starting = threading.Thread(target=read_address, daemon=True)
        starting.start()
        starting.join(START_TIMEOUT_S)  # it may die, or hang, before it says where it is
        if not found:
            self.process.kill()
            self.process.wait()
            output = "\n".join(early[-20:])
            raise ChildError(f"the {function} process didn't start:\n{output}".rstrip())
        address = found[0]
        self._on_output = on_output
        for line in early:
            self._output(line)
        self.conn: Connection = Client(address, authkey=key)
        self._send_lock = threading.Lock()
        self.send((function, dict(kwargs or {})))
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()

    def _output(self, line: str) -> None:
        if self._on_output is not None:
            try:
                self._on_output(line)
            except Exception:
                pass

    def _read_output(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                self._output(line.rstrip("\r\n"))
        except (OSError, ValueError):
            pass

    def send(self, message) -> None:
        """Send a message (thread-safe); raises OSError once the child is gone."""
        with self._send_lock:
            self.conn.send(message)

    def recv(self):
        """The next message; raises EOFError once the child has closed its end."""
        return self.conn.recv()

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def wait(self, timeout: float | None = None) -> int | None:
        """Wait for the process to end; its exit code, or None on timeout."""
        try:
            return self.process.wait(timeout)
        except subprocess.TimeoutExpired:
            return None

    def terminate(self) -> None:
        if self.alive:
            self.process.terminate()

    def kill(self) -> None:
        if self.alive:
            self.process.kill()

    def close(self, timeout: float = 5.0) -> None:
        """Wait for the child to end (killing it after ``timeout``), then free everything."""
        if self.wait(timeout) is None:
            self.kill()
            self.wait(timeout)
        for stream in (self.process.stdin,):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        try:
            self.conn.close()
        except OSError:
            pass
        self._reader.join(timeout)


def _exit_when_orphaned(parent: int) -> None:
    """Exit as soon as the parent is gone: its process ends (Windows), or it closes our
    stdin (elsewhere)."""
    if WINDOWS:
        import _winapi

        try:
            handle = _winapi.OpenProcess(_winapi.SYNCHRONIZE, False, parent)
        except OSError:
            return  # it's gone already, or can't be watched: the closed connection ends us
        _winapi.WaitForSingleObject(handle, _winapi.INFINITE)
    else:
        try:
            sys.stdin.read()
        except (OSError, ValueError):
            pass
    os._exit(3)


def main() -> None:
    dump_after = float(os.environ.get(DUMP_ENV) or 0)
    if dump_after > 0:
        import faulthandler

        faulthandler.dump_traceback_later(dump_after, file=sys.__stderr__)
    key = bytes.fromhex(os.environ.pop(AUTHKEY_ENV))
    parent = int(os.environ.pop(PARENT_ENV, "0") or 0)
    with Listener(authkey=key) as listener:
        print(ADDRESS_PREFIX + str(listener.address), flush=True)
        conn = listener.accept()
    threading.Thread(target=_exit_when_orphaned, args=(parent,), daemon=True).start()
    code = 0
    try:
        function, kwargs = conn.recv()
        module, name = function.split(":")
        getattr(importlib.import_module(module), name)(conn, **kwargs)
    except BaseException:
        import traceback

        traceback.print_exc()
        code = 1
    finally:
        conn.close()
    # End now, without the interpreter's shutdown: that could wait forever on the thread
    # above, which is blocked reading stdin (or waiting for the parent).
    for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__):
        try:
            if stream is not None:
                stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(code)


if __name__ == "__main__":
    main()

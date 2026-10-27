"""Process pools for running simulations in parallel, whose workers end with their parent.

A pool's worker processes outlive a parent that is killed rather than shut down (a
benchmark cancelled in the browser app, say), and would go on simulating for nobody. So
each worker watches the process that made the pool and exits as soon as it's gone.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor

POLL_S = 0.5


def process_pool(workers: int) -> ProcessPoolExecutor:
    """A pool of ``workers`` processes that exit when this process does."""
    return ProcessPoolExecutor(
        max_workers=workers, initializer=_watch_parent, initargs=(os.getpid(),)
    )


def default_workers() -> int:
    """All but one of the computer's cores."""
    return max(1, (os.cpu_count() or 2) - 1)


def _watch_parent(parent: int) -> None:
    threading.Thread(target=_exit_when_gone, args=(parent,), daemon=True).start()


def _exit_when_gone(parent: int) -> None:
    if sys.platform == "win32":
        import _winapi

        try:
            handle = _winapi.OpenProcess(_winapi.SYNCHRONIZE, False, parent)
        except OSError:
            return  # it can't be watched
        _winapi.WaitForSingleObject(handle, _winapi.INFINITE)
    else:
        # A worker is the pool maker's child (fork, spawn) or a fork server's (forkserver):
        # either way it's orphaned once its parent changes or the pool maker is gone.
        first = os.getppid()
        while os.getppid() == first and _alive(parent):
            time.sleep(POLL_S)
    os._exit(3)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

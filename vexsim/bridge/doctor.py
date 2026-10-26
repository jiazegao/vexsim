"""``vexsim doctor``: check that robot code can be compiled and run on this machine."""

from __future__ import annotations

import platform
import sys
from collections.abc import Callable

from vexsim import __version__
from vexsim.bridge.build import BuildError, build_project, cache_root, find_toolchain, install_help
from vexsim.bridge.host import HostError, RobotHost

TEST_PROGRAM = """\
#include "api.h"

extern "C" void initialize(void);  // PROS projects declare this in main.h

// vexsim doctor: two tasks share a counter under a mutex while simulated time advances.
static pros::Mutex counter_mutex;
static int counter = 0;

void initialize() {
	pros::Task worker([] {
		for (int i = 0; i < 3; i++) {
			counter_mutex.take();
			counter++;
			counter_mutex.give();
			pros::delay(10);
		}
	}, "worker");
	pros::delay(50);
	printf("doctor: counter %d at %u ms\\n", counter, (unsigned)pros::millis());
}
"""
EXPECTED = "doctor: counter 3 at 50 ms"


def run_doctor(cxx: str | None = None, log: Callable[[str], None] = print) -> bool:
    log(f"vexsim {__version__}, Python {platform.python_version()} on {platform.platform()}")
    try:
        tc = find_toolchain(cxx)
    except BuildError as exc:
        log(f"[FAIL] compiler   {exc}")
        return False
    log(f"[ ok ] compiler   {tc.cxx}")
    details = f"g++ {tc.version_text}, target {tc.target}, thread model {tc.thread_model}"
    log(f"                  {details}")
    problems = tc.problems()
    if problems:
        for problem in problems:
            log(f"[FAIL] compiler   {problem}")
        log(install_help())
        return False

    project = cache_root() / "doctor-project"
    (project / "src").mkdir(parents=True, exist_ok=True)
    main = project / "src" / "main.cpp"
    if not main.exists() or main.read_text() != TEST_PROGRAM:
        main.write_text(TEST_PROGRAM)
    try:
        result = build_project(project, toolchain=tc)
    except BuildError as exc:
        log(f"[FAIL] build      {exc}")
        return False
    log(f"[ ok ] build      test program compiled and linked in {result.seconds:.1f} s")
    log(f"                  build cache: {cache_root()}")

    try:
        host = RobotHost(result.executable, [], busy_timeout_s=10.0)
        console: list[str] = []
        reply = host.run(0, ["MODE 1 initialize 0"])
        for _ in range(100):
            console += reply.console
            if 1 in reply.finished or reply.next_wake_us is None:
                break
            reply = host.run(reply.next_wake_us)
        host.close()
    except HostError as exc:
        log(f"[FAIL] run        {exc}")
        return False
    if EXPECTED not in console:
        log(f"[FAIL] run        expected {EXPECTED!r}, got {console!r}")
        return False
    log("[ ok ] run        tasks, delays and mutexes run in lockstep with simulated time")
    log("Ready. Build a PROS project with: vexsim build <project folder>")
    return True


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0 if run_doctor() else 1)

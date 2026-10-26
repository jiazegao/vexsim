"""Running PROS 4 C++ robot code in the simulator.

`vexsim build` compiles a PROS project against vexsim's PROS 4 shim headers
into a small host program (``robot_host``). The simulator starts it as a
child process and steps it in lockstep with the physics over pipes; see
``host.py`` for the protocol and ``cpp/runtime`` for the C++ side.
"""

from vexsim.bridge.build import BuildError, BuildResult, build_project, find_toolchain
from vexsim.bridge.host import HostError, RobotHost
from vexsim.bridge.program import CppProgram

__all__ = [
    "BuildError",
    "BuildResult",
    "CppProgram",
    "HostError",
    "RobotHost",
    "build_project",
    "find_toolchain",
]

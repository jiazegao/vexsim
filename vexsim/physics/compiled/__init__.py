"""The physics step, compiled (step.c), for the robots it can take.

The Python step is the model: ``Robot._step_python`` with ``V5Motor.update``,
``Mechanism.advance`` and the rest. step.c copies its arithmetic. This module builds it with
the C compiler beside the g++ vexsim finds, loads it, checks it against the Python step
once on each computer, and gives a robot its compiled step.

A compiled robot's numbers live in one block of doubles that the C reads and writes in
place. The objects that held them (its motors and their thermal models, its power system
and battery, its mechanisms, its wheels' contact state) become views of the block when the
robot first steps: the same classes' methods, their numbers properties over it. So whatever
read or set them still does, and the Python step still runs on them, which is how the two
are compared.

``VEXSIM_STEP`` picks the step: ``python``; ``compiled`` (an error where it can't be had);
``check`` (both, on every step, compared: slow); or, unset, the compiled step wherever
there is one. PLAN.md section 18 has the tolerance the two are held to, and why.

The modules: ``layout`` (where each number lives: the tables step_layout.h is written from,
by ``python -m vexsim.physics.compiled``; a test checks it's current), ``modes`` (which
step), ``lib`` (the library found, built, loaded, checked), ``views`` (the robot's objects
over the block), ``step`` (a robot's compiled step) and ``check`` (the library's own check).
"""

from __future__ import annotations

from vexsim.physics.compiled.check import (
    CHECK_ROBOT,
    self_check,
)
from vexsim.physics.compiled.layout import (
    ARRAYS,
    HEADER,
    MAX_DOF,
    MAX_OCV,
    MAX_WHEELS,
    MECHANISM,
    MOTOR,
    ROBOT,
    SOURCE,
    WHEEL,
    header,
    layout_id,
)
from vexsim.physics.compiled.lib import (
    LIB_NAME,
    Library,
    describe,
    forget,
    library,
    reason,
)
from vexsim.physics.compiled.modes import (
    ENV,
    MODES,
    TOLERANCE,
    StepMismatch,
    StepUnavailable,
    mode,
    use,
)
from vexsim.physics.compiled.step import (
    Compiled,
    engage,
    engaged,
    refused,
    why_not,
)
from vexsim.physics.compiled.views import (
    SharedBattery,
    SharedMechanism,
    SharedMotor,
    SharedPower,
    SharedThermal,
)

__all__ = [
    "MAX_DOF",
    "MAX_WHEELS",
    "MAX_OCV",
    "ROBOT",
    "MOTOR",
    "MECHANISM",
    "WHEEL",
    "ARRAYS",
    "layout_id",
    "header",
    "SOURCE",
    "HEADER",
    "MODES",
    "ENV",
    "TOLERANCE",
    "StepUnavailable",
    "StepMismatch",
    "mode",
    "use",
    "LIB_NAME",
    "Library",
    "library",
    "reason",
    "describe",
    "forget",
    "SharedMotor",
    "SharedThermal",
    "SharedPower",
    "SharedBattery",
    "SharedMechanism",
    "why_not",
    "Compiled",
    "engaged",
    "refused",
    "engage",
    "CHECK_ROBOT",
    "self_check",
]

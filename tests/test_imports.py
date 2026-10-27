"""Every public entry point imports on its own, first, in a fresh interpreter."""

import subprocess
import sys

import pytest

MODULES = [
    "vexsim.physics",
    "vexsim.physics.robot",
    "vexsim.physics.params",
    "vexsim.physics.arena",
    "vexsim.config",
    "vexsim.devices.suite",
    "vexsim.algorithms.localization",
    "vexsim.algorithms.control.motions",
    "vexsim.api",
    "vexsim.runtime.simulation",
    "vexsim.bridge.program",
    "vexsim.bench.runner",
    "vexsim.calibration.fit",
    "vexsim.cli",
    "vexsim.app.runspec",
    "vexsim.app.workspace",
    "vexsim.app.jobs",
    "vexsim.app.session",
    "vexsim.ui.protocol",
    "vexsim.ui.server",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_first(module):
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr

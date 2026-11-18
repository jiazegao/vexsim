"""Command-line interface: ``vexsim <command> ...``.

The commands are in a module a group (``analysis``, ``running``, ``projects``, ``bench``,
``calibration``, ``calibrate``, ``app``), each with its part of the parser; ``parser`` puts the
parser together and has ``main``, the ``vexsim`` command.
"""

from __future__ import annotations

from vexsim.cli.analysis import (
    add_analysis,
    cmd_drift,
    cmd_motor_curves,
    cmd_odometry,
    cmd_validate_config,
)
from vexsim.cli.app import (
    _log_when_windowless,
    _ui_error,
    _ui_missing,
    add_app,
    cmd_shortcut,
    cmd_ui,
    cmd_vscode,
)
from vexsim.cli.bench import (
    add_bench,
    cmd_bench,
)
from vexsim.cli.calibrate import (
    _calibrate_session,
    _session_field,
    add_calibrate,
    add_routine,
    cmd_calibrate,
    cmd_calibration_routine,
)
from vexsim.cli.calibration import (
    _load_robot_and_field,
    add_calibration,
    cmd_calibration_check_auton,
    cmd_calibration_collect,
    cmd_calibration_plan,
    cmd_calibration_program,
    cmd_logger_add,
)
from vexsim.cli.common import (
    EXIT_INVALID,
    EXIT_OK,
    _load_config,
    _parse_start,
    _print_issues,
    _print_run_error,
)
from vexsim.cli.parser import (
    build_parser,
    main,
)
from vexsim.cli.projects import (
    add_projects,
    cmd_build,
    cmd_doctor,
    cmd_route,
    cmd_route_export,
    cmd_routines,
)
from vexsim.cli.running import (
    add_logs,
    add_run,
    cmd_plot,
    cmd_replay,
    cmd_run,
)

__all__ = [
    "EXIT_OK",
    "EXIT_INVALID",
    "_print_issues",
    "_print_run_error",
    "_parse_start",
    "_load_config",
    "cmd_validate_config",
    "cmd_motor_curves",
    "cmd_drift",
    "cmd_odometry",
    "add_analysis",
    "cmd_build",
    "cmd_routines",
    "cmd_route",
    "cmd_route_export",
    "cmd_doctor",
    "add_projects",
    "cmd_run",
    "cmd_plot",
    "cmd_replay",
    "add_run",
    "add_logs",
    "cmd_bench",
    "add_bench",
    "build_parser",
    "main",
    "add_routine",
    "add_calibrate",
    "cmd_calibration_routine",
    "_session_field",
    "_calibrate_session",
    "cmd_calibrate",
    "add_calibration",
    "_load_robot_and_field",
    "cmd_calibration_plan",
    "cmd_calibration_program",
    "cmd_logger_add",
    "cmd_calibration_collect",
    "cmd_calibration_check_auton",
    "add_app",
    "cmd_ui",
    "cmd_shortcut",
    "cmd_vscode",
    "_ui_missing",
    "_log_when_windowless",
    "_ui_error",
]

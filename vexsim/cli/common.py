"""What every command uses: the exit codes, how problems are printed, a start pose and a robot
config read from the command line."""

from __future__ import annotations

import argparse

from vexsim.config.issues import ConfigIssue
from vexsim.config.loader import validate_robot

EXIT_OK = 0
EXIT_INVALID = 1


def _print_issues(issues: list[ConfigIssue]) -> None:
    ordered = [i for i in issues if i.severity == "error"] + [
        i for i in issues if i.severity == "warning"
    ]
    for issue in ordered:
        print(f"  {issue.severity:<8} {issue.location or '(document)'}: {issue.message}")


def _print_run_error(exc) -> None:
    """A RunError as ``vexsim run`` reports it: config issues one per line, else the message."""
    if exc.issues:
        _print_issues(exc.issues)
    else:
        print(f"error: {exc.message}")


def _parse_start(text: str):
    from vexsim.algorithms.localization.base import Pose

    try:
        x, y, heading = (float(v) for v in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("--start must be x,y,heading (inches, degrees)") from None
    return Pose(x, y, heading)


def _load_config(path: str):
    report = validate_robot(path)
    if not report.ok or report.config is None:
        _print_issues(report.issues)
        return None
    return report.config

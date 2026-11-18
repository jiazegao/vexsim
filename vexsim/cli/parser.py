"""``vexsim <command> ...``: the parser, made of each group of commands' part, and ``main``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from vexsim import __version__
from vexsim.cli.analysis import add_analysis
from vexsim.cli.app import add_app
from vexsim.cli.bench import add_bench
from vexsim.cli.calibrate import add_calibrate, add_routine
from vexsim.cli.calibration import add_calibration
from vexsim.cli.projects import add_projects
from vexsim.cli.running import add_logs, add_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vexsim",
        description="VEX V5 robot mechanics simulator.",
    )
    parser.add_argument("--version", action="version", version=f"vexsim {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    add_analysis(sub)
    add_run(sub)
    add_projects(sub)
    add_bench(sub)
    add_logs(sub)
    add_routine(sub)
    add_calibration(sub)
    add_calibrate(sub)
    add_app(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Config text (robot names, paths) may contain characters the console code
    # page can't encode; never crash on output.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")

    args = build_parser().parse_args(argv)
    return args.func(args)

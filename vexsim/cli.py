"""Command-line interface: ``vexsim <command> ...``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from vexsim import __version__
from vexsim.config.issues import ConfigIssue
from vexsim.config.loader import validate_field, validate_robot
from vexsim.config.summary import field_summary, robot_summary

EXIT_OK = 0
EXIT_INVALID = 1

ROADMAP = """\
planned commands:
  run       run a scenario with the live viewer          (Phase 5)
  bench     Monte-Carlo algorithm comparison              (Phase 6)
  build     compile a PROS 4 project against the sim      (Phase 7)
  doctor    check the C++ toolchain (MSYS2 on Windows)    (Phase 7)
  replay    replay a logged run                           (Phase 5)
"""


def _print_issues(issues: list[ConfigIssue]) -> None:
    ordered = [i for i in issues if i.severity == "error"] + [
        i for i in issues if i.severity == "warning"
    ]
    for issue in ordered:
        print(f"  {issue.severity:<8} {issue.location or '(document)'}: {issue.message}")


def cmd_validate_config(args: argparse.Namespace) -> int:
    reports = []

    robot = validate_robot(args.robot)
    reports.append(robot)
    print(f"Robot  {robot.source}")
    if robot.config is not None and not args.quiet:
        print("\n".join(robot_summary(robot.config)))
    _print_issues(robot.issues)

    if args.field:
        field = validate_field(args.field)
        reports.append(field)
        print(f"Field  {field.source}")
        if field.config is not None and not args.quiet:
            print("\n".join(field_summary(field.config)))
        _print_issues(field.issues)

    n_err = sum(len(r.errors) for r in reports)
    n_warn = sum(len(r.warnings) for r in reports)
    failed = n_err > 0 or (args.strict and n_warn > 0)
    verdict = "INVALID" if failed else "OK"
    strict_note = " (--strict: warnings count as failures)" if args.strict and n_warn else ""
    print(f"\nResult: {verdict} ({n_err} error(s), {n_warn} warning(s)){strict_note}")
    return EXIT_INVALID if failed else EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vexsim",
        description="VEX V5 robot mechanics simulator.",
        epilog=ROADMAP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"vexsim {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    p = sub.add_parser(
        "validate-config",
        help="check a robot (and optionally field) config and print a summary",
        description="Check a robot config for errors and print what the simulator will build.",
    )
    p.add_argument("robot", help="robot YAML file")
    p.add_argument("--field", help="field YAML file to check as well")
    p.add_argument("--strict", action="store_true", help="treat warnings as failures")
    p.add_argument("-q", "--quiet", action="store_true", help="print only problems and the result")
    p.set_defaults(func=cmd_validate_config)

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


if __name__ == "__main__":
    raise SystemExit(main())

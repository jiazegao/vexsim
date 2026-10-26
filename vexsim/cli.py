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


def cmd_motor_curves(args: argparse.Namespace) -> int:
    from vexsim.viz import motor_curves

    curves = motor_curves.compute(args.cartridge, args.supply_voltage, points=args.points)
    if args.csv:
        sys.stdout.write(motor_curves.to_csv(curves))
    if args.out:
        try:
            path = motor_curves.plot(curves, args.out)
        except ModuleNotFoundError:
            print('error: plotting needs matplotlib; install it with: pip install -e ".[viz]"')
            return EXIT_INVALID
        print(f"wrote {path}")
    return EXIT_OK


def cmd_drift(args: argparse.Namespace) -> int:
    from vexsim.viz import drift

    report = validate_robot(args.robot)
    if not report.ok or report.config is None:
        _print_issues(report.issues)
        return EXIT_INVALID
    try:
        mus = [float(v) for v in args.lateral_mu.split(",")]
    except ValueError:
        print(f"error: --lateral-mu must be comma-separated numbers, got {args.lateral_mu!r}")
        return EXIT_INVALID
    runs = [
        drift.run_arc(report.config, mu, left=args.left, right=args.right, seconds=args.seconds)
        for mu in mus
    ]
    for run in runs:
        x, y = run.true_xy[-1]
        print(
            f"roller friction {run.lateral_mu:g}: ends at ({x:.1f}, {y:.1f}) in, "
            f"drive-encoder odometry off by {run.final_error_in:.1f} in"
        )
    if args.csv:
        sys.stdout.write(drift.to_csv(runs))
    if args.out:
        title = (
            f"Arc at left {args.left:g} / right {args.right:g} of rated speed for "
            f"{args.seconds:g} s: solid = true path, dashed = odometry"
        )
        try:
            path = drift.plot(runs, args.out, title=title)
        except ModuleNotFoundError:
            print('error: plotting needs matplotlib; install it with: pip install -e ".[viz]"')
            return EXIT_INVALID
        print(f"wrote {path}")
    return EXIT_OK


def cmd_odometry(args: argparse.Namespace) -> int:
    from vexsim.algorithms.localization.runner import run_odometry
    from vexsim.viz import odometry

    report = validate_robot(args.robot)
    if not report.ok or report.config is None:
        _print_issues(report.issues)
        return EXIT_INVALID
    run = run_odometry(report.config, args.script, seed=args.seed, noise=args.noise)
    if not run.estimates:
        print("this robot has no sensors any baseline localizer can use")
        return EXIT_INVALID
    noise = args.noise or "configured"
    print(f"{args.script} drive, {noise} sensor noise, seed {args.seed}:")
    width = max(len(name) for name in run.estimates)
    for name in run.estimates:
        position, heading = run.errors(name)
        print(
            f"  {name:<{width}}  final error {position[-1]:6.2f} in {heading[-1]:6.2f} deg"
            f"   worst {position.max():6.2f} in"
        )
    if args.csv:
        sys.stdout.write(odometry.to_csv(run))
    if args.out:
        title = f"Odometry baselines: {args.script} drive, {noise} sensor noise, seed {args.seed}"
        try:
            path = odometry.plot(run, args.out, title=title)
        except ModuleNotFoundError:
            print('error: plotting needs matplotlib; install it with: pip install -e ".[viz]"')
            return EXIT_INVALID
        print(f"wrote {path}")
    return EXIT_OK


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

    p = sub.add_parser(
        "motor-curves",
        help="plot or tabulate a V5 motor's torque/current/power vs. speed",
        description=(
            "Measure the simulated motor on a dynamometer under move_velocity(max) and "
            "move_voltage(12000), and write a plot (--out) and/or CSV (--csv)."
        ),
    )
    p.add_argument("--cartridge", choices=["red", "green", "blue"], default="green")
    p.add_argument(
        "--supply-voltage", type=float, default=12.8, help="battery voltage (default 12.8)"
    )
    p.add_argument("--points", type=int, default=61, help="speed samples (default 61)")
    p.add_argument("--out", help="PNG file to write (needs the viz extra)")
    p.add_argument("--csv", action="store_true", help="print the data as CSV")
    p.set_defaults(func=cmd_motor_curves)

    p = sub.add_parser(
        "drift",
        help="drive an arc and compare the true path with drive-encoder odometry",
        description=(
            "Drive a differential robot with fixed left/right speeds (fractions of rated "
            "speed) for several omni roller friction values. Compare the plot with a video "
            "of your real robot to calibrate wheel.omni.lateral_mu."
        ),
    )
    p.add_argument("robot", help="robot YAML file")
    p.add_argument("--left", type=float, default=1.0, help="left side, fraction of rated speed")
    p.add_argument("--right", type=float, default=0.4, help="right side, fraction of rated speed")
    p.add_argument("--seconds", type=float, default=1.5)
    p.add_argument(
        "--lateral-mu", default="0.4,0.2,0.1", help="up to 3 comma-separated values to compare"
    )
    p.add_argument("--out", help="PNG file to write (needs the viz extra)")
    p.add_argument("--csv", action="store_true", help="print the sampled paths as CSV")
    p.set_defaults(func=cmd_drift)

    p = sub.add_parser(
        "odometry",
        help="drive a scripted path and compare the baseline localizers with the truth",
        description=(
            "Calibrate the IMU, drive a scripted path with the robot's motors, and run every "
            "baseline localizer the robot's sensors allow (drive encoders, tracking wheels, IMU)."
        ),
    )
    p.add_argument("robot", help="robot YAML file")
    p.add_argument("--script", choices=["gentle", "aggressive"], default="aggressive")
    p.add_argument(
        "--noise",
        choices=["ideal", "default", "harsh"],
        help="use this sensor noise preset for every sensor (default: as configured)",
    )
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", help="PNG file to write (needs the viz extra)")
    p.add_argument("--csv", action="store_true", help="print truth and estimates as CSV")
    p.set_defaults(func=cmd_odometry)

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

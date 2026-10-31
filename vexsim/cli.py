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
    if report.config.drivetrain.type != "differential":
        kind = report.config.drivetrain.type
        print(f"error: drift runs need a differential drivetrain, not {kind}")
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
    try:
        run = run_odometry(report.config, args.script, seed=args.seed, noise=args.noise)
    except ValueError as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
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


def cmd_build(args: argparse.Namespace) -> int:
    from vexsim.bridge.build import BuildError, build_project, find_toolchain

    try:
        toolchain = find_toolchain(args.cxx)
        result = build_project(
            args.project, toolchain=toolchain, workers=args.jobs, debug=args.debug, log=print
        )
    except BuildError as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    if not result.linked:
        status = "up to date"
    else:
        status = f"built ({result.compiled} of {result.total} sources compiled)"
    print(f"{status} in {result.seconds:.1f} s")
    print(f"  {result.executable}")
    return EXIT_OK


def cmd_routines(args: argparse.Namespace) -> int:
    from vexsim.bridge.build import is_pros_project
    from vexsim.bridge.routines import AUTON_HEADER, find_routines

    if not is_pros_project(args.project):
        print(f"error: {args.project} is not a PROS project")
        return EXIT_INVALID
    found = find_routines(args.project)
    if found is None:
        print(f"{args.project} has no {AUTON_HEADER}, so no routines")
        return EXIT_OK
    print(f"Routines in {found.header} (vexsim run --routine NAME):")
    width = max((len(r.name) for r in found.routines), default=0) + 2
    for r in found.routines:
        if r.source is None:
            where = "vexsim can't tell which file defines it, so a run can't pick it"
        elif r.start is None:
            where = f"defined in {r.source}"
        else:
            x, y, heading = r.start_pose()
            theta = r.start[2]
            where = f"starts at --start={x:g},{y:g},{heading:g} (setPose {x:g}, {y:g}, {theta:g})"
        print(f"  {r.name:<{width}}{where}")
    if not found.routines:
        print("  (none)")
    for other in found.others:
        print(f"Not a routine: {other.name}() (line {other.line}) {other.why}")
    return EXIT_OK


def cmd_route(args: argparse.Namespace) -> int:
    """``vexsim route check|run FILE``: a route read and checked, or run headless."""
    from vexsim.app.routes import label, load_route, run_route
    from vexsim.app.runspec import RunError

    checked = load_route(args.file)
    route = checked.route
    if route is None or checked.errors:
        print(f"Route  {args.file}")
        _print_issues(checked.issues)
        return EXIT_INVALID
    if args.action == "check":
        x, y, theta = route.start
        print(f"Route  {args.file}: {route.name}")
        print(f"  starts at ({x:g}, {y:g}, {theta:g}), {len(route.steps)} step(s)")
        for number, step in enumerate(route.steps, 1):
            print(f"  {number:>3}  {label(step)}")
        drive = checked.drive
        if drive is not None:  # its arcs and paths drive with it
            given = (
                f"its drive: section gives {', '.join(route.drive)}"
                if route.drive
                else "vexsim's, from the robot"
            )
            print(
                f"Drive model ({given}): kS {drive.kS:g} V, "
                f"kV {drive.kV:g} V per in/s, kA {drive.kA:g} V per in/s², kT {drive.kT:g} V, "
                f"kP {drive.kP:g} V per in/s"
            )
            print(
                f"  plans within {drive.max_velocity:g} in/s, {drive.max_accel:g} in/s², and "
                f"{drive.max_lateral_accel:g} in/s² turning at speed"
            )
        functions = checked.functions
        if args.functions and functions is not None:
            print(f"Functions a step can call ({', '.join(route.functions) or 'no headers'}):")
            for fn in functions.functions:
                print(f"  {fn.declaration()}")
            for other in functions.others:
                print(f"  not callable: {other.name}() (line {other.line}) {other.why}")
        _print_issues(checked.issues)
        if not checked.issues:
            print("  no problems")
        return EXIT_OK

    def log(line: str) -> None:  # the build's: with --json, stdout is the JSON alone
        print(line, file=sys.stderr if args.json else sys.stdout)

    try:
        result = run_route(args.file, seed=args.seed, noise=args.noise, log=log)
    except RunError as exc:
        _print_run_error(exc)
        return EXIT_INVALID
    if args.json:
        import json

        print(json.dumps(result, indent=2))
        return EXIT_OK if result["error"] is None else EXIT_INVALID
    if result["error"]:
        print(f"error: {result['error']}")
    ended = result["ended_s"]
    print(
        f"{route.name}: {len(route.steps)} step(s)"
        + (
            f", done {ended:.2f} s into the {result['period_s']:g} s autonomous period"
            if result["finished"]
            else ""
        )
    )
    row = "  {:>4}  {:>7}  {:>8}  {:<20}  {:<20}  {}"
    print(row.format("step", "ends at", "took (s)", "robot (x, y, θ)", "LemLib (x, y, θ)", "what"))
    for step in result["steps"]:
        if step["ended_s"] is None:
            where = "didn't end" if step["started_s"] is not None else "didn't start"
            print(row.format(step["number"], where, "", "", "", step["label"]))
            continue
        pose = ", ".join(f"{v:.1f}" for v in step["pose"])
        lemlib = ", ".join(f"{v:.1f}" for v in step["lemlib"]) if step["lemlib"] else "-"
        flag = " (used up its timeout)" if step["timed_out"] else ""
        ended, took = f"{step['ended_s']:.3f}", f"{step['duration_s']:.3f}"
        print(row.format(step["number"], ended, took, pose, lemlib, step["label"] + flag))
    return EXIT_OK if result["error"] is None else EXIT_INVALID


def cmd_route_export(args: argparse.Namespace) -> int:
    """``vexsim route export PROJECT``: the project's routes written into it as routines."""
    from vexsim.app.autons import ExportError, export, plan_export

    try:
        done = (plan_export if args.dry_run else export)(args.project)
    except ExportError as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    print(f"Routes of {args.project}, as routines:")
    for routine in done.routines:
        x, y, theta = routine.start
        print(f"  {routine.name}()  from {routine.route}, starts at ({x:g}, {y:g}, {theta:g})")
    for why in done.left_out:
        print(f"  left out: {why}")
    for change in done.files:
        print(f"  {change.path}: {change.state}")
        if args.diff and change.state != "unchanged":
            print(
                "".join("    " + line for line in change.diff().splitlines(keepends=True)), end=""
            )
    for note in done.notes:
        print(f"  note: {note}")
    if not done.changes:
        print("Up to date: nothing to write.")
    elif args.dry_run:
        print("Nothing written (--dry-run).")
    else:
        print(f"Wrote {sum(f.state != 'unchanged' for f in done.files)} file(s).")
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    from vexsim.bridge.doctor import run_doctor

    return EXIT_OK if run_doctor(args.cxx) else EXIT_INVALID


def cmd_run(args: argparse.Namespace) -> int:
    from vexsim.algorithms.localization.base import Pose
    from vexsim.app.runspec import (
        RunError,
        RunSpec,
        build,
        check,
        program_factory,
        simulation_factory,
    )
    from vexsim.bridge.host import HostError
    from vexsim.runtime.simulation import ScriptedInput

    try:
        prepared = check(RunSpec.from_args(args))
        for warning in prepared.warnings:
            if warning.location == "start":
                print(f"warning: {warning.message}")
        executable = build(prepared, log=print) if prepared.project is not None else None
        make_program, mode = program_factory(prepared, executable)
    except RunError as exc:
        _print_run_error(exc)
        return EXIT_INVALID
    inputs = ScriptedInput.from_csv(args.input) if args.input else None
    robot_logs = []  # the latest run's, when --robot-log asks for one

    def attach_robot_log(sim) -> None:
        from vexsim.calibration.record import RobotLogger

        robot_logs.append(RobotLogger(sim.robot, sim.sensors).attach(sim.world))

    factory = simulation_factory(
        prepared,
        make_program,
        mode,
        input_source=inputs,
        on_create=attach_robot_log if args.robot_log else None,
    )

    if args.headless:
        try:
            sim = factory()
            if args.seconds is not None:
                sim.run_for(args.seconds)
            elif not sim.run_until_finished(args.max_seconds):
                print(f"stopped after {args.max_seconds:g} s (the program was still running)")
        except HostError as exc:
            print(f"error: {exc}")
            return EXIT_INVALID
        sim.close()
        true = Pose.from_si(sim.robot.pose)
        est = sim.estimated_pose
        print(f"{mode} finished at t = {sim.world.time:.2f} s")
        print(f"  true pose      x {true.x:7.2f}  y {true.y:7.2f}  heading {true.heading_360:6.1f}")
        print(f"  estimated pose x {est.x:7.2f}  y {est.y:7.2f}  heading {est.heading_360:6.1f}")
        error = sim.recorder.pose_error(mode) if sim.recorder is not None else None
        if error is not None and sim.reported_pose is not None:
            print(f"  the robot code's pose vs. the true one during {mode}: {error}")
        if args.screenshot:
            from vexsim.viz.viewer import LiveSource, Viewer

            viewer = Viewer(LiveSource(lambda: sim), headless=True)
            if sim.recorder is not None:
                rows = sim.recorder.rows
                viewer.prefill_trails([(r[2], r[3]) for r in rows], [(r[5], r[6]) for r in rows])
            viewer.draw(viewer.source.snapshot())
            viewer.save(args.screenshot)
            print(f"wrote {args.screenshot}")
    else:
        from vexsim.viz.viewer import LiveSource, Viewer

        try:
            viewer = Viewer(LiveSource(factory), speed=args.speed)
        except ModuleNotFoundError:
            print('error: the viewer needs pygame; install it with: pip install -e ".[viz]"')
            return EXIT_INVALID
        except HostError as exc:
            print(f"error: {exc}")
            return EXIT_INVALID
        try:
            viewer.run()
        except HostError as exc:
            print(f"error: {exc}")
            return EXIT_INVALID
        finally:
            viewer.source.sim.close()
        sim = viewer.source.sim
    if args.record and sim.recorder is not None:
        print(f"wrote {sim.recorder.write_csv(args.record)}")
    if args.robot_log and robot_logs:
        from pathlib import Path

        log = robot_logs[-1].log()
        name = Path(args.program).stem if args.program else "no program"
        devices = robot_logs[-1].devices()
        log.info = {"vexsim-log": "2", "name": f"{name} in vexsim", "devices": devices}
        print(f"wrote {log.write(args.robot_log)}")
    return EXIT_OK


def cmd_plot(args: argparse.Namespace) -> int:
    from vexsim.runtime.recorder import Log
    from vexsim.viz import telemetry

    try:
        log = Log.read(args.log)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    from pathlib import Path

    title = args.title or Path(args.log).name
    print(f"wrote {telemetry.plot(log, args.out, title=title)}")
    return EXIT_OK


def cmd_replay(args: argparse.Namespace) -> int:
    from vexsim.runtime.recorder import Log
    from vexsim.viz.viewer import ReplaySource, Viewer

    config = _load_config(args.robot)
    if config is None:
        return EXIT_INVALID
    try:
        log = Log.read(args.log)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    viewer = Viewer(ReplaySource(config, log), headless=args.headless, speed=args.speed)
    if args.headless:
        viewer.source.advance(args.at if args.at is not None else 1e9)
        shown = log["time_s"] <= viewer.source.time
        viewer.prefill_trails(
            zip(log["x_in"][shown], log["y_in"][shown], strict=True),
            zip(log["est_x_in"][shown], log["est_y_in"][shown], strict=True),
        )
        viewer.draw(viewer.source.snapshot())
        if args.screenshot:
            viewer.save(args.screenshot)
            print(f"wrote {args.screenshot}")
        return EXIT_OK
    viewer.run()
    return EXIT_OK


def cmd_bench(args: argparse.Namespace) -> int:
    from pathlib import Path

    from vexsim.bench.runner import run_bench
    from vexsim.bench.scenario import validate_scenario

    report = validate_scenario(args.scenario)
    if not report.ok:
        print(f"Scenario  {report.source}")
        _print_issues(report.issues)
        return EXIT_INVALID

    def names(text: str | None) -> list[str] | None:
        return [n.strip() for n in text.split(",") if n.strip()] if text else None

    seeds = list(range(args.first_seed, args.first_seed + args.seeds))
    step = max(1, args.seeds // 10)
    last = [0]

    def progress(done: int, total: int) -> None:
        if done == total or done - last[0] >= step * max(1, total // args.seeds):
            last[0] = done
            print(f"  {done}/{total} trials", flush=True)

    try:
        result = run_bench(
            args.scenario,
            seeds,
            localizers=names(args.localizers),
            controllers=names(args.controllers),
            workers=args.workers,
            progress=progress,
        )
    except ValueError as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    print(
        f"\n{result.loaded.scenario.name}: {len(result.rows)} trials in {result.wall_time_s:.0f} s"
    )
    width = max(len(f"{e['localizer']} / {e['controller']}") for e in result.summary())
    print(
        f"  {'localizer / controller':<{width}}  success  final error mean/p95  loc error mean/p95"
    )
    for e in result.summary():
        label = f"{e['localizer']} / {e['controller']}"
        fe, le = e["final_error_in"], e["loc_error_final_in"]
        print(
            f"  {label:<{width}}  {e['success_rate'] * 100:6.0f}%  "
            f"{fe['mean']:7.2f} / {fe['p95']:5.2f} in    {le['mean']:6.2f} / {le['p95']:5.2f} in"
        )
    out = Path(args.out or f"bench_{Path(args.scenario).stem}")
    try:
        from vexsim.bench.report import write_report

        path = write_report(result, out, worst_cases=not args.no_worst)
    except ModuleNotFoundError:
        from vexsim.bench.report import write_csv

        out.mkdir(parents=True, exist_ok=True)
        path = write_csv(out / "trials.csv", result.rows)
        print('note: install the viz extra for the HTML report: pip install -e ".[viz]"')
    print(f"wrote {path}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vexsim",
        description="VEX V5 robot mechanics simulator.",
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

    p = sub.add_parser(
        "run",
        help="run a robot program in the live viewer (or headless)",
        description=(
            "Run a Python robot program (initialize/autonomous/opcontrol generators, see "
            "vexsim.api) in the live viewer. Without a program, drive the robot with the "
            "keyboard or a gamepad (arcade, plus strafing on robots that can). Press H in the "
            "viewer for keys."
        ),
    )
    p.add_argument("robot", nargs="?", help="robot YAML file (a --route's own, if left out)")
    p.add_argument(
        "--program",
        help="Python robot program file, or a PROS 4 project folder (built with `vexsim build`)",
    )
    p.add_argument(
        "--routine",
        metavar="NAME",
        help="PROS projects: run this routine from include/custom/auton.hpp in place of the "
        "one autonomous() calls (vexsim routines PROJECT lists them)",
    )
    p.add_argument(
        "--route",
        metavar="FILE",
        help="run a route (a YAML file in a PROS project's routes/ folder) as a routine is "
        "run: its project, robot, field and start, unless given",
    )
    p.add_argument(
        "--mode",
        choices=["autonomous", "driver", "match", "skills"],
        help="competition mode (default: autonomous for PROS projects and Python programs "
        "with an autonomous function, else driver)",
    )
    p.add_argument("--field", help="field YAML file")
    p.add_argument(
        "--start",
        type=_parse_start,
        help="x,y,heading (in, deg; default 0,0,0, or where --follow's log starts, or where "
        "--routine sets its pose)",
    )
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--noise", choices=["ideal", "default", "harsh"], help="sensor noise preset")
    p.add_argument("--speed", type=float, default=1.0, help="viewer speed (0.1 to 8; 0 = max)")
    p.add_argument("--input", help="scripted controller input CSV (time_s, LEFT_Y, ..., buttons)")
    p.add_argument(
        "--follow",
        metavar="LOG",
        help="drive along a real robot's path, from its MCL log: a virtual driver holds the "
        "sticks of the program's driver control (opcontrol) and the run ends with the log",
    )
    p.add_argument(
        "--sticks",
        choices=["tank", "arcade"],
        help="--follow: how the program drives from the sticks (default tank: both sticks' y; "
        "arcade: left y forward, right x turning)",
    )
    p.add_argument(
        "--curve",
        metavar="DEADBAND,MIN,CURVE",
        help="--follow: the program's LemLib ExpoDriveCurve, if it shapes the sticks with one",
    )
    p.add_argument("--record", help="write a telemetry CSV log")
    p.add_argument(
        "--robot-log",
        help="write a robot log: what the robot's own sensors read, as on a real robot "
        "(for vexsim calibrate, or to compare with a real robot's log)",
    )
    p.add_argument("--headless", action="store_true", help="no window: run, print, save")
    p.add_argument("--seconds", type=float, help="headless: run exactly this long")
    p.add_argument("--max-seconds", type=float, default=180.0, help="headless: give up after")
    p.add_argument("--screenshot", help="headless: save the final frame as PNG")
    p.add_argument(
        "--busy-timeout",
        type=float,
        default=5.0,
        help="PROS projects: stop if a task runs this many real seconds without blocking",
    )
    p.add_argument(
        "--env",
        action="append",
        metavar="KEY=VALUE",
        help="an environment variable for the robot program (getenv() in C++); repeatable. "
        "VEXSIM_SEED is always set to --seed",
    )
    p.add_argument(
        "--sd",
        metavar="FOLDER",
        help="PROS projects: a folder that stands in for the brain's SD card (made if it "
        "isn't there): files the code opens under /usd/ go there, as vexsim_log's logs do",
    )
    p.set_defaults(func=cmd_run)

    p = sub.add_parser(
        "routines",
        help="list a PROS project's autonomous routines (for run --routine)",
        description=(
            "List the routines in a PROS project's include/custom/auton.hpp: the functions it "
            "declares that take no arguments. vexsim run --routine NAME runs one of them in "
            "place of the routine the project's autonomous() calls, without changing the "
            "project. Where a routine sets LemLib's pose (chassis.setPose), its start is shown."
        ),
    )
    p.add_argument("project", help="PROS project folder")
    p.set_defaults(func=cmd_routines)

    p = sub.add_parser(
        "route",
        help="check an autonomous route, or run it and see where each step ended",
        description=(
            "A route is a YAML file in a PROS project's routes/ folder: a start pose and steps "
            "(LemLib motions, pauses and calls of the team's functions), run in the project's "
            "own autonomous() without changing the project. check reads and checks it; run "
            "runs it headless and prints where each step ended; export writes a project's "
            "routes into it as C++ routines."
        ),
    )
    actions = p.add_subparsers(dest="action", required=True)
    check = actions.add_parser("check", help="read and check a route")
    check.add_argument("file", help="the route's YAML file")
    check.add_argument(
        "--functions", action="store_true", help="list the functions its headers declare"
    )
    check.set_defaults(func=cmd_route)
    run = actions.add_parser("run", help="run a route headless; print where each step ended")
    run.add_argument("file", help="the route's YAML file")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--noise", choices=["ideal", "default", "harsh"], help="sensor noise preset")
    run.add_argument("--json", action="store_true", help="print the endpoints as JSON")
    run.set_defaults(func=cmd_route)
    export = actions.add_parser(
        "export",
        help="write a project's routes into it as routines (src/vexsim_autons.cpp)",
        description=(
            "Write each of a PROS project's routes as a C++ routine into src/vexsim_autons.cpp "
            "(rewritten whole each time) and declare them in include/custom/auton.hpp, between "
            "the comments // vexsim routes: begin and // vexsim routes: end, so the routine "
            "list and the team's selector can call them. Only files that change are written."
        ),
    )
    export.add_argument("project", help="PROS project folder (its routes are in routes/)")
    export.add_argument(
        "--dry-run", action="store_true", help="say what would change; write nothing"
    )
    export.add_argument("--diff", action="store_true", help="show each change as a diff")
    export.set_defaults(func=cmd_route_export)

    p = sub.add_parser(
        "build",
        help="compile a PROS 4 project to run in the simulator",
        description=(
            "Compile a PROS 4 project against vexsim's PROS shim with g++ (MSYS2 MinGW-w64 on "
            "Windows). The project is not modified; builds are incremental and cached."
        ),
    )
    p.add_argument("project", help="PROS project folder (the one with project.pros and src/)")
    p.add_argument("--debug", action="store_true", help="compile with -O0 -g for a debugger")
    p.add_argument("--jobs", type=int, help="parallel compiles (default: CPU cores)")
    p.add_argument("--cxx", help="g++ to use (default: $VEXSIM_CXX, then PATH)")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser(
        "doctor",
        help="check the C++ toolchain by building and running a test program",
        description="Find g++, check its version and threads, and build and run a test program.",
    )
    p.add_argument("--cxx", help="g++ to check (default: $VEXSIM_CXX, then PATH)")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser(
        "bench",
        help="Monte-Carlo comparison of localizers and controllers on a scenario",
        description=(
            "Run every seed x localizer x controller of a scenario in parallel, then write "
            "trials.csv, summary.csv, worst-case telemetry and a self-contained report.html."
        ),
    )
    p.add_argument("scenario", help="scenario YAML file")
    p.add_argument("--seeds", type=int, default=20, help="number of seeds (default 20)")
    p.add_argument("--first-seed", type=int, default=0)
    p.add_argument("--workers", type=int, help="worker processes (default: CPU cores - 1)")
    p.add_argument("--localizers", help="comma-separated subset of the scenario's localizers")
    p.add_argument("--controllers", help="comma-separated subset of the scenario's controllers")
    p.add_argument("--out", help="output directory (default: bench_<scenario name>)")
    p.add_argument("--no-worst", action="store_true", help="skip re-running the worst cases")
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("plot", help="plot a telemetry log (path, speed, currents, temps, battery)")
    p.add_argument("log", help="telemetry CSV from vexsim run --record")
    p.add_argument("--out", required=True, help="PNG file to write")
    p.add_argument("--title")
    p.set_defaults(func=cmd_plot)

    p = sub.add_parser("replay", help="replay a telemetry log in the viewer")
    p.add_argument("robot", help="robot YAML file the log was recorded with")
    p.add_argument("log", help="telemetry CSV")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--headless", action="store_true")
    p.add_argument("--at", type=float, help="headless: time to show (default: the end)")
    p.add_argument("--screenshot", help="headless: save the frame as PNG")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser(
        "calibration-routine",
        help="add the calibration routine (C++) for a robot to a PROS project",
        description=(
            "Write include/vexsim_calibration.hpp and src/vexsim_calibration.cpp into a PROS 4 "
            "project: a drive routine that logs what the robot measures, for vexsim calibrate. "
            "It builds with PROS for the real robot and runs in vexsim unchanged."
        ),
    )
    p.add_argument("robot", help="robot YAML file")
    p.add_argument("project", help="PROS project folder")
    p.set_defaults(func=cmd_calibration_routine)

    p = sub.add_parser(
        "logger",
        help="vexsim's logger for PROS projects: what the robot's devices read, for vexsim",
        description=(
            "vexsim's logger is two files (include/vexsim_log.hpp, src/vexsim_log.cpp), the same "
            "in every PROS 4 project: it finds what is plugged into each port and logs it every "
            "10 ms, with any poses and numbers the code adds, to the SD card or the terminal, "
            "for vexsim calibrate and comparing a real run with a simulated one."
        ),
    )
    actions = p.add_subparsers(dest="action", required=True)
    add = actions.add_parser("add", help="copy the logger's two files into a PROS project")
    add.add_argument("project", help="PROS project folder")
    add.set_defaults(func=cmd_logger_add)

    p = sub.add_parser(
        "calibrate",
        help="fit model parameters to a robot log",
        description=(
            "Replay a robot log (from the calibration routine, or any program that logs with "
            "vexsim_calibration::start_logging) in the simulator and fit model parameters until "
            "the simulated sensors match the logged ones."
        ),
    )
    p.add_argument("robot", help="robot YAML file")
    p.add_argument("log", help="robot log: the CSV, or terminal/console output that contains it")
    p.add_argument(
        "--fit",
        help="comma-separated parameters to fit (default: the wheel parameters); "
        "'none' replays and compares only",
    )
    p.add_argument("--max-iterations", type=int, default=12)
    p.add_argument(
        "--workers", type=int, default=0, help="parallel replays (default: CPUs, up to 8)"
    )
    p.add_argument("--out", help="folder for overrides.yaml, calibration.png and simulated.csv")
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser(
        "ui",
        help="open the vexsim app in your browser",
        description=(
            "Start the vexsim app for a folder (its workspace) and open it in your browser. "
            "It finds the robots, fields, programs and PROS projects in the folder; run "
            "and watch simulations from there. It listens on this computer only."
        ),
    )
    p.add_argument("folder", nargs="?", default=".", help="workspace folder (default: here)")
    p.add_argument("--port", type=int, help="port (default: 8642, or any free one)")
    where = p.add_mutually_exclusive_group()
    where.add_argument(
        "--window",
        action="store_true",
        help="open it in a window of its own (Edge's or Chrome's app mode); "
        "it stops when you close the window",
    )
    where.add_argument("--no-browser", action="store_true", help="don't open a browser")
    # stop when the app's last page closes (the VS Code panel opens it itself)
    p.add_argument("--stop-when-closed", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--token", help=argparse.SUPPRESS)  # fixed token, for tests
    p.add_argument("--dev", action="store_true", help=argparse.SUPPRESS)  # Vite dev server
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser(
        "shortcut",
        help="make shortcuts that open a folder in the vexsim app's window",
        description=(
            "Make shortcuts that open a workspace folder in the vexsim app, in a window of its "
            "own (vexsim ui FOLDER --window): in the Start menu and on the desktop on Windows, "
            "in the applications menu on Linux, in ~/Applications on macOS. They use this "
            "Python, so they work for as long as it has vexsim installed."
        ),
    )
    p.add_argument("folder", nargs="?", default=".", help="workspace folder (default: here)")
    p.add_argument("--remove", action="store_true", help="remove the folder's shortcuts")
    p.set_defaults(func=cmd_shortcut)

    p = sub.add_parser(
        "vscode",
        help="install the VS Code extension that shows the app in a panel",
        description=(
            "Install vexsim's VS Code extension. Then 'vexsim: Open the app' (Command Palette) "
            "or 'Open in vexsim' (on a folder in the Explorer) shows the app in a panel beside "
            "your code, where file:line links open in the editor. It runs vexsim with this "
            "Python."
        ),
    )
    p.add_argument(
        "--code",
        default="code",
        help="the editor's command (default: code; or code-insiders, cursor, codium)",
    )
    p.add_argument("--out", help="where to write the .vsix (default: vexsim's own folder)")
    p.add_argument("--no-install", action="store_true", help="only write the .vsix")
    p.set_defaults(func=cmd_vscode)

    return parser


def cmd_calibration_routine(args: argparse.Namespace) -> int:
    from vexsim.calibration.cpp import write_routine
    from vexsim.calibration.routine import schedule, standard_routine

    config = _load_config(args.robot)
    if config is None:
        return EXIT_INVALID
    for path in write_routine(config, args.project):
        print(f"wrote {path}")
    seconds = schedule(config, standard_routine(config))[-1][0] / 1000
    print(
        f"Call vexsim_calibration::run() from autonomous() (it takes {seconds:g} s plus IMU "
        "calibration, and needs about 3 x 3 m of open floor), then copy its log from the SD "
        "card (vexsim_0001_calibration.csv, numbered up from there), or save the terminal "
        "output, and run: vexsim calibrate ROBOT.yaml LOG"
    )
    return EXIT_OK


def cmd_logger_add(args: argparse.Namespace) -> int:
    from pathlib import Path

    from vexsim.bridge.build import is_pros_project
    from vexsim.bridge.logger import add_logger

    project = Path(args.project)
    if not is_pros_project(project):
        print(f"error: {project} isn't a PROS project (no project.pros or src/)")
        return EXIT_INVALID
    for path, state in add_logger(project):
        print(f"{path}: {state}")
    print(
        "\nTo log, in src/main.cpp:\n"
        '  #include "vexsim_log.hpp"\n'
        "  void autonomous() {\n"
        '      vexsim_log::start("my routine");  // finds every device, logs it every 10 ms\n'
        "      ...\n"
        "      vexsim_log::stop();  // or it saves itself when autonomous ends\n"
        "  }\n"
        "vexsim_log::pose() and value() add what only your code knows (include/vexsim_log.hpp "
        "says how).\nLogs go to the SD card (vexsim_0001_my_routine.csv, numbered up from "
        "there), or to the terminal without a card (pros terminal > log.txt). In vexsim, "
        "vexsim run --sd FOLDER stands in for the card."
    )
    return EXIT_OK


def cmd_calibrate(args: argparse.Namespace) -> int:
    from pathlib import Path

    from vexsim.calibration.fit import UNITS, compare, fit, worker_count
    from vexsim.calibration.log import RobotLog

    config = _load_config(args.robot)
    if config is None:
        return EXIT_INVALID
    try:
        log = RobotLog.read(args.log)
    except (OSError, ValueError) as exc:
        print(f"error: {args.log}: {exc}")
        return EXIT_INVALID
    seconds = (log.time_ms[-1] - log.time_ms[0]) / 1000
    kinds = [
        (len(log.ports("m")), "motor"),
        (len(log.ports("r")), "rotation sensor"),
        (len(log.ports("imu")), "IMU"),
        (len(log.ports("gps")), "GPS"),
    ]
    found = ", ".join(f"{n} {name}{'s' if n > 1 else ''}" for n, name in kinds if n)
    print(f"Robot log: {len(log)} rows ({seconds:.1f} s): {found}")
    if log.skipped_lines:
        print(f"  skipped {log.skipped_lines} malformed line(s)")
    unknown = sorted(
        set(log.ports("m")) - {abs(p) for g in config.drivetrain.gearing.values() for p in g.motors}
    )
    if unknown:
        print(f"  ignoring motors not in the drivetrain: {', '.join(map(str, unknown))}")

    before = after = None
    if args.fit == "none":
        try:
            rms, after = compare(config, log)
        except ValueError as exc:
            print(f"error: {exc}")
            return EXIT_INVALID
        print("\nRMS difference, simulated vs. logged:")
        for group, value in rms.items():
            print(f"  {group} ({UNITS[group]}): {value:.3g}")
        overrides: dict[str, float] = {}
    else:
        names = [n.strip() for n in args.fit.split(",") if n.strip()] if args.fit else None
        try:
            result = fit(
                config,
                log,
                names,
                max_iterations=args.max_iterations,
                workers=worker_count(args.workers),
                progress=lambda text: print(f"  {text}"),
            )
        except ValueError as exc:
            print(f"error: {exc}")
            return EXIT_INVALID
        before, after = result.sim_before, result.sim_after
        width = max([len(n) for n in result.overrides] + [9])
        print(f"\n{'parameter':<{width}}  {'before':>9}  {'after':>9}  uncertainty")
        for name in result.parameters:
            spread = result.uncertainty[name]
            note = f"+/-{spread * 100:.2g}%" if spread < 0.5 else "poorly determined by this log"
            print(
                f"{name:<{width}}  {result.before[name]:>9.4g}  {result.after[name]:>9.4g}  {note}"
            )
        for name, value in result.direct.items():
            old = config.overrides.get(name)
            shown = f"{old:>9.4g}" if old is not None else f"{'':>9}"
            print(f"{name:<{width}}  {shown}  {value:>9.4g}  from battery voltage vs. current")
        print(f"\nRMS difference, simulated vs. logged ({result.replays} replays):")
        for group, value in result.rms_after.items():
            print(f"  {group} ({UNITS[group]}): {result.rms_before[group]:.3g} -> {value:.3g}")
        overrides = result.overrides
        print("\nAdd to the robot config:\noverrides:")
        for name, value in overrides.items():
            print(f"  {name}: {value:g}")

    from vexsim.calibration.feedforward import drive_section, fit_log

    drive = fit_log(config, log)  # for vexsim's own motions, on the real robot
    if drive is not None:
        print(f"\nDrive model for vexsim's own motions (arcs, RAMSETE paths): {drive.describe()}")
        print(f"For the robot's routes, add to them:\n  {drive_section(drive)}")
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        if overrides:
            text = "overrides:\n" + "".join(f"  {k}: {v:g}\n" for k, v in overrides.items())
            (out / "overrides.yaml").write_text(text, encoding="utf-8")
        after.write(out / "simulated.csv")
        if drive is not None:
            (out / "drive.yaml").write_text(drive_section(drive) + "\n", encoding="utf-8")
        try:
            from vexsim.viz import calibration as cal_plot

            title = f"{Path(args.log).name}: logged vs. simulated"
            path = cal_plot.plot(config, log, before, after, out / "calibration.png", title=title)
            print(f"wrote {path}")
        except ModuleNotFoundError:
            print('note: plots need matplotlib; install it with: pip install -e ".[viz]"')
        print(f"wrote {out}")
    return EXIT_OK


def cmd_ui(args: argparse.Namespace) -> int:
    from pathlib import Path

    windowless = _log_when_windowless()
    folder = Path(args.folder)
    if not folder.is_dir():
        return _ui_error(f"{args.folder} is not a folder", windowless)
    try:
        from vexsim.ui.server import serve
    except ModuleNotFoundError as exc:
        return _ui_error(
            f'the UI needs {exc.name}; install it with: pip install -e ".[ui]"', windowless
        )
    try:
        serve(
            folder,
            port=args.port,
            open_browser=not args.no_browser,
            window=args.window,
            stop_when_closed=args.stop_when_closed,
            token=args.token,
            dev=args.dev,
        )
    except OSError as exc:
        return _ui_error(str(exc), windowless)
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def cmd_shortcut(args: argparse.Namespace) -> int:
    from pathlib import Path

    from vexsim.ui import shortcut

    folder = Path(args.folder).resolve()
    try:
        if args.remove:
            removed = shortcut.remove(folder)
            for label, path in removed.items():
                print(f"Removed from the {label}: {path}")
            if not removed:
                print(f"{folder} has no shortcuts to remove")
            return EXIT_OK
        if not folder.is_dir():
            print(f"error: {args.folder} is not a folder")
            return EXIT_INVALID
        if _ui_missing():
            return EXIT_INVALID
        made = shortcut.make(folder)
    except (shortcut.ShortcutError, OSError) as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    print(f"Shortcuts that open {folder} in the vexsim app:")
    for label, path in made.items():
        print(f"  {label}: {path}")
    return EXIT_OK


def cmd_vscode(args: argparse.Namespace) -> int:
    from pathlib import Path

    from vexsim.ui import vsix
    from vexsim.ui.window import user_folder

    if _ui_missing():
        return EXIT_INVALID
    out = Path(args.out) if args.out else user_folder() / "vexsim.vsix"
    try:
        vsix.build(out)
    except OSError as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    print(f"Wrote the extension: {out}")
    if args.no_install:
        return EXIT_OK
    code = vsix.find_code(args.code)
    if code is None:
        print(
            f"error: can't find VS Code's command ({args.code}). In VS Code, install {out} "
            "from the Extensions view: its ... menu, Install from VSIX..."
        )
        return EXIT_INVALID
    try:
        said = vsix.install(out, code)
    except vsix.VsixError as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    if said:
        print(said)
    print(
        "In VS Code: 'vexsim: Open the app' from the Command Palette (Ctrl+Shift+P), or "
        "'Open in vexsim' on a folder in the Explorer."
    )
    return EXIT_OK


def _ui_missing() -> bool:
    """Say so if the app's packages (the [ui] extra) aren't installed."""
    from importlib.util import find_spec

    missing = [name for name in ("fastapi", "uvicorn", "websockets") if not find_spec(name)]
    if missing:
        print(f'error: the app needs {missing[0]}; install it with: pip install -e ".[ui]"')
    return bool(missing)


def _log_when_windowless() -> bool:
    """Started with no console (pythonw, from a shortcut): what it prints goes to ui.log in
    vexsim's own folder instead, to find out why if it doesn't open. True if so."""
    if sys.stdout is not None and sys.stderr is not None:
        return False
    from vexsim.ui.window import user_folder

    try:
        user_folder().mkdir(parents=True, exist_ok=True)
        log = open(user_folder() / "ui.log", "w", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return True
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log
    return True


def _ui_error(message: str, windowless: bool) -> int:
    print(f"error: {message}")
    if windowless and sys.platform == "win32":  # there's nowhere else to see it
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "vexsim", 0x10)  # an error icon
    return EXIT_INVALID


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

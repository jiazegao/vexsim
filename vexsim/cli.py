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
        executable = build(prepared, log=print) if prepared.project is not None else None
    except RunError as exc:
        _print_run_error(exc)
        return EXIT_INVALID
    make_program, mode = program_factory(prepared, executable)
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
        print(f"wrote {robot_logs[-1].log().write(args.robot_log)}")
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
    p.add_argument("robot", help="robot YAML file")
    p.add_argument(
        "--program",
        help="Python robot program file, or a PROS 4 project folder (built with `vexsim build`)",
    )
    p.add_argument(
        "--mode",
        choices=["autonomous", "driver", "match", "skills"],
        help="competition mode (default: autonomous for PROS projects and Python programs "
        "with an autonomous function, else driver)",
    )
    p.add_argument("--field", help="field YAML file")
    p.add_argument("--start", type=_parse_start, default="0,0,0", help="x,y,heading (in, deg)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--noise", choices=["ideal", "default", "harsh"], help="sensor noise preset")
    p.add_argument("--speed", type=float, default=1.0, help="viewer speed (0.1 to 8; 0 = max)")
    p.add_argument("--input", help="scripted controller input CSV (time_s, LEFT_Y, ..., buttons)")
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
    p.set_defaults(func=cmd_run)

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
    p.add_argument("--no-browser", action="store_true", help="don't open a browser")
    p.add_argument("--token", help=argparse.SUPPRESS)  # fixed token, for tests
    p.add_argument("--dev", action="store_true", help=argparse.SUPPRESS)  # Vite dev server
    p.set_defaults(func=cmd_ui)

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
        "calibration, and needs about 3 x 3 m of open floor), then copy /usd/vexsim_log.csv "
        "from the SD card, or save the terminal output, and run: vexsim calibrate ROBOT.yaml LOG"
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

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        if overrides:
            text = "overrides:\n" + "".join(f"  {k}: {v:g}\n" for k, v in overrides.items())
            (out / "overrides.yaml").write_text(text, encoding="utf-8")
        after.write(out / "simulated.csv")
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

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"error: {args.folder} is not a folder")
        return EXIT_INVALID
    try:
        from vexsim.ui.server import serve
    except ModuleNotFoundError as exc:
        print(f'error: the UI needs {exc.name}; install it with: pip install -e ".[ui]"')
        return EXIT_INVALID
    try:
        serve(
            folder,
            port=args.port,
            open_browser=not args.no_browser,
            token=args.token,
            dev=args.dev,
        )
    except OSError as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    except KeyboardInterrupt:
        pass
    return EXIT_OK


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

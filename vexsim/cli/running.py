"""``vexsim run``, and a run's log afterwards: ``plot`` and ``replay``."""

from __future__ import annotations

import argparse

from vexsim.cli.common import EXIT_INVALID, EXIT_OK, _load_config, _parse_start, _print_run_error


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
        drawings=not args.headless or bool(args.screenshot),  # headless: nothing shows them
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


def add_run(sub) -> None:
    """The parser's commands: run."""
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
        help="drive along a real robot's path, from its robot log (the first pose its code "
        "logged with vexsim_log::pose) or its MCL log: a virtual driver holds the sticks of the "
        "program's driver control (opcontrol) and the run ends with the log",
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


def add_logs(sub) -> None:
    """The parser's commands: plot, replay."""
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

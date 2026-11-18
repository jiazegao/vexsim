"""A calibration session: ``vexsim calibration plan``, ``program``, ``collect`` and
``check-auton``, and ``vexsim logger add``."""

from __future__ import annotations

import argparse

from vexsim.cli.common import EXIT_INVALID, EXIT_OK, _load_config, _print_issues
from vexsim.config.loader import validate_field


def add_calibration(sub) -> None:
    """The parser's commands: calibration (plan, program, collect, check-auton), logger."""
    p = sub.add_parser(
        "calibration",
        help="calibrate vexsim with a physical robot: plan the tests, write the program",
        description=(
            "A calibration session runs a program on the real robot that tests its drive, "
            "motors and sensors and logs each test. 'plan' finds where on the field each test "
            "fits between the elements; 'program' writes the program into a PROS project."
        ),
    )
    actions = p.add_subparsers(dest="action", required=True)
    plan = actions.add_parser(
        "plan",
        help="find where each test fits on the field; write the maps",
        description=(
            "Simulate each driving test over a spread of the parameters it measures and find "
            "where on the field all of those paths fit, a margin clear of the walls and every "
            "element; likewise the push lane and the spots for the slow spin and the distance "
            "sweeps. Prints where to put the robot for each, from two walls."
        ),
    )
    plan.add_argument("robot", help="robot YAML file")
    plan.add_argument("field", help="field YAML file, with the elements as they'll be")
    plan.add_argument(
        "--margin", type=float, default=6.0, help="room to keep around each test (in, default 6)"
    )
    plan.add_argument("--out", help="folder for plan.txt, plan.yaml and the maps")
    plan.add_argument(
        "--workers", type=int, default=0, help="parallel simulations (default: CPUs, up to 8)"
    )
    plan.set_defaults(func=cmd_calibration_plan)
    program = actions.add_parser(
        "program",
        help="write the calibration program into a PROS project, for a spare slot",
        description=(
            "Plan the tests (as 'plan' does), then write the calibration program into a PROS "
            "project made for it (pros c n FOLDER): a menu of the session's tests on the "
            "brain and the controller, each logged with vexsim's logger. It builds with PROS "
            "for the robot (pros upload --slot 8) and runs unchanged in vexsim "
            "(vexsim run ROBOT.yaml --program FOLDER --mode driver --sd SD_FOLDER). The plan "
            "and its maps go in FOLDER/plan/."
        ),
    )
    program.add_argument("robot", help="robot YAML file")
    program.add_argument("field", help="field YAML file, with the elements as they'll be")
    program.add_argument("folder", help="PROS project folder for the program (pros c n FOLDER)")
    program.add_argument(
        "--margin", type=float, default=6.0, help="room to keep around each test (in, default 6)"
    )
    program.add_argument(
        "--workers", type=int, default=0, help="parallel simulations (default: CPUs, up to 8)"
    )
    program.add_argument(
        "--force", action="store_true", help="write over a src/main.cpp that isn't the program's"
    )
    program.set_defaults(func=cmd_calibration_program)
    collect = actions.add_parser(
        "collect",
        help="copy the program's logs into a session folder, and check each",
        description=(
            "Copy the calibration program's logs that the session doesn't have yet into "
            "SESSION/runs/, check each (the robot's name, finished or stopped, its warnings) "
            "and list them in SESSION/session.yaml, where use: false leaves a run out of the "
            "fit. Then: vexsim calibrate ROBOT.yaml SESSION."
        ),
    )
    collect.add_argument("session", help="the session's folder (made if it isn't there)")
    source = collect.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--from-card", action="store_true", help="the brain's SD card, in this computer"
    )
    source.add_argument("--from", dest="source", metavar="FOLDER", help="a folder of logs")
    source.add_argument(
        "--usb",
        action="store_true",
        help="over USB as the program prints them (no card in the brain), until Ctrl+C",
    )
    collect.add_argument(
        "--command",
        default="pros terminal",
        help="what prints the brain's terminal, for --usb (default: pros terminal)",
    )
    collect.set_defaults(func=cmd_calibration_collect)
    auton = actions.add_parser(
        "check-auton",
        help="check the team's real autonomous against the simulated one",
        description=(
            "Run the routine a real robot's log is of (its competition program, with "
            "vexsim's logger) in vexsim, from where the log's code set its pose, with a few "
            "seeds, each until the robot is still after the period; and compare: where it "
            "ended (measured with tape at two corners, --end) against where the simulated runs "
            "did, and the code's pose through the run against theirs. It passes when the end "
            "is within the pass marks (2 in and 2 degrees, or the team's in "
            ".vexsim/calibration.yaml: max_distance_in, max_heading_deg) and the run is "
            "within the distance mark (RMS). The report and its plots go in --out."
        ),
    )
    auton.add_argument("robot", help="robot YAML file (as calibrated)")
    auton.add_argument("logs", nargs="+", metavar="LOG", help="the real run's log (one or more)")
    auton.add_argument("--program", required=True, help="the PROS project the robot ran")
    auton.add_argument("--field", required=True, help="field YAML file, as the field was")
    auton.add_argument(
        "--end",
        action="append",
        required=True,
        metavar="MEASUREMENTS",
        help='where each run ended, two corners from two walls each: "front-left: 23.5 from '
        '-x, 40 from +y; back-right: 35.25 from -x, 52 from +y" (one --end per log, in order)',
    )
    auton.add_argument("--routine", help="the routine's function (default: as the log names it)")
    auton.add_argument(
        "--seeds", type=int, default=3, help="simulated runs to compare with (default 3)"
    )
    auton.add_argument("--max-distance", type=float, help="the distance mark (in)")
    auton.add_argument("--max-heading", type=float, help="the heading mark (degrees)")
    auton.add_argument(
        "--env", action="append", metavar="KEY=VALUE", help="environment for the program"
    )
    auton.add_argument("--out", help="folder for the report (default: beside the first log)")
    auton.add_argument(
        "--workers", type=int, default=0, help="parallel simulations (default: CPUs, up to 8)"
    )
    auton.set_defaults(func=cmd_calibration_check_auton)

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


def _load_robot_and_field(args: argparse.Namespace):
    config = _load_config(args.robot)
    if config is None:
        return None
    report = validate_field(args.field)
    if not report.ok or report.config is None:
        _print_issues(report.issues)
        return None
    return config, report.config


def cmd_calibration_plan(args: argparse.Namespace) -> int:
    from vexsim.calibration.plan import make_plan, write_plan

    loaded = _load_robot_and_field(args)
    if loaded is None:
        return EXIT_INVALID
    config, field = loaded
    plan = make_plan(config, field, margin=args.margin, workers=args.workers, progress=print)
    print()
    print(plan.text(), end="")
    if args.out:
        print()
        for path in write_plan(plan, args.out):
            print(f"wrote {path}")
    return EXIT_INVALID if plan.missing else EXIT_OK


def cmd_calibration_program(args: argparse.Namespace) -> int:
    from pathlib import Path

    from vexsim.calibration.plan import make_plan, write_plan
    from vexsim.calibration.program import ProgramError, check_folder, write_program

    loaded = _load_robot_and_field(args)
    if loaded is None:
        return EXIT_INVALID
    config, field = loaded
    folder = Path(args.folder)
    try:
        check_folder(folder, force=args.force)
    except ProgramError as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    plan = make_plan(config, field, margin=args.margin, workers=args.workers, progress=print)
    print()
    for path, state in write_program(config, plan, folder, force=args.force):
        print(f"{path}: {state}")
    for path in write_plan(plan, folder / "plan"):
        print(f"wrote {path}")
    print()
    print(plan.text(), end="")
    if plan.missing:
        names = ", ".join(t.title for t in plan.missing)
        print(f"\nLeft out, with no room on this field: {names}.")
    if not (folder / "project.pros").is_file():
        print(
            f"\n{folder} isn't a PROS project yet: it runs in vexsim, but to put it on the "
            f"robot, make one first (pros c n {folder}) and run this again."
        )
    print(
        f"\nOn the robot: pros upload --slot 8 (in {folder}), then run it from the brain's "
        "screen: its menu lists the tests in order.\n"
        f"In vexsim: vexsim run {args.robot} --program {folder} --mode driver --field "
        f"{args.field} --sd sd"
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


def cmd_calibration_collect(args: argparse.Namespace) -> int:
    import shlex
    from pathlib import Path

    from vexsim.calibration.session import Session, card_logs, collect, find_card, from_usb

    session = Session.open(args.session)
    before = len(session.runs)
    if args.usb:
        try:
            added = from_usb(session, shlex.split(args.command), say=print)
        except OSError as exc:
            print(f"error: {exc}")
            return EXIT_INVALID
    else:
        if args.from_card:
            folder = find_card()
            if folder is None:
                print(
                    "error: no SD card with vexsim's logs found: put the brain's card in this "
                    "computer (or copy its files to a folder and use --from FOLDER)"
                )
                return EXIT_INVALID
            print(f"the card: {folder}")
        else:
            folder = Path(args.source)
            if not folder.is_dir():
                print(f"error: {folder} is not a folder")
                return EXIT_INVALID
        logs = card_logs(folder)
        if not logs:
            print(f"error: no logs in {folder} (vexsim_0001_device_check.csv and so on)")
            return EXIT_INVALID
        added = collect(session, logs, say=print)
    print(
        f"\n{len(added)} new run(s); {before + len(added)} in {session.file} for "
        f"{session.robot or 'the robot'}."
    )
    tests: dict[str, list[str]] = {}
    for run in session.runs:
        tests.setdefault(run.test, []).append("used" if run.use else f"left out ({run.quality})")
    for test, states in tests.items():
        used = states.count("used")
        out = [s for s in states if s != "used"]
        print(f"  {test}: {used} used" + (f", {len(out)} " + "; ".join(out) if out else ""))
    print(f"\nThen: vexsim calibrate ROBOT.yaml {args.session}")
    return EXIT_OK


def cmd_calibration_check_auton(args: argparse.Namespace) -> int:
    from pathlib import Path

    from vexsim.app.runspec import RunError, parse_env
    from vexsim.calibration.auton import AutonError, check_auton, load_marks, write_report
    from vexsim.calibration.fit import worker_count
    from vexsim.config import load_field

    config = _load_config(args.robot)
    if config is None:
        return EXIT_INVALID
    report = validate_field(args.field)
    if not report.ok or report.config is None:
        _print_issues(report.issues)
        return EXIT_INVALID
    if args.seeds < 1:
        print("error: --seeds needs 1 or more")
        return EXIT_INVALID
    try:
        marks = load_marks(max_distance_in=args.max_distance, max_heading_deg=args.max_heading)
        env = parse_env(args.env or ())
        print(
            f"Pass marks: {marks.max_distance_in:g} in, {marks.max_heading_deg:g} degrees "
            f"({marks.source})"
        )
        result = check_auton(
            args.robot,
            args.field,
            args.program,
            args.logs,
            args.end,
            marks=marks,
            routine=args.routine,
            seeds=args.seeds,
            env=env,
            workers=min(worker_count(args.workers), args.seeds),
            say=lambda text: print(f"  {text}"),
        )
    except (AutonError, RunError) as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    print()
    for run in result.runs:
        if run.end is not None:
            x, y, h = run.end.pose
            print(f"{run.file}: ended at {x:.2f}, {y:.2f}, {h:.1f} deg (measured)", end="")
            off = run.end_off
            print(f"; {off[0]:.2f} in and {off[1]:+.1f} deg from the simulated end" if off else "")
        if run.run_rms_in is not None:
            parted = (
                "" if run.parted_s is None else f"; first over the mark at {run.parted_s:.1f} s"
            )
            print(
                f"  through the run: {run.run_rms_in:.2f} in from the simulated runs (RMS){parted}"
            )
    x, y, h = result.sim_end
    print(f"simulated: ended at {x:.2f}, {y:.2f}, {h:.1f} deg (the seeds' mean)")
    for warning in result.warnings:
        print(f"warning: {warning}")
    folder = (
        Path(args.out)
        if args.out
        else Path(args.logs[0]).with_suffix("").parent / (Path(args.logs[0]).stem + "_check")
    )
    written = write_report(result, config, load_field(args.field), folder)
    print(f"\nwrote {written} (with its plots)")
    if result.passed:
        print(f"PASSED: the simulated {result.routine} matches the real one, within the marks.")
        return EXIT_OK
    print(f"FAILED: the simulated {result.routine} doesn't match the real one:")
    for failure in result.failures:
        print(f"  - {failure}")
    return EXIT_INVALID

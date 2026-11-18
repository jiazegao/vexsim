"""PROS projects: ``vexsim build``, ``doctor``, ``routines`` and ``route``."""

from __future__ import annotations

import argparse
import sys

from vexsim.cli.common import EXIT_INVALID, EXIT_OK, _print_issues, _print_run_error


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


def add_projects(sub) -> None:
    """The parser's commands: routines, route, build, doctor."""
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

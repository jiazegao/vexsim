"""``vexsim calibrate`` (a quick fit, or a whole session's) and ``calibration-routine``."""

from __future__ import annotations

import argparse

from vexsim.cli.common import EXIT_INVALID, EXIT_OK, _load_config, _print_issues
from vexsim.config.loader import validate_field


def add_routine(sub) -> None:
    """The parser's commands: calibration-routine."""
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


def add_calibrate(sub) -> None:
    """The parser's commands: calibrate."""
    p = sub.add_parser(
        "calibrate",
        help="fit the model to a calibration session, or to a robot log",
        description=(
            "Given a calibration session's folder (vexsim calibration collect), fit each test "
            "into what it measures, in order: the motors, the IMU, the wheels' diameters, the "
            "drive (one run held out to check it), the tracking wheels and the distance "
            "sensors; write SESSION/report/ and, with --apply, the robot config. Given a robot "
            "log, replay it in the simulator and fit model parameters until the simulated "
            "sensors match the logged ones."
        ),
    )
    p.add_argument("robot", help="robot YAML file")
    p.add_argument(
        "log",
        help="a calibration session's folder, or a robot log (the CSV, or terminal output "
        "that contains it)",
    )
    p.add_argument(
        "--field",
        help="a session's field YAML (for the distance sweeps; found by the logs' field name "
        "next to the robot's config if not given)",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="a session: write what it found into the robot YAML, its comments kept",
    )
    p.add_argument(
        "--fit",
        help="comma-separated parameters to fit (default: the wheel parameters); "
        "'none' replays and compares only",
    )
    p.add_argument("--max-iterations", type=int, default=12)
    p.add_argument(
        "--workers", type=int, default=0, help="parallel replays (default: CPUs, up to 8)"
    )
    p.add_argument(
        "--out",
        help="folder for overrides.yaml, calibration.png and simulated.csv (a session's "
        "report goes in SESSION/report/)",
    )
    p.set_defaults(func=cmd_calibrate)


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


def _session_field(session, robot_path: str, given: str | None):
    """The field the session ran on: the one given, or the one named as its logs name it,
    among the fields next to the robot config's folder (or here)."""
    from pathlib import Path

    from vexsim.config import load_field

    if given:
        report = validate_field(given)
        if not report.ok or report.config is None:
            _print_issues(report.issues)
            raise ValueError(f"{given} isn't a valid field config")
        return report.config
    if not session.field_name:
        return None
    robot_dir = Path(robot_path).resolve().parent
    for folder in (robot_dir.parent / "fields", robot_dir, Path("fields"), Path(".")):
        for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
            try:
                field = load_field(path)
            except Exception:  # noqa: BLE001 - any YAML that isn't a field
                continue
            if field.name == session.field_name:
                print(f"field: {path} (the one the logs name)")
                return field
    return None


def _calibrate_session(args: argparse.Namespace, config) -> int:
    import datetime
    from pathlib import Path

    from vexsim.calibration.feedforward import drive_section
    from vexsim.calibration.fit import UNITS, worker_count
    from vexsim.calibration.report import apply_changes, why_not, write_report
    from vexsim.calibration.session import Session
    from vexsim.calibration.session_fit import SessionError, calibrate

    session = Session.open(args.log)
    if not session.runs:
        print(
            f"error: {args.log} has no runs: collect them first "
            f"(vexsim calibration collect {args.log} --from-card)"
        )
        return EXIT_INVALID
    try:
        field = _session_field(session, args.robot, args.field)
    except ValueError as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    print(f"Calibration session {session.folder}: {len(session.runs)} runs of {session.robot}")
    try:
        result = calibrate(
            config,
            session,
            field,
            workers=worker_count(args.workers),
            say=lambda text: print(f"  {text}"),
        )
    except SessionError as exc:
        print(f"error: {exc}")
        return EXIT_INVALID
    when = datetime.date.today().isoformat()
    report, writes = write_report(config, result, session.folder / "report", when=when)
    for number, step in enumerate(result.steps, 1):
        print(f"\n{number}. {step.name}")
        if step.skipped:
            print(f"   skipped: {step.skipped}")
        for v in step.values:
            why = why_not(v)
            mark = "" if not why else f"  ({why})"
            print(f"   {v.key}: {v.before:.4g} -> {v.after:.4g}{mark}")
        for group, (before, after) in step.rms.items():
            print(f"   {group}: {before:.3g} -> {after:.3g} {UNITS.get(group, '')} (RMS)")
        for warning in step.warnings:
            print(f"   warning: {warning}")
    held = result.held_out
    if held is not None:
        verdict = "matches" if held.matches else "DOESN'T match"
        print(f"\nThe held-out run ({held.run}) {verdict} within the sensors' noise.")
    if result.drive is not None:
        print(f"\nDrive model for vexsim's own motions: {result.drive.describe()}")
        print(f"For the robot's routes, add to them:\n  {drive_section(result.drive)}")
    print(f"\nwrote {report} (and changes.yaml, with the plots)")
    if not writes:
        print("Nothing to write: the logs agree with the robot config as it is.")
        return EXIT_OK
    if not args.apply:
        print(f"{len(writes)} change(s) to write: vexsim calibrate {args.robot} {args.log} --apply")
        return EXIT_OK
    robot = Path(args.robot)
    text = robot.read_text(encoding="utf-8")
    robot.write_text(
        apply_changes(text, writes, session.folder.name, when), encoding="utf-8", newline=""
    )
    if _load_config(args.robot) is None:
        robot.write_text(text, encoding="utf-8", newline="")
        print(f"error: the changes didn't make a valid config, so {robot} is as it was")
        return EXIT_INVALID
    print(f"wrote {len(writes)} change(s) into {robot}, its comments kept")
    return EXIT_OK


def cmd_calibrate(args: argparse.Namespace) -> int:
    from pathlib import Path

    from vexsim.calibration.fit import UNITS, compare, fit, worker_count
    from vexsim.calibration.log import RobotLog

    config = _load_config(args.robot)
    if config is None:
        return EXIT_INVALID
    if Path(args.log).is_dir():
        return _calibrate_session(args, config)
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

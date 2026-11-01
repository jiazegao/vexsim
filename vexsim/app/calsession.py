"""A calibration session in the app: the Calibrate page's steps (phase 14.7), over phase 14's
tools (``vexsim calibration program``, ``collect``, ``check-auton`` and ``vexsim calibrate``).

    the plan and the program   ``program_job`` plans the session on the field and writes the
                               program into a PROS project; ``program_info`` reads back what it
                               wrote (plan/plan.json, the maps)
    a practice session         ``practice_job``: the simulated student runs the program in
                               vexsim, on the robot as a real one is (``student.unlike``), its
                               logs collected into a session marked as practice
    collecting                 ``collect_logs`` (from the card, or a folder), ``usb_job`` (over
                               USB, until stopped), ``set_use`` (a run left out, or back in)
    each run's result          ``session_state``: the session's runs, each with a line of what
                               it measured (as the brain's screen said), and its latest fit
    the fit                    ``fit_job``: the session fitted, its report written, and
                               report/report.json (what the page shows); ``apply_session``
                               writes its changes into a robot config's text
    the autonomous check       ``check_job``, kept with the results (.vexsim/checks/);
                               ``pass_marks`` and ``save_marks`` (.vexsim/calibration.yaml),
                               ``end_found`` (two corners' tape marks, read as the student types)

The jobs' params name files as absolute paths, beside the workspace's names for them
(``*_name``) for what the page shows.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import numpy as np

from vexsim.app.jsonsafe import finite

if TYPE_CHECKING:
    from vexsim.app.jobs import Report
    from vexsim.calibration.log import RobotLog
    from vexsim.calibration.session import Run
    from vexsim.config.robot import RobotConfig

PRACTICE_LIMIT_S = 1200.0  # simulated seconds a practice session may take, at most
PRACTICE_CHUNK_S = 5.0  # it's run this much at a time, to say how it's going
CHECK_PLOTS = ("paths.png", "apart.png", "readings.png")
REPORT_PLOTS = {  # the fit's plots (calibration/report.py), as the page names them
    "free_spin.png": "The free spin: logged against simulated, before the fit and after",
    "held_out.png": "The held-out run: logged against simulated, with what the fit found",
    "distance.png": "The distance sweeps: what each sensor read, against what it should have",
}
_RESULTS: dict[tuple, str] = {}  # each run's result line, by its log's file, its state, the config


def _relative(root: Path, path: Path) -> str:
    import os

    return Path(os.path.relpath(Path(path).resolve(), Path(root).resolve())).as_posix()


def digest(text: str) -> str:
    """A config's text, as the fit saw it: whether it's changed since."""
    return hashlib.sha1(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


# --- the plan and the program -----------------------------------------------------------------


def program_job(params: dict, report: Report) -> dict:
    """``vexsim calibration program``: plan the session for the robot on the field, and write
    the program and the plan (its maps) into the folder. Params: ``robot``, ``field`` and
    ``folder`` (absolute), ``root`` (the workspace's), ``margin``, ``force``, ``workers``."""
    from vexsim.calibration.fit import worker_count
    from vexsim.calibration.plan import MARGIN_IN, make_plan, write_plan
    from vexsim.calibration.program import ProgramError, check_folder, write_program
    from vexsim.config import load_field, load_robot

    config, field = load_robot(params["robot"]), load_field(params["field"])
    folder, root = Path(params["folder"]), Path(params["root"])
    force = bool(params.get("force"))
    try:
        check_folder(folder, force=force)
    except ProgramError as exc:
        raise ValueError(str(exc)) from None
    margin = float(params.get("margin") or MARGIN_IN)
    plan = make_plan(
        config, field, margin=margin, workers=worker_count(params.get("workers")), progress=report
    )
    for path, state in write_program(config, plan, folder, force=force):
        report(f"{_relative(root, path)}: {state}")
    write_plan(plan, folder / "plan")
    for line in plan.text().splitlines():
        report(line)
    return {"folder": _relative(root, folder), "missing": [t.title for t in plan.missing]}


def program_info(root: Path, folder: Path) -> dict:
    """``CalibrationProgram``: what's in a program's folder: whether the program and a PROS
    project are there, and the plan it was written with (its tests, in the menu's order, each
    with how many runs it takes, where it goes and its map)."""
    from vexsim.calibration.program import DRIVE_RUNS, MARK, RUNS

    main = folder / "src" / "main.cpp"
    written = main.is_file() and MARK in main.read_text(encoding="utf-8", errors="replace")
    out: dict = {
        "folder": _relative(root, folder),
        "exists": folder.is_dir(),
        "pros_project": (folder / "project.pros").is_file(),
        "written": written,
        "plan": None,
    }
    try:
        plan = json.loads((folder / "plan" / "plan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    tests = []
    for entry in plan.get("session", []):
        key, kind = entry["key"], entry.get("kind", "on_hand")
        spot = entry.get("spot")
        image = folder / "plan" / entry["map"] if entry.get("map") else None
        tests.append(
            {
                "number": entry["number"],
                "key": key,
                "title": entry["title"],
                "kind": kind,
                "runs": RUNS.get(key, DRIVE_RUNS if kind == "drive" else 1),
                "place": spot["place"] if spot else [],
                "clearance_in": spot["clearance_in"] if spot else None,
                "map": _relative(root, image) if image is not None and image.is_file() else None,
                "scale": entry.get("scale"),
            }
        )
    out["plan"] = {
        "robot": plan.get("robot", ""),
        "field": plan.get("field", ""),
        "margin_in": plan.get("margin_in", 0.0),
        "tests": tests,
        "missing": plan.get("missing", []),
    }
    return out


def _practice_plan(folder: Path) -> SimpleNamespace:
    """What the simulated student needs of a program's plan (plan/plan.json): each test that
    needs room, with its key and its spot's pose."""
    try:
        plan = json.loads((folder / "plan" / "plan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError(f"{folder.name} has no plan: write the program first") from None
    tests = [
        SimpleNamespace(
            key=entry["key"],
            spot=SimpleNamespace(
                pose=(entry["spot"]["x_in"], entry["spot"]["y_in"], entry["spot"]["heading_deg"])
            ),
        )
        for entry in plan["session"]
        if entry.get("spot")
    ]
    return SimpleNamespace(tests=tests, keys=[entry["key"] for entry in plan["session"]])


def practice_job(params: dict, report: Report) -> dict:
    """A practice session: the program, built for the laptop, run in vexsim by the simulated
    student (``vexsim.calibration.student``) through ``tests`` (default: every one), on the
    robot as a real one is (``unlike``: not quite as its config says) or as configured; its
    logs collected into the session, marked as practice. Params: ``robot``, ``field``,
    ``program`` and ``session`` (absolute), ``tests``, ``unlike``."""
    from vexsim.bridge.build import build_project
    from vexsim.bridge.program import CppProgram
    from vexsim.calibration.session import Session, card_logs, collect
    from vexsim.calibration.student import Student, unlike
    from vexsim.config import load_field, load_robot
    from vexsim.runtime.simulation import Simulation

    config, field = load_robot(params["robot"]), load_field(params["field"])
    program = Path(params["program"])
    plan = _practice_plan(program)
    session = Session.open(params["session"])
    if session.runs and not session.practice:
        raise ValueError(
            f"{session.folder.name} has a robot's runs: practice in a session of its own"
        )
    tests = [t for t in (params.get("tests") or plan.keys) if t in plan.keys]
    if not tests:
        raise ValueError("no tests to practice: the plan has none of those")
    report("building the program for the simulator")
    executable = build_project(program, log=report).executable
    real = unlike(config) if params.get("unlike", True) else config
    without = field.model_copy(
        update={"elements": tuple(e for e in field.elements if e.type != "piece")}
    )
    with tempfile.TemporaryDirectory(prefix="vexsim-practice-") as card:
        student = Student(plan, config, tests)
        sim = Simulation(
            real,
            program=CppProgram(executable, env={"VEXSIM_SD_DIR": card}),
            field=without,
            input_source=student,
            start=student.start,
            echo=None,
        )
        student.attach(sim)
        report(f"the simulated student runs {len(tests)} tests: {', '.join(tests)}")
        sim.start("driver")
        logged = 0
        try:
            for _ in range(int(PRACTICE_LIMIT_S / PRACTICE_CHUNK_S)):
                if sim.run_until_finished(PRACTICE_CHUNK_S):
                    break
                for run in student.runs[logged:]:
                    report(f"{run.name}: {run.test}")
                logged = len(student.runs)
                report.progress(len(tests) - len(student.todo), len(tests))
            else:
                raise RuntimeError("the practice session didn't finish")
        finally:
            sim.close()
        for run in student.runs[logged:]:
            report(f"{run.name}: {run.test}")
        if student.error:
            raise RuntimeError(f"the simulated student got stuck: {student.error}")
        report.progress(len(tests), len(tests))
        session.practice = True
        added = collect(session, card_logs(Path(card)), say=report)
    session.save()
    return {"added": len(added), "session": session.folder.name}


# --- collecting -------------------------------------------------------------------------------


def collect_logs(folder: Path, source: Path | None) -> dict:
    """The calibration logs on the brain's card (found, with ``source`` None) or in a folder,
    copied into the session (``vexsim calibration collect``): where they came from, how many
    are new, and what collecting said of each."""
    from vexsim.calibration.session import Session, card_logs, collect, find_card

    session = Session.open(folder)
    if session.practice:
        raise ValueError(
            f"{folder.name} is a practice session (the simulated robot's): collect the real "
            "robot's logs into a session of its own"
        )
    if source is None:
        card = find_card()
        if card is None:
            raise ValueError(
                "no SD card with vexsim's logs found: put the brain's card in this computer (or "
                "copy its files into a folder, and collect from that)"
            )
    else:
        card = source
        if not card.is_dir():
            raise ValueError(f"{card} isn't a folder")
    logs = card_logs(card)
    if not logs:
        raise ValueError(f"no logs in {card} (vexsim_0001_device_check.csv and so on)")
    said: list[str] = []
    added = collect(session, logs, say=said.append)
    return {"card": str(card), "added": len(added), "messages": said}


def usb_job(params: dict, report: Report) -> dict:
    """Collect over USB (no card in the brain): ``pros terminal`` (or ``command``) until the
    job is stopped, each log the program prints added to the session as it ends. Params:
    ``session`` (absolute), ``command``."""
    from vexsim.calibration.session import Session, from_usb

    session = Session.open(params["session"])
    if session.practice:
        raise ValueError(f"{session.folder.name} is a practice session: use one of its own")
    command = params.get("command") or None
    added = from_usb(session, command, say=report, stop=report.stopping)
    return {"added": len(added), "session": session.folder.name}


def set_use(folder: Path, file: str, use: bool) -> None:
    """Leave a run out of the fit, or put it back (its ``use`` in session.yaml)."""
    from vexsim.calibration.session import Session

    session = Session.open(folder)
    run = next((r for r in session.runs if r.file == file), None)
    if run is None:
        raise ValueError(f"{folder.name} has no run {file}")
    run.use = bool(use)
    session.save()


# --- each run's result ------------------------------------------------------------------------


def session_state(root: Path, folder: Path, config: RobotConfig | None) -> dict:
    """``CalibrationSessionState``: the session's runs in the order they were made, each with
    a line of what it measured (``run_result``), and its latest fit (report/report.json)."""
    from vexsim.calibration.session import Session

    session = Session.open(folder)
    key = None if config is None else digest(config.model_dump_json())
    runs = []
    for run in sorted(session.runs, key=lambda r: (r.started_ms, r.file)):
        path = session.runs_dir / run.file
        runs.append({**_run_dict(run), "result": _cached_result(path, run, config, key)})
    report = None
    try:
        report = json.loads((folder / "report" / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {
        "path": _relative(root, folder),
        "name": folder.name,
        "exists": session.file.is_file(),
        "robot": session.robot,
        "field": session.field_name,
        "practice": session.practice,
        "runs": runs,
        "report": report,
    }


def _run_dict(run: Run) -> dict:
    return {
        "file": run.file,
        "test": run.test,
        "run": run.run,
        "name": run.name,
        "started_ms": run.started_ms,
        "ended": run.ended,
        "quality": run.quality,
        "use": run.use,
        "warnings": list(run.warnings),
    }


def _cached_result(path: Path, run: Run, config: RobotConfig | None, key: str | None) -> str:
    try:
        stat = path.stat()
    except OSError:
        return "its log is missing"
    cached = (str(path), stat.st_mtime_ns, stat.st_size, key)
    if cached not in _RESULTS:
        if len(_RESULTS) > 2000:
            _RESULTS.clear()
        _RESULTS[cached] = run_result(path, run, config)
    return _RESULTS[cached]


def run_result(path: Path, run: Run, config: RobotConfig | None) -> str:
    """What a run measured, in a line, as the brain's screen said it: the device check's
    verdict, the motors' speed free, the IMU's drift and its turns, how far the wheels say the
    push went, a driving run's time, top speed and turn."""
    from vexsim.calibration.log import RobotLog

    try:
        log = RobotLog.read(path)
    except (OSError, ValueError) as exc:
        return f"its log doesn't read: {exc}"
    if run.ended != "finished":
        return run.ended
    test = run.test
    try:
        if test == "device_check":
            if log.info.get("check") == "passed":
                return "passed: every device answers, turns and counts as the config says"
            fix = [t.removeprefix("to fix: ") for _, t in log.marks if t.startswith("to fix")]
            return "to fix: " + "; ".join(fix) if fix else "failed"
        if test == "free_spin":
            return _free_spin(log, config)
        if test == "imu_still":
            turned, seconds = _imu_turn(log)
            return f"the IMU drifted {turned:+.2f} deg in {seconds:.0f} s"
        if test == "imu_turns":
            turned, _ = _imu_turn(log)
            off = (abs(turned) / 3600 - 1) * 100
            return (
                f"the IMU read {abs(turned):.1f} deg for 3600: "
                f"{abs(off):.2f}% {'more' if off > 0 else 'less'} than it turned"
            )
        if test == "push":
            return _push(log, config)
        return _drive(log, config)
    except (KeyError, ValueError, IndexError, StopIteration):
        return run.quality


def _imu_turn(log: RobotLog) -> tuple[float, float]:
    """How far the IMU turned over the log (deg, as PROS reads it), and in how long (s)."""
    port = log.ports("imu")[0]
    rotation = log[f"imu{port}_deg"]
    known = np.flatnonzero(np.isfinite(rotation))
    if len(known) < 2:
        raise ValueError("no IMU readings")
    seconds = (log.time_ms[known[-1]] - log.time_ms[known[0]]) / 1000
    return float(rotation[known[-1]] - rotation[known[0]]), float(seconds)


def _drive_motors(config: RobotConfig | None, log: RobotLog) -> list[tuple[int, float]]:
    """The drive's motors the log has: port, and the wheels' inches per motor turn."""
    if config is None:
        return [(port, math.nan) for port in log.ports("m")]
    out = []
    for gear in config.drivetrain.gearing.values():
        wheel = config.drivetrain.wheel(gear.wheels[0])
        per_rev = math.pi * wheel.diameter_in * gear.speed_ratio
        out += [(abs(p), per_rev) for p in gear.motors if abs(p) in log.ports("m")]
    return out


def _free_spin(log: RobotLog, config: RobotConfig | None) -> str:
    marks = sorted(log.marks)
    begin = next(t for t, text in marks if text == "12 V")
    end = next((t for t, text in marks if t > begin), log.time_ms[-1])
    rows = (log.time_ms > (begin + end) / 2) & (log.time_ms <= end)
    motors = _drive_motors(config, log)
    speeds = [float(np.nanmedian(np.abs(log[f"m{p}_rpm"][rows]))) for p, _ in motors]
    return f"at 12 V the drive motors ran {np.mean(speeds):.0f} rpm, free"


def _push(log: RobotLog, config: RobotConfig | None) -> str:
    length = float(log.info["length_in"])
    motors = [(p, per_rev) for p, per_rev in _drive_motors(config, log) if math.isfinite(per_rev)]
    if not motors:
        return f"pushed {length:.0f} in"
    inches = float(
        np.mean(
            [
                abs(np.nanmax(log[f"m{p}_deg"]) - np.nanmin(log[f"m{p}_deg"])) / 360 * per_rev
                for p, per_rev in motors
            ]
        )
    )
    off = (inches / length - 1) * 100
    return (
        f"the wheels say {inches:.1f} in for {length:.0f} in: "
        f"{abs(off):.1f}% {'more' if off > 0 else 'less'}"
    )


def _drive(log: RobotLog, config: RobotConfig | None) -> str:
    seconds = (log.time_ms[-1] - log.time_ms[0]) / 1000
    parts = [f"{seconds:.1f} s"]
    motors = [(p, per_rev) for p, per_rev in _drive_motors(config, log) if math.isfinite(per_rev)]
    if motors:
        speed = np.nanmean(
            [np.abs(log[f"m{p}_rpm"]) * per_rev / 60 for p, per_rev in motors], axis=0
        )
        parts.append(f"wheels up to {np.nanmax(speed):.0f} in/s")
    if log.ports("imu"):
        turned, _ = _imu_turn(log)
        parts.append(f"turned {abs(turned):.0f} deg")
    return ", ".join(parts)


# --- the fit ----------------------------------------------------------------------------------


def fit_job(params: dict, report: Report) -> dict:
    """``vexsim calibrate ROBOT SESSION``: fit the session, write its report, and
    report/report.json (``SessionReport``, what the page shows). Params: ``robot`` (absolute)
    and ``robot_name`` (the workspace's), ``session``, ``field`` (absolute; None: none, the
    distance sweeps skipped), ``workers``."""
    from vexsim.calibration.fit import worker_count
    from vexsim.calibration.report import write_report
    from vexsim.calibration.session import Session
    from vexsim.calibration.session_fit import SessionError, calibrate
    from vexsim.config import load_field, load_robot

    robot = Path(params["robot"])
    text = robot.read_text(encoding="utf-8")
    config = load_robot(robot)
    session = Session.open(params["session"])
    if not session.runs:
        raise ValueError(f"{session.folder.name} has no runs yet: collect them first")
    field = load_field(params["field"]) if params.get("field") else None
    try:
        found = calibrate(
            config, session, field, workers=worker_count(params.get("workers")), say=report
        )
    except SessionError as exc:
        raise ValueError(str(exc)) from None
    when = datetime.date.today().isoformat()
    folder = session.folder / "report"
    _, writes = write_report(config, found, folder, when=when)
    data = report_data(found, writes, when, params.get("robot_name") or robot.name, digest(text))
    data["plots"] = [
        {"title": title, "file": name}
        for name, title in REPORT_PLOTS.items()
        if (folder / name).is_file()
    ]
    (folder / "report.json").write_text(json.dumps(finite(data), indent=1) + "\n", encoding="utf-8")
    held = found.held_out
    return {
        "session": session.folder.name,
        "changes": len(writes),
        "matches": None if held is None else held.matches,
    }


def report_data(found, writes, when: str, robot_file: str, config_digest: str) -> dict:
    """A session's fit as the page shows it (``SessionReport``)."""
    from vexsim.calibration.feedforward import drive_section
    from vexsim.calibration.fit import UNITS
    from vexsim.calibration.report import why_not

    def number(value) -> float | None:
        return float(value) if value is not None and math.isfinite(value) else None

    steps = []
    for step in found.steps:
        steps.append(
            {
                "name": step.name,
                "runs": list(step.runs),
                "skipped": step.skipped,
                "values": [
                    {
                        "key": v.key,
                        "before": number(v.before),
                        "after": number(v.after),
                        "uncertainty": number(v.uncertainty),
                        "tolerance": number(v.tolerance),
                        "pinned": v.pinned,
                        "note": v.note,
                        "why_not": why_not(v),
                    }
                    for v in step.values
                ],
                "rms": [
                    {
                        "group": group,
                        "unit": UNITS.get(group, ""),
                        "before": number(b),
                        "after": number(a),
                    }
                    for group, (b, a) in step.rms.items()
                ],
                "notes": list(step.notes),
                "warnings": list(step.warnings),
            }
        )
    held = found.held_out
    return {
        "robot": found.robot,
        "robot_file": robot_file,
        "config_digest": config_digest,
        "fitted": when,
        "session": found.session.name,
        "steps": steps,
        "held_out": None
        if held is None
        else {
            "run": held.run,
            "matches": held.matches,
            "groups": [
                {
                    "group": group,
                    "unit": UNITS.get(group, ""),
                    "rms": number(rms),
                    "noise": number(held.noise.get(group)),
                }
                for group, rms in held.rms.items()
            ],
        },
        "drive": None if found.drive is None else found.drive.describe(),
        "drive_section": None if found.drive is None else drive_section(found.drive),
        "changes": [
            {
                "location": w.location,
                "value": w.value,
                "key": w.value_of.key if w.value_of is not None else w.location,
            }
            for w in writes
        ],
        "warnings": list(found.warnings),
        "plots": [],
    }


def apply_session(folder: Path, text: str) -> tuple[str, int]:
    """A robot config's text with what the session's fit found written in (as ``vexsim
    calibrate --apply`` writes it, its comments kept): the text, and how many changes. Raises
    ValueError if the session hasn't been fitted, found nothing to change, or the config has
    changed since its fit (the changes' places in it would be guesses)."""
    from vexsim.calibration.report import Write, apply_changes

    try:
        data = json.loads((folder / "report" / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError(f"{folder.name} hasn't been fitted yet: fit it first") from None
    if digest(text) != data.get("config_digest"):
        raise ValueError(
            f"the robot's config has changed since {folder.name} was fitted (on "
            f"{data.get('fitted')}): fit the session again, then apply what it finds"
        )
    writes = [Write(c["location"], c["value"]) for c in data.get("changes", [])]
    if not writes:
        raise ValueError("the fit found nothing to change: the logs agree with the config")
    return apply_changes(text, writes, folder.name, datetime.date.today().isoformat()), len(writes)


# --- the autonomous check ---------------------------------------------------------------------


def check_job(params: dict, report: Report) -> dict:
    """``vexsim calibration check-auton``, kept with the results (``AutonCheckResult``).
    Params: ``robot``, ``field``, ``program`` and ``logs`` (absolute), their workspace names
    (``robot_name``, ``field_name``, ``program_name``, ``log_names``), ``ends`` (each log's tape
    marks), ``routine``, ``seeds``, ``max_distance_in`` and ``max_heading_deg`` (None: the
    team's, or vexsim's), ``root`` (the workspace's), ``results`` (where results go),
    ``workers``."""
    import shutil

    from vexsim.app import results
    from vexsim.calibration.auton import AutonError, check_auton, load_marks, write_report
    from vexsim.calibration.fit import worker_count
    from vexsim.config import load_field, load_robot

    try:
        marks = load_marks(
            params["root"],
            max_distance_in=params.get("max_distance_in"),
            max_heading_deg=params.get("max_heading_deg"),
        )
        seeds = int(params.get("seeds") or 3)
        check = check_auton(
            params["robot"],
            params["field"],
            params["program"],
            params["logs"],
            params["ends"],
            marks=marks,
            routine=params.get("routine") or None,
            seeds=seeds,
            workers=min(worker_count(params.get("workers")), seeds),
            say=report,
        )
    except AutonError as exc:
        raise ValueError(str(exc)) from None
    store = Path(params["results"])
    result_id, folder = results.new_result(store)
    try:
        write_report(check, load_robot(params["robot"]), load_field(params["field"]), folder)
        verdict = "passes" if check.passed else "fails"
        runs = len(check.runs)
        about = results.write_result(
            folder,
            "checks",
            f"{check.routine} against {runs} real run{'s' if runs != 1 else ''}",
            f"{verdict} at {marks.max_distance_in:g} in, {marks.max_heading_deg:g} degrees",
            check_data(check, params, folder),
        )
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    results.prune(store)
    return {"id": about["id"], "passed": check.passed}


def check_data(check, params: dict, folder: Path) -> dict:
    """An autonomous check as the page shows it."""

    def pose(value) -> list[float] | None:
        return None if value is None else [round(float(v), 2) for v in value]

    m = check.marks
    names = params.get("log_names") or [Path(p).name for p in params["logs"]]
    return {
        "routine": check.routine,
        "robot": params.get("robot_name"),
        "field": params.get("field_name"),
        "program": params.get("program_name"),
        "start": pose(check.start),
        "marks": {
            "max_distance_in": m.max_distance_in,
            "max_heading_deg": m.max_heading_deg,
            "source": m.source,
        },
        "passed": check.passed,
        "failures": list(check.failures),
        "warnings": list(check.warnings),
        "runs": [
            {
                "log": names[k] if k < len(names) else run.file,
                "end": params["ends"][k] if k < len(params["ends"]) else None,
                "measured": None if run.end is None else pose(run.end.pose),
                "end_off": pose(run.end_off),
                "run_rms_in": None if run.run_rms_in is None else round(run.run_rms_in, 2),
                "parted_s": None if run.parted_s is None else round(run.parted_s, 2),
            }
            for k, run in enumerate(check.runs)
        ],
        "sims": [{"seed": s.seed, "end": pose(s.end)} for s in check.sims],
        "sim_end": pose(check.sim_end),
        "end_off": pose(check.end_off),
        "run_rms_in": None if check.run_rms_in is None else round(check.run_rms_in, 2),
        "sim_spread": pose(check.sim_spread),
        "real_spread": pose(check.real_spread),
        "plots": [name for name in CHECK_PLOTS if (folder / name).is_file()],
    }


def pass_marks(root: Path) -> dict:
    """``PassMarks``: the team's (the nearest .vexsim/calibration.yaml), else vexsim's."""
    from vexsim.calibration.auton import load_marks, marks_file

    marks = load_marks(root)
    found = marks_file(root)
    return {
        "max_distance_in": marks.max_distance_in,
        "max_heading_deg": marks.max_heading_deg,
        "source": marks.source,
        "file": None if found is None else str(found),
        "warnings": marks.warnings(),
    }


def save_marks(root: Path, distance: float, heading: float) -> dict:
    """Set the team's pass marks in the workspace's .vexsim/calibration.yaml, in place (its
    comments and whatever else it says kept); the marks as they now are."""
    import yaml

    from vexsim.app.configs import PatchError
    from vexsim.app.yamledit import Change, apply
    from vexsim.calibration.auton import MARKS_FILE

    if not (distance > 0 and heading > 0):
        raise ValueError("the pass marks must be above 0")
    path = Path(root) / MARKS_FILE
    marks = {"max_distance_in": float(distance), "max_heading_deg": float(heading)}
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    text = None
    if old.strip():
        try:
            text = apply(old, [Change("set", key, value) for key, value in marks.items()])
        except PatchError:  # not a mapping it can change in place: written again, as data
            try:
                loaded = yaml.safe_load(old)
            except yaml.YAMLError:
                loaded = None
            data = {**(loaded if isinstance(loaded, dict) else {}), **marks}
            text = yaml.safe_dump(data, sort_keys=False)
    if text is None:
        head = "# The team's pass marks for the autonomous check (vexsim calibration check-auton)\n"
        text = head + yaml.safe_dump(marks, sort_keys=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return pass_marks(root)


def end_found(config: RobotConfig, field, text: str) -> dict:
    """``EndFound``: where two corners' tape marks put the robot, or why they can't."""
    from vexsim.calibration.auton import MISFIT_IN, AutonError, end_pose, parse_end

    try:
        corners = parse_end(text)
        found = end_pose(config, field, corners)
    except AutonError as exc:
        raise ValueError(str(exc)) from None
    warning = None
    if found.misfit_in > MISFIT_IN:
        warning = (
            f"the two marks are {found.misfit_in:.1f} in further apart, or nearer, than those "
            "corners are: measure again, or check which corners they are"
        )
    return {
        "x": round(found.x, 2),
        "y": round(found.y, 2),
        "heading": round(found.heading, 1),
        "misfit_in": round(found.misfit_in, 2),
        "corners": [c.name for c in corners],
        "warning": warning,
    }

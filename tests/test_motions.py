"""vexsim's own motions (PLAN.md 13.4): the C++ library's plans (bridge/cpp/motions) against
the Python they're ported from, the drive model they drive with (calibration/feedforward.py),
arcs and RAMSETE paths as route steps (read, checked, mirrored, run and exported), and a route
with both that runs in the simulator and, exported, drives the same. The C++ tests need g++,
and the runs LemLib's source."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys

import pytest

from tests.conftest import ROOT
from tests.test_autons import where_it_drove
from tests.test_routes import HEAD, route_file, team_project
from vexsim.algorithms.control.trajectory import Limits, plan_arc, plan_path
from vexsim.app.autons import GENERATED, LIBRARY, export, plan_export
from vexsim.app.routes import (
    label,
    load_route,
    mirror_text,
    read_route,
    route_drive,
    run_route,
    runner_input,
)
from vexsim.calibration.feedforward import characterize, drive_section, fit, fit_log
from vexsim.calibration.routine import Step, run_routine, standard_routine
from vexsim.config.loader import load_robot

HARNESS = ROOT / "tests" / "cpp" / "trajectory" / "main.cpp"
TEMPLATE = ROOT / "examples" / "pros_projects" / "lemlib_template"
ROBOTS = ROOT / "examples" / "robots"
LIMITS = Limits(64.1, 221.3, 12.9, 10.0)

# --- the C++ plans as the Python does -------------------------------------------------------------

ARCS = [  # x, y, heading, radius, turn, forwards, speed
    (0.0, 0.0, math.pi / 2, 18.0, -math.pi / 2, True, 64.1),
    (48.0, 0.0, 2.5, 12.0, math.pi / 2, False, 30.0),
    (-10.0, 5.0, -1.0, 30.0, 2 * math.pi, True, 50.0),  # a whole circle
    (0.0, 0.0, 0.0, 5.0, 0.0, True, 50.0),  # no turn: nowhere to go
]
PATHS = [  # x, y, heading, points, forwards, end heading, speed
    (0.0, 0.0, math.pi / 2, [(24.0, 24.0), (48.0, 0.0)], True, None, 64.1),
    (50.0, 0.0, 0.0, [(36.0, 12.0), (24.0, 36.0)], False, None, 64.1),
    (-48.0, -24.0, 0.3, [(0.0, -24.0), (24.0, 0.0), (24.0, 24.0)], True, math.pi, 40.0),
    (0.0, 0.0, 0.0, [(0.0, 0.0), (36.0, 0.0), (36.0, 0.0)], True, None, 64.1),  # repeats
]


def test_the_cpp_plans_as_the_python_does(cache_dir, tmp_path):
    """vexsim/trajectory.hpp and algorithms/control/trajectory.py, the same plans to within
    rounding (the maker's planner, src/trajectory.ts, is held to the Python by Vitest)."""
    from vexsim.bridge.build import MOTIONS_INCLUDE, find_toolchain

    exe = tmp_path / ("plans.exe" if sys.platform == "win32" else "plans")
    command = [find_toolchain().cxx, "-std=gnu++17", "-O2", f"-I{MOTIONS_INCLUDE}", str(HARNESS)]
    subprocess.run([*command, "-o", str(exe)], check=True, capture_output=True)
    lines, expected = [], []
    limits = f"{LIMITS.max_velocity} {LIMITS.max_accel} {LIMITS.max_lateral_accel} 10"
    for x, y, h, r, turn, forwards, speed in ARCS:
        lines.append(f"arc {x!r} {y!r} {h!r} {r!r} {turn!r} {int(forwards)} {speed!r} {limits}")
        expected.append(plan_arc(x, y, h, r, turn, forwards, speed, LIMITS))
    for x, y, h, points, forwards, end, speed in PATHS:
        words = " ".join(f"{px!r} {py!r}" for px, py in points)
        ends = "nan" if end is None else repr(end)
        lines.append(f"path {x!r} {y!r} {h!r} {int(forwards)} {ends} {speed!r} {limits} {words}")
        expected.append(plan_path(x, y, h, points, forwards, end, speed, LIMITS))
    out = subprocess.run(
        [str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, check=True
    ).stdout.splitlines()
    plans, at = [], 0
    while at < len(out):
        count = int(out[at].split()[1])
        plans.append([[float(v) for v in row.split()] for row in out[at + 1 : at + 1 + count]])
        at += 1 + count
    assert len(plans) == len(expected)
    for made, python in zip(plans, expected, strict=True):
        assert len(made) == len(python)
        for row, state in zip(made, python, strict=True):
            want = [state.t, state.s, state.x, state.y, state.heading]
            want += [state.v, state.omega, state.a, state.alpha]
            assert row == pytest.approx(want, rel=1e-9, abs=1e-9)


def test_a_plan_keeps_to_its_limits_and_ends_where_it_goes():
    arc = plan_arc(0, 0, math.pi / 2, 18, -math.pi / 2, True, 64.1, LIMITS)
    end = arc[-1]
    assert (end.x, end.y, end.heading, end.v) == pytest.approx((18, 18, 0, 0), abs=1e-9)
    assert max(s.v for s in arc) == pytest.approx(math.sqrt(12.9 * 18))  # held to its grip
    assert all(abs(s.t - k * 0.01) < 1e-12 for k, s in enumerate(arc[:-1]))  # every 10 ms
    path = plan_path(0, 0, math.pi / 2, [(24, 24), (48, 0)], True, None, 40, LIMITS)
    assert (path[-1].x, path[-1].y) == pytest.approx((48, 0), abs=1e-9)
    assert path[-1].heading == pytest.approx(-math.pi / 4)  # the way its last stretch goes
    for s in path:  # the outside wheels, within the drive's top speed; the robot, within 40
        assert abs(s.v) <= 40 + 1e-9 and abs(s.v) + abs(s.omega) * 5 <= 64.1 + 1e-6
    back = plan_path(0, 0, 0, [(-24, 0)], False, None, 40, LIMITS)
    assert back[-1].x == pytest.approx(-24) and min(s.v for s in back) < -30
    assert back[-1].heading == pytest.approx(0, abs=1e-9)  # still facing +x


# --- the drive model ------------------------------------------------------------------------------


def test_the_drive_model_is_worked_out_from_the_robot_and_fitted_to_its_log():
    robot = load_robot(ROBOTS / "1239e_2026-27.yaml")
    model = characterize(robot)  # driven open-loop in the simulator, and fitted
    assert model.r2 > 0.99 and model.turned
    assert 0.5 < model.kS < 2 and model.kV == pytest.approx(12 / 87, rel=0.15)
    assert 0.01 < model.kA < 0.05 and model.kT > 0.5 and model.kP == pytest.approx(4 * model.kV)
    rated = 450 / 60 * math.pi * 3.25  # its wheels at the motors' rated speed
    assert model.top_speed == pytest.approx(min((12 - model.kS) / model.kV, rated), abs=0.1)
    assert model.max_velocity == pytest.approx(0.8 * model.top_speed, abs=0.1)
    # its middle wheels hold it in a turn: half their sideways grip (omni rollers, 0.2)
    assert model.max_lateral_accel == pytest.approx(0.5 * 0.2 * 2 / 6 * 386.09, abs=0.1)
    # a robot log fits the same model: the calibration routine's (spins and arcs in it)
    logged = fit(robot, run_routine(robot, standard_routine(robot), noise="default"))
    assert logged.turned and logged.kV == pytest.approx(model.kV, rel=0.05)
    assert logged.kS == pytest.approx(model.kS, abs=0.3)
    assert logged.kT == pytest.approx(model.kT, abs=0.3)
    # a log that doesn't turn the robot says nothing of kT
    straight = [Step("settle", 0.3), Step("a", 1.0, forward=0.3), Step("b", 1.0, forward=0.7)]
    flat = fit(robot, run_routine(robot, [*straight, Step("c", 1.0, forward=-0.5)]))
    assert not flat.turned and flat.kT == 0
    assert drive_section(flat) == f"drive: {{kS: {flat.kS:g}, kV: {flat.kV:g}, kA: {flat.kA:g}}}"
    assert drive_section(logged).endswith(f", kT: {logged.kT:g}}}")
    # traction wheels in the middle hold a turn far better; an H-drive's strafe wheel doesn't
    # scrub; a mecanum drive has no left and right sides for the model
    assert characterize(load_robot(ROBOTS / "traction_6m.yaml")).max_lateral_accel > 60
    assert characterize(load_robot(ROBOTS / "hdrive_5m.yaml")).kT < 0.3
    assert fit_log(load_robot(ROBOTS / "mecanum_4m.yaml"), None) is None


# --- arcs and RAMSETE paths as route steps ------------------------------------------------------

STEPS = (
    "  - {move_arc: [18, 90], timeout: 1500}\n"
    "  - {ramsete: [[24, 24], [48, 0]], timeout: 3000, forwards: false, max_velocity: 40, "
    "end_heading: 90}\n"
)


def test_arcs_and_paths_read_with_each_problem_at_its_place():
    data = {"name": "r", "robot": "x.yaml", "start": [0, 0, 0], "steps": []}

    def read(*steps, **top):
        return read_route({**data, "steps": list(steps), **top})

    route, issues = read(
        {"move_arc": [18, -45], "timeout": 1000, "max_accel": 100},
        {"ramsete": [[1, 2], [3, 4.5]], "timeout": 2000, "end_heading": -90, "async": False},
        drive={"kS": 1, "kT": 0, "max_lateral_accel": 20},
    )
    assert issues == [] and route.own_motions
    arc, path = route.steps
    assert (arc.target, arc.options) == ((18, -45), (("max_accel", 100),))
    assert path.target == (1, 2, 3, 4.5) and path.points == [(1, 2), (3, 4.5)]
    assert route.drive == {"kS": 1, "kT": 0, "max_lateral_accel": 20}
    assert label(arc) == "move_arc -45°, radius 18 in max_accel 100"
    assert label(path) == "ramsete (1, 2) (3, 4.5) end_heading -90 not async"
    _, issues = read(
        {"move_arc": [0, 90], "timeout": 1000},
        {"move_arc": [10, 0], "timeout": 1000, "max_velocity": 0},
        {"ramsete": [], "timeout": 1000},
        {"ramsete": [[1, 2], [3]], "timeout": 1000, "lead": 0.5},
        {"ramsete": [1, 2], "timeout": 1000},
        drive={"kV": 0, "kS": -1, "kQ": 1},
    )
    assert [(i.location, i.message) for i in issues] == [
        ("drive.kV", "must be more than 0"),
        ("drive.kS", "must be 0 or more"),
        ("drive.kQ", "unknown key 'kQ'"),
        ("steps[0].move_arc[0]", "the radius must be more than 0 (inches)"),
        ("steps[1].move_arc[1]", "must turn some way: degrees, clockwise positive"),
        ("steps[1].max_velocity", "must be more than 0"),
        ("steps[2].ramsete", "must be the points it goes through: [[x, y], ...] (inches)"),
        ("steps[3].lead", "unknown key 'lead' for ramsete"),
        ("steps[3].ramsete[1]", "must be a point: [x, y] (inches)"),
        ("steps[4].ramsete[0]", "must be a point: [x, y] (inches)"),
        ("steps[4].ramsete[1]", "must be a point: [x, y] (inches)"),
    ]


def test_arcs_and_paths_are_checked_and_run_with_the_routes_drive_model(tmp_path):
    project = team_project(tmp_path)
    path = route_file(project, HEAD + STEPS + "  - {ramsete: [[100, 0]], timeout: 2000}\n")
    checked = load_route(path)
    assert [(i.location, i.message) for i in checked.issues] == [
        ("steps[2].ramsete[0]", "(100, 0) is off the field")
    ]
    robot = checked.robot
    model = characterize(robot)
    assert checked.drive == model  # vexsim's, from the robot
    assert runner_input(checked.route, checked.functions, checked.drive).splitlines() == [
        "vexsim-route 1",
        "start -48 -24 0",
        f"drive {model.kS:.10g} {model.kV:.10g} {model.kA:.10g} {model.kT:.10g} "
        f"{model.kP:.10g} {model.max_velocity:.10g} {model.max_accel:.10g} "
        f"{model.max_lateral_accel:.10g}",
        "1 move_arc 18 90 1500",
        "2 ramsete 24 24 48 0 3000 forwards=false max_velocity=40 end_heading=90",
        "3 ramsete 100 0 2000",
    ]
    with pytest.raises(ValueError, match="need the drive model"):
        runner_input(checked.route, checked.functions)
    # the route's drive: section in place of vexsim's: the limits follow its constants
    route, _ = read_route(
        {"name": "r", "robot": "r.yaml", "start": [0, 0, 0], "drive": {"kV": 0.2, "max_accel": 90}}
    )
    given = route_drive(route, robot)
    assert (given.kS, given.kV, given.kA, given.max_accel) == (model.kS, 0.2, model.kA, 90)
    assert given.top_speed == pytest.approx((12 - model.kS) / 0.2, abs=0.1)
    route, _ = read_route(
        {"name": "r", "robot": "r.yaml", "start": [0, 0, 0], "drive": {"kS": 1, "kV": 0.15}}
    )
    assert route_drive(route, robot).kA == model.kA
    # a robot whose drive has no left and right sides can't drive them
    mecanum = tmp_path / "mecanum.yaml"
    shutil.copy(ROBOTS / "mecanum_4m.yaml", mecanum)
    text = (HEAD + STEPS).replace("../../robot.yaml", "../../mecanum.yaml")
    errors = load_route(route_file(project, text, "mecanum.yaml")).errors
    assert [(i.location, i.message) for i in errors] == [
        (f"steps[{k}].{kind}", f"{kind} drives a differential drive's left and right sides, "
         "and this robot's drivetrain is mecanum")
        for k, kind in ((0, "move_arc"), (1, "ramsete"))
    ]  # fmt: skip


def test_arcs_and_paths_are_mirrored(tmp_path):
    project = team_project(tmp_path)
    path = route_file(project, HEAD + STEPS)
    text, notes = mirror_text(path.read_text(), path, "x")
    assert notes == []
    assert text.splitlines()[-2:] == [
        "  - {move_arc: [18, -90], timeout: 1500}",
        "  - {ramsete: [[-24, 24], [-48, 0]], timeout: 3000, forwards: false, max_velocity: 40, "
        "end_heading: 270}",
    ]
    across, _ = mirror_text(path.read_text(), path, "y")
    assert "{ramsete: [[24, -24], [48, 0]]," in across and "end_heading: 90}" in across


def test_the_server_checks_a_route_with_its_drive_model(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from tests.test_pages import TOKEN
    from vexsim.ui.server import create_app

    project = team_project(tmp_path)
    app = create_app(
        tmp_path, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    model = characterize(load_robot(tmp_path / "robot.yaml"))
    with TestClient(app) as client:
        client.headers["authorization"] = f"Bearer {TOKEN}"
        for text in (HEAD + "  - {wait: 10}\n", HEAD + STEPS + "drive: {kT: 0.5}\n"):
            route_file(project, text)
            check = client.post(
                "/api/route/check", json={"path": "project/routes/test.yaml", "text": text}
            ).json()
            drive = check["drive"]  # what an arc would drive with, before there's one
            assert drive["max_velocity"] == model.max_velocity
            assert drive["kT"] == (0.5 if "kT" in text else model.kT)
        assert check["route"]["drive"] == {"kT": 0.5}
        assert [s["kind"] for s in check["route"]["steps"]] == ["move_arc", "ramsete"]
        assert check["route"]["steps"][1]["target"] == [24, 24, 48, 0]


def test_a_route_with_an_arc_and_a_path_exports_with_the_motion_library(tmp_path):
    project = team_project(tmp_path)
    route_file(project, HEAD + STEPS)
    model = characterize(load_robot(tmp_path / "robot.yaml"))
    plan = plan_export(project)
    assert [(f.path, f.state) for f in plan.files] == [
        (GENERATED, "new"),
        ("include/custom/auton.hpp", "new"),
        *((rel, "new") for rel in LIBRARY),
    ]
    source = plan.files[0].after
    assert '#include "vexsim/motions.hpp"' in source
    body = source[source.index("void test_route() {") :].splitlines()
    assert body[1:6] == [
        "    // vexsim's own motions, with the model of the drive the route was simulated with",
        f"    static vexsim::Motions motions(chassis, {{.kS = {model.kS:g}, .kV = {model.kV:g}, "
        f".kA = {model.kA:g}, .kT = {model.kT:g}, .kP = {model.kP:g}, .maxVelocity = "
        f"{model.max_velocity:g}, .maxAccel = {model.max_accel:g}, .maxLateralAccel = "
        f"{model.max_lateral_accel:g}}});",
        "    chassis.setPose(-48, -24, 0);",
        "    motions.moveArc(18, 90, 1500);",
        "    motions.ramsete({{24, 24}, {48, 0}}, 3000, {.forwards = false, .maxVelocity = 40, "
        ".endHeading = 90});",
    ]
    ours = {rel: change.after for rel, change in ((f.path, f) for f in plan.files[2:])}
    export(project)
    for rel in LIBRARY:
        assert (project / rel).read_text() == ours[rel]
    # the project's own copy, changed, stays: the export says so
    header = project / LIBRARY[0]
    header.write_text(header.read_text() + "// ours\n")
    again = plan_export(project)
    assert [f.path for f in again.files if f.path in LIBRARY] == list(LIBRARY[1:])
    assert all(f.state == "unchanged" for f in again.files)
    assert any(note.startswith(f"{LIBRARY[0]} isn't vexsim's") for note in again.notes)


def test_a_calibration_fits_the_drive_model_to_its_log(tmp_path):
    from vexsim.app.calibrate import calibrate

    found = calibrate(
        {
            "robot": str(ROBOTS / "full_omni_6m.yaml"),
            "log": str(ROOT / "examples" / "logs" / "full_omni_routine.csv"),
            "results": str(tmp_path),
            "compare_only": True,
        },
        lambda text: None,
    )
    drive = json.loads((tmp_path / found["id"] / "result.json").read_text())["drive"]
    assert drive["turned"] and drive["r2"] > 0.99 and drive["section"].startswith("drive: {kS: ")
    assert (tmp_path / found["id"] / "drive.yaml").read_text() == drive["section"] + "\n"


# --- the done-when: a route with a RAMSETE path and an arc runs, and exported, drives the same --


def test_a_route_with_a_path_and_an_arc_runs_and_exported_drives_the_same(
    tmp_path, lemlib_build, in_cache
):
    from vexsim.app.runspec import RunSpec

    project = tmp_path / "template"
    shutil.copytree(TEMPLATE, project, ignore=shutil.ignore_patterns(".vexsim"))
    (project / "routes").mkdir()
    shutil.copy(ROBOTS / "lemlib_example.yaml", tmp_path / "robot.yaml")
    route = route_file(
        project,
        "version: 1\nname: Arcs\nrobot: ../../robot.yaml\nstart: [0, 0, 0]\nsteps:\n"
        "  - {ramsete: [[24, 24], [48, 0]], timeout: 4000, async: false}\n"
        "  - {move_arc: [18, 90], timeout: 3000}\n"
        "  - wait_until_done\n",
        "arcs.yaml",
    )
    lemlib_build(project)
    with in_cache():
        ran = run_route(route)
    assert ran["error"] is None and ran["finished"], ran
    path, arc, done = ran["steps"]
    assert not path["timed_out"] and not arc["timed_out"]
    # each ends near where its plan does, from where it set off
    assert math.hypot(path["pose"][0] - 48, path["pose"][1]) < 2.5
    assert abs((path["pose"][2] - 135 + 180) % 360 - 180) < 6  # the way the last stretch goes
    x, y, theta = path["lemlib"]
    model = load_route(route).drive
    limits = Limits(model.max_velocity, model.max_accel, model.max_lateral_accel, 10)
    speed = model.max_velocity
    planned = plan_arc(x, y, math.radians(90 - theta), 18, -math.pi / 2, True, speed, limits)[-1]
    assert math.hypot(arc["pose"][0] - planned.x, arc["pose"][1] - planned.y) < 2.5
    assert done["ended_s"] == pytest.approx(arc["ended_s"], abs=0.02)

    # exported, and called from autonomous(): it drives the same
    made = export(project)
    assert [f.path for f in made.files if f.state == "new"][-3:] == list(LIBRARY)
    main = project / "src" / "main.cpp"
    text = main.read_text()
    main.write_text(
        '#include "custom/auton.hpp"\n'
        + text.replace("void autonomous() {", "void autonomous() {\n    arcs();\n    return;", 1)
    )
    lemlib_build(project)
    ends = [(s["ended_s"], s["pose"]) for s in ran["steps"]]
    with in_cache():
        spec = RunSpec(robot=str(tmp_path / "robot.yaml"), program=str(project), start=(0, 0, 90))
        drove = where_it_drove(spec, max(t for t, _ in ends) + 0.05)
    for t, pose in ends:
        at = min(drove, key=lambda p: abs(p[0] - t))
        assert abs(at[0] - t) < 0.001
        assert math.hypot(at[1] - pose[0], at[2] - pose[1]) < 0.25, (t, at, pose)

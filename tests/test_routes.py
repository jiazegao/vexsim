"""Autonomous routes (phase 13.1): route files read and checked (vexsim/app/routes.py), the
team's functions read from a project's headers (bridge/functions.py), and the runner a route
build adds to the project (bridge/runner.py), which runs a route in the project's own
autonomous() and says where each step ended. And the autonomous maker's side of the server
(13.2): the comments that say how the team's functions move the robot, mirrored routes, and
routes opened, checked and changed in place. The runs build PROS projects that use LemLib,
so they need g++ and LemLib's source."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from tests.conftest import ROOT
from vexsim.app.routes import (
    KINDS,
    check_text,
    label,
    load_route,
    mirror_text,
    read_route,
    run_route,
    runner_input,
)
from vexsim.app.runspec import RunError, RunSpec, check
from vexsim.app.workspace import Workspace
from vexsim.bridge.functions import Hint, find_functions
from vexsim.bridge.runner import Chassis, RouteRecord, find_chassis, runner_source
from vexsim.cli import build_parser, main

PROJECT = ROOT / "examples" / "pros_projects" / "1239e_2026-27"
TEMPLATE = ROOT / "examples" / "pros_projects" / "lemlib_template"
LEFT_START = PROJECT / "routes" / "left_start.yaml"
HEADERS = ["include/custom/util_funcs.hpp", "include/custom/lift_control.hpp"]
PROS = '{"py/state": {"templates": {"LemLib": {"version": "0.5.6"}}}}'

TEAM = r"""
#pragma once
#include "lemlib/api.hpp"
#include "modes.hpp"

extern lemlib::Chassis chassis;

namespace auton {
enum Speed { SLOW = 1, FAST = 2 };
void pick(Speed speed = Speed::FAST, Mode mode = Mode::B);
}
void drive(float inches, int timeout, float maxSpeed = 127, bool async = true);
void spin(std::uint8_t port, double rpm = -1.5e2, unsigned long ms = 0x10);
void lock(lemlib::DriveSide side = lemlib::DriveSide::LEFT);
void tuned(float kP = DEFAULT_KP, float kD = 2);
void startIntake();
inline void inlined(int x) {}
int returns();
static void hidden(int x);
void pointer(int* x);
void reference(const float& x);
void unnamed(int);
void templated(std::vector<int> v);
void variadic(int n, ...);
void over(int x);
void over(float x);
void twice(int x);
void twice(int x);
void text(const char* s);
void pose(lemlib::Pose p);
"""


def team_project(folder: Path) -> Path:
    """A PROS project that uses LemLib, with the team's functions in include/team.hpp, beside a
    robot and the practice field (whose barrier is at the field's center)."""
    project = folder / "project"
    (project / "include").mkdir(parents=True)
    (project / "src").mkdir()
    (project / "routes").mkdir()
    (project / "project.pros").write_text(PROS)
    (project / "include" / "team.hpp").write_text(TEAM)
    (project / "include" / "modes.hpp").write_text("#pragma once\nenum class Mode { A, B };\n")
    (project / "src" / "main.cpp").write_text(
        '#include "team.hpp"\nlemlib::Chassis chassis(a, b);\n'
    )
    shutil.copy(ROOT / "examples" / "robots" / "lemlib_example.yaml", folder / "robot.yaml")
    shutil.copy(ROOT / "examples" / "fields" / "practice_elements.yaml", folder / "field.yaml")
    return project


def route_file(project: Path, text: str, name: str = "test.yaml") -> Path:
    path = project / "routes" / name
    path.write_text(text)
    return path


HEAD = """\
version: 1
name: Test route
robot: ../../robot.yaml
field: ../../field.yaml
start: [-48, -24, 0]
functions: [include/team.hpp]
steps:
"""


# --- the team's functions -------------------------------------------------------------------------


def test_the_teams_functions_are_read_from_its_headers(tmp_path):
    project = team_project(tmp_path)
    found = find_functions(project, ["include/team.hpp", "include/missing.hpp"])
    assert found.missing == ["include/missing.hpp"]
    assert [f.name for f in found.functions] == [
        "auton::pick", "drive", "spin", "lock", "tuned", "startIntake", "inlined", "twice",
    ]  # fmt: skip
    drive = found.named("drive")
    assert drive.declaration() == (
        "void drive(float inches, int timeout, float maxSpeed = 127, bool async = true)"
    )
    assert drive.required == 2 and [p.kind for p in drive.params] == [
        "number", "integer", "number", "bool",
    ]  # fmt: skip
    pick = found.named("auton::pick")
    assert [(p.type, p.enum) for p in pick.params] == [("Speed", "auton::Speed"), ("Mode", "Mode")]
    assert [p.literal(found.enums[p.enum].values) for p in pick.params] == ["FAST", "B"]
    spin = found.named("spin")
    assert [p.type for p in spin.params] == ["std::uint8_t", "double", "unsigned long"]
    assert [p.literal() for p in spin.params[1:]] == [-150.0, 16]
    assert found.named("lock").params[0].enum == "lemlib::DriveSide"  # LemLib's own
    assert found.named("tuned").params[0].literal() is None  # an expression, not a value
    assert found.named("inlined").defined and not drive.defined
    pointer = "takes a pointer, a reference, an array, a template or a function"
    assert {o.name: o.why for o in found.others} == {
        "returns": "returns a value",
        "hidden": "is static: only its own file can call it",
        "pointer": pointer,
        "reference": pointer,
        "unnamed": "has a parameter without a name, which a route's arguments go by",
        "templated": pointer,
        "variadic": "takes any number of arguments",
        "over": "is overloaded",
        "text": pointer,
        "pose": "takes a lemlib::Pose, which a route can't pass (it passes numbers, bools and "
        "enums)",
    }


def test_1239es_own_functions_are_steps():
    found = find_functions(PROJECT, HEADERS)
    assert found.named("moveForward").declaration() == (
        "void moveForward(float inches, int timeout, float maxSpeed = 127, float minSpeed = 1, "
        "bool async = true)"
    )
    assert found.named("startFrontIntake").params[0].literal() == 127
    assert found.why_not("setEffector") == "is overloaded"  # by EFFECTOR_STAGES and float
    assert found.named("moveForward").hint == Hint("drive", ("inches",))  # its vexsim: comment
    assert found.named("moveBackward").hint is None
    assert found.enums["EFFECTOR_STAGES"].values[:2] == ("IDLE_ANGLE", "LOW_ANGLE")


def test_the_chassis_is_found_where_the_project_declares_it(tmp_path):
    assert find_chassis(PROJECT) == Chassis("chassis", "include/custom/configs.hpp", 146, True)
    assert find_chassis(TEMPLATE) == Chassis("chassis", "src/main.cpp", 83, False)
    project = team_project(tmp_path)  # declared extern in a header, defined in a source
    assert find_chassis(project) == Chassis("chassis", "include/team.hpp", 6, True)

    (project / "src" / "other.cpp").write_text("namespace robot { lemlib::Chassis base(a, b); }\n")
    assert "more than one lemlib::Chassis (chassis, robot::base)" in find_chassis(project)
    (project / "include" / "team.hpp").write_text("#pragma once\n")
    (project / "src" / "main.cpp").write_text("static lemlib::Chassis chassis(a, b);\n")
    (project / "src" / "other.cpp").unlink()
    assert "(chassis in src/main.cpp) is static" in find_chassis(project)
    (project / "src" / "main.cpp").write_text("int not_a_chassis = 0;\n")
    assert "can't find the project's lemlib::Chassis" in find_chassis(project)


# --- reading and checking a route -----------------------------------------------------------------


def test_a_route_reads_with_each_problem_at_its_place(tmp_path):
    project = team_project(tmp_path)
    text = HEAD + (
        "  - {move_to_point: [0, 0]}\n"  # steps[0]: no timeout
        "  - {turn_to_heading: 90, timeout: 500, max_speed: 60.5}\n"  # a turn's speeds are ints
        "  - {move_to_pose: [1, 2], timeout: 500}\n"  # a pose is [x, y, theta]
        "  - {swing_to_heading: 90, timeout: 500, direction: up}\n"  # no locked_side; bad direction
        "  - {move_to_point: [0, 0], timeout: 500, min_speed: 90, max_speed: 60, lead: 1}\n"
        "  - {wait: -5}\n"
        "  - {pause: 100}\n"
        "  - {wait: 100, wait_until: 3}\n"
        "  - {call: drive, args: {inches: [1]}}\n"
    )
    route, issues = read_route(yaml.safe_load(text + "stpes: []\n"), "test")
    assert route is None
    assert [(i.location, i.message) for i in issues] == [
        ("stpes", "unknown key 'stpes' (did you mean 'steps'?)"),
        ("steps[0].timeout", "required key is missing: how long it may take (ms)"),
        ("steps[1].max_speed", "must be a whole number"),
        ("steps[2].move_to_pose", "must be [x, y, theta] (inches, degrees)"),
        ("steps[3].locked_side", "required key is missing: left or right"),
        ("steps[3].direction", "must be one of: cw, ccw, auto"),
        ("steps[4].lead", "unknown key 'lead' for move_to_point"),
        ("steps[4].min_speed", "must be at most max_speed"),
        ("steps[5].wait", "must be 0 or more (ms)"),
        ("steps[6]", "must say what it does: " + ", ".join(KINDS)),
        ("steps[7]", "has more than one of wait, wait_until"),
        ("steps[8].args.inches", "must be a number, true or false, or an enum's value"),
    ]

    # in the editor's text, each at its line
    checked, located = check_text(text, route_file(project, text))
    where = {i.location: i.span.line for i in located if i.span is not None}
    assert where["steps[0].timeout"] == 8 and where["steps[1].max_speed"] == 9


def test_a_route_is_checked_against_its_project_robot_and_field(tmp_path):
    project = team_project(tmp_path)
    text = HEAD.replace("start: [-48, -24, 0]", "start: [0, 0, 90]") + (
        "  - {call: drvie, args: {inches: 5, timeout: 500}}\n"  # 0: no such function
        "  - {call: over}\n"  # 1: overloaded
        "  - {call: drive, args: {inches: true, timeout: 2.5, speed: 3}}\n"  # 2
        "  - {call: drive, args: {inches: 5}}\n"  # 3: timeout missing
        "  - {call: tuned, args: {kD: 3}}\n"  # 4: kP's default isn't a value
        "  - {call: auton::pick, args: {mode: C}}\n"  # 5: not one of Mode's
        "  - {move_to_point: [100, 0], timeout: 500, async: false}\n"  # 6: off the field
        "  - {wait_until: 5}\n"  # 7: after a motion that isn't async
        "  - {call: spin, args: {port: 3, ms: 20}}\n"  # 8: fine (rpm's default is a value)
    )
    checked = load_route(route_file(project, text))
    assert [(i.severity, i.location, i.message) for i in checked.issues] == [
        ("error", "steps[0].call", "the route's headers don't declare drvie() (did you mean "
                                   "drive?) (headers: include/team.hpp)"),
        ("error", "steps[1].call", "over() is overloaded, so a route can't call it"),
        ("error", "steps[2].args.inches", "inches is a number (float)"),
        ("error", "steps[2].args.timeout", "timeout is a whole number (int)"),
        ("error", "steps[2].args.speed", "drive() has no parameter speed (its parameters: inches, "
                                         "timeout, maxSpeed, async)"),
        ("error", "steps[3].args", "drive() needs timeout"),
        ("error", "steps[4].args", "give kP too: its default (DEFAULT_KP) isn't a value vexsim "
                                   "can pass on, and a later argument is given"),
        ("error", "steps[5].args.mode", "mode is a Mode: one of A, B"),
        ("warning", "steps[6].move_to_point", "(100, 0) is off the field"),
        ("warning", "steps[7].wait_until", "the motion before it isn't async, so it has ended: "
                                           "wait_until goes on at once"),
        ("warning", "start", "the robot starts on top of barrier; move its start"),
    ]  # fmt: skip

    # what the robot and field are, and where a route may be
    broken = HEAD.replace("../../robot.yaml", "../../nothing.yaml") + "  - {wait: 1}\n"
    assert [i.message for i in load_route(route_file(project, broken)).errors] == [
        "there's no ../../nothing.yaml (the path is relative to this route's file)"
    ]
    outside = tmp_path / "loose.yaml"
    outside.write_text(HEAD + "  - {wait: 1}\n")
    assert [i.message for i in load_route(outside).errors][0] == (
        "a route is a file in a PROS project's routes/ folder"
    )
    (project / "project.pros").write_text('{"py/state": {"templates": {}}}')
    assert [i.message for i in load_route(route_file(project, HEAD)).errors][0] == (
        "a route runs LemLib's motions, and project doesn't use LemLib"
    )


def test_the_runner_reads_the_steps_as_written(tmp_path):
    project = team_project(tmp_path)
    text = HEAD + (
        "  - {move_to_point: [24, -24], timeout: 1000, max_speed: 60, forwards: false}\n"
        "  - {move_to_pose: [24, 0, 45], timeout: 2000, lead: 0.3, async: false}\n"
        "  - {turn_to_heading: 270, timeout: 800, direction: ccw}\n"
        "  - {turn_to_point: [0, 0], timeout: 600}\n"
        "  - {swing_to_heading: 90, locked_side: right, timeout: 900}\n"
        "  - {swing_to_point: [0, 0], locked_side: left, timeout: 900, early_exit: 2}\n"
        "  - {wait: 250}\n"
        "  - {wait_until: 12.5}\n"
        "  - wait_until_done\n"
        "  - {wait_until_done: true}\n"
        "  - {call: drive, args: {inches: -10, timeout: 800, async: false}}\n"  # maxSpeed filled in
        "  - {call: auton::pick, args: {mode: Mode::A}}\n"  # speed filled in, by name
        "  - {call: startIntake}\n"
    )
    checked = load_route(route_file(project, text))
    assert checked.ok, checked.issues
    assert runner_input(checked.route, checked.functions) == (
        "vexsim-route 1\n"
        "start -48 -24 0\n"
        "1 move_to_point 24 -24 1000 forwards=false max_speed=60\n"
        "2 move_to_pose 24 0 45 2000 lead=0.3 async=false\n"
        "3 turn_to_heading 270 800 direction=ccw\n"
        "4 turn_to_point 0 0 600\n"
        "5 swing_to_heading 90 right 900\n"
        "6 swing_to_point 0 0 left 900 early_exit=2\n"
        "7 wait 250\n"
        "8 wait_until 12.5\n"
        "9 wait_until_done\n"
        "10 wait_until_done\n"
        "11 call drive -10 800 127 false\n"
        "12 call auton::pick FAST A\n"
        "13 call startIntake\n"
    )
    labels = [label(step) for step in checked.route.steps]
    assert labels[0] == "move_to_point (24, -24) forwards false max_speed 60"
    assert labels[1] == "move_to_pose (24, 0, 45) lead 0.3 not async"
    assert labels[4] == "swing_to_heading 90 right side"
    assert labels[10] == "drive(inches=-10, timeout=800, async=false)"
    assert checked.route.start_pose() == (-48, -24, 90)  # vexsim's heading: counter-clockwise


def test_the_runner_is_generated_with_the_teams_functions(tmp_path):
    project = team_project(tmp_path)
    found = find_functions(project, ["include/team.hpp"])
    stage = tmp_path / "stage"
    source = runner_source(
        project,
        ["include/team.hpp"],
        found,
        find_chassis(project),
        stage,
        {"twice": "isn't defined"},
    )
    assert '#include "team.hpp"' in source
    assert "lemlib::Chassis& chassis() { return ::chassis; }" in source
    assert "const Named<::auton::Speed> enum_0[] = " in source
    assert '{"FAST", ::auton::Speed::FAST}' in source
    assert "\t\tcase 2: ::drive(p0, p1); return nullptr;" in source
    assert "\t\tcase 4: ::drive(p0, p1, p2, p3); return nullptr;" in source
    assert "\tfloat p0{}; int p1{}; float p2{}; bool p3{};" in source
    assert "\tstd::uint8_t p0{}; double p1{}; unsigned long p2{};" in source
    assert '\tif (name == "twice") return "isn\'t defined";' in source
    # a chassis that's only in a source file is declared for the runner
    template = runner_source(
        TEMPLATE, [], find_functions(TEMPLATE, []), find_chassis(TEMPLATE), stage
    )
    assert "extern lemlib::Chassis chassis;" in template and '#include "main.h"' in template


def test_the_runners_lines_say_where_each_step_ended():
    record = RouteRecord()
    true = (1.0, 2.0, 90.0)
    lines = [
        (0.0, "vexsim: route starts"),
        (0.0, "vexsim: route step 1 starts 0"),  # an async motion: motion 0
        (0.0, "vexsim: route motion 0 starts"),
        (0.01, "vexsim: route step 1 called 1 0 0 90"),
        (0.01, "vexsim: route step 2 starts 1"),  # a call that starts two more
        (0.5, "vexsim: route motion 0 ends 10 0 90"),
        (0.5, "vexsim: route motion 1 starts"),
        (0.9, "vexsim: route motion 1 ends 12 0 90"),
        (0.9, "vexsim: route motion 2 starts"),
        (0.91, "vexsim: route step 2 called 3 12 0 90"),
        (0.91, "vexsim: route step 3 starts 3"),  # a motion that isn't async: it waits its turn
        (1.4, "vexsim: route motion 2 ends 20 0 90"),
        (1.9, "vexsim: route step 3 called 3 20 5 0"),
        (1.9, "vexsim: route ends"),
    ]
    for time_s, text in lines:
        assert record.read(text, time_s, true)
    assert not record.read("vexsim: autonomous() called left40()", 2.0, true)
    assert record.done
    assert [record.step_end(n).time_s for n in (1, 2, 3)] == [0.5, 1.4, 1.9]
    assert record.step_end(3).lemlib == (20, 5, 0) and record.step_end(3).pose == true
    assert record.motion_time(1) == pytest.approx(0.5)  # its task's life
    assert record.motion_time(3) == pytest.approx(0.5)  # from when the motions before it ended
    cut = RouteRecord()
    for time_s, text in lines[:8]:
        cut.read(text, time_s, true)
    assert cut.step_end(2) is None and not cut.done  # its last motion hasn't ended
    cut.read("vexsim: route can't run: step 3 (call): takes 2 argument(s)", 1.0, true)
    assert cut.done and cut.error == "step 3 (call): takes 2 argument(s)"


# --- the autonomous maker (13.2) ------------------------------------------------------------------

MOVES = """\
#pragma once
// Turns in place, clockwise.
// vexsim: turn_by(degrees)
void turnBy(float degrees, int timeout = 800);
// vexsim: point(x, y)
void goPoint(float x, float y);
// vexsim: arc(18, degrees)
void sweep(float degrees);
// vexsim: drive(inches)
void ahead(float inches);
// vexsim: turn_by(90)
void quarter();
// vexsim: none
void clamp(bool closed = true);
// vexsim: drive(timeout2)
void notAParameter(int timeout);
// vexsim: drive(closed)
void notANumber(bool closed);
// vexsim: fly(up)
void notAMotion(float up);
// vexsim: turn_by(a, b)
void tooMany(float a, float b);

void unsaid(float inches);
"""


def test_a_comment_above_a_function_says_how_it_moves_the_robot(tmp_path):
    project = team_project(tmp_path)
    (project / "include" / "moves.hpp").write_text(MOVES)
    found = {f.name: f for f in find_functions(project, ["include/moves.hpp"]).functions}
    assert {name: f.hint for name, f in found.items() if f.hint} == {
        "turnBy": Hint("turn_by", ("degrees",)),  # past the comment above it
        "goPoint": Hint("point", ("x", "y")),
        "sweep": Hint("arc", (18.0, "degrees")),  # a number, or a number parameter
        "ahead": Hint("drive", ("inches",)),
        "quarter": Hint("turn_by", (90.0,)),
        "clamp": Hint("none"),
    }
    numbers = "isn't a number, or one of {}()'s number parameters"
    assert {name: f.hint_problem for name, f in found.items() if f.hint_problem} == {
        "notAParameter": "vexsim: timeout2 " + numbers.format("notAParameter"),
        "notANumber": "vexsim: closed " + numbers.format("notANumber"),
        "notAMotion": "vexsim: fly(up) isn't one of drive(inches), turn_by(degrees), "
        "arc(radius, degrees), point(x, y), pose(x, y, theta), none",
        "tooMany": "vexsim: turn_by takes 1 argument(s): degrees",
    }
    assert found["unsaid"].hint is None and found["unsaid"].hint_problem is None


def test_a_route_is_mirrored_for_the_other_side_of_the_field(tmp_path):
    project = team_project(tmp_path)
    (project / "include" / "moves.hpp").write_text(MOVES)
    text = (
        "# for the left side\n"
        "version: 1\nname: Left side\nrobot: ../../robot.yaml\n"
        "start: [-48, -24, 30]   # setPose\n"
        "functions: [include/moves.hpp, include/team.hpp]\n"
        "steps:\n"
        "  - {move_to_point: [-24, -24], timeout: 1000}   # the first\n"
        "  - {turn_to_heading: 90, timeout: 800, direction: cw}\n"
        "  - {swing_to_point: [0, 6], locked_side: left, timeout: 900}\n"
        "  - {move_to_pose: [-10, 20, 45], timeout: 2000}\n"
        "  - {call: turnBy, args: {degrees: 30}}\n"
        "  - {call: goPoint, args: {x: -5, y: 7}}\n"
        "  - {call: sweep, args: {degrees: -45}}\n"
        "  - {call: ahead, args: {inches: 12}}\n"
        "  - {call: startIntake}\n"
        "  - {call: quarter}\n"
    )
    route = route_file(project, text)
    across_x, notes = mirror_text(text, route, "x")  # x becomes -x
    assert across_x == (
        "# for the left side\n"
        "version: 1\nname: Left side (mirrored)\nrobot: ../../robot.yaml\n"
        "start: [48, -24, 330]   # setPose\n"
        "functions: [include/moves.hpp, include/team.hpp]\n"
        "steps:\n"
        "  - {move_to_point: [24, -24], timeout: 1000}   # the first\n"
        "  - {turn_to_heading: 270, timeout: 800, direction: ccw}\n"  # the other way round
        "  - {swing_to_point: [0, 6], locked_side: right, timeout: 900}\n"
        "  - {move_to_pose: [10, 20, 315], timeout: 2000}\n"
        "  - {call: turnBy, args: {degrees: -30}}\n"  # as their vexsim: comments say
        "  - {call: goPoint, args: {x: 5, y: 7}}\n"
        "  - {call: sweep, args: {degrees: 45}}\n"
        "  - {call: ahead, args: {inches: 12}}\n"
        "  - {call: startIntake}\n"
        "  - {call: quarter}\n"
    )
    assert notes == [
        "step 9: startIntake() is as it was: nothing says how it moves the robot (a // vexsim: "
        "comment above it would)",
        "step 10: quarter() turns by a fixed angle, so its mirror image is another function: "
        "change that step by hand",
    ]
    across_y, _ = mirror_text(text, route, "y")  # y becomes -y
    assert "start: [-48, 24, 150]   # setPose" in across_y
    assert "  - {move_to_pose: [-10, -20, 135], timeout: 2000}\n" in across_y
    assert "  - {call: goPoint, args: {x: -5, y: -7}}\n" in across_y
    with pytest.raises(ValueError, match="the route doesn't read"):
        mirror_text("steps: [", route, "x")


def test_the_server_opens_checks_and_changes_a_route_in_place(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from tests.test_pages import TOKEN
    from vexsim.ui.server import create_app

    project = team_project(tmp_path)
    text = HEAD + "  - {move_to_point: [-24, -24], timeout: 1000}   # the first\n  - {wait: 100}\n"
    route_file(project, text)
    path = "project/routes/test.yaml"
    app = create_app(
        tmp_path, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as client:
        client.headers["authorization"] = f"Bearer {TOKEN}"
        opened = client.get("/api/route", params={"path": path}).json()
        assert opened["text"] == text and opened["version"]
        checked = opened["check"]
        assert checked["issues"] == [] and checked["route"]["start"] == [-48, -24, 0]
        assert [s["label"] for s in checked["route"]["steps"]] == [
            "move_to_point (-24, -24)", "wait 100 ms",
        ]  # fmt: skip
        assert checked["places"]["steps[1]"]["line"] == 9  # to show a step in the YAML
        assert (checked["project"], checked["robot_path"], checked["field_path"]) == (
            "project", "robot.yaml", "field.yaml",
        )  # fmt: skip
        assert checked["headers"] == ["include/modes.hpp", "include/team.hpp"]
        assert "drive" in [f["name"] for f in checked["functions"]]
        assert checked["preview"]["field"]["size"] == [144, 144] and checked["track"] == 10
        # half typed: what reads is still there to draw, the rest is marked
        typing = text.replace("{wait: 100}", "{wait: }")
        partial = client.post("/api/route/check", json={"path": path, "text": typing}).json()
        assert [(i["location"], i["message"]) for i in partial["issues"]] == [
            ("steps[1].wait", "must be a whole number"),
        ]  # fmt: skip
        assert [s["kind"] for s in partial["route"]["steps"]] == ["move_to_point", "invalid"]

        # a step put in, one moved, a number set: in place, the comments kept
        edits = [
            {
                "op": "insert",
                "location": "steps[1]",
                "value": {"turn_to_heading": 90, "timeout": 800},
            },
            {"op": "move", "location": "steps[2]", "value": 0},
            {"op": "set", "location": "steps[1].move_to_point[1]", "value": -12},
        ]
        patched = client.post("/api/route/patch", json={"path": path, "text": text, "edits": edits})
        assert patched.json()["text"] == HEAD + (
            "  - {wait: 100}\n"
            "  - {move_to_point: [-24, -12], timeout: 1000}   # the first\n"
            "  - {turn_to_heading: 90, timeout: 800}\n"
        )
        assert [s["kind"] for s in patched.json()["check"]["route"]["steps"]] == [
            "wait", "move_to_point", "turn_to_heading",
        ]  # fmt: skip
        moved = [{"op": "move", "location": "steps[0]", "value": 5}]
        refused = client.post("/api/route/patch", json={"path": path, "text": text, "edits": moved})
        assert refused.status_code == 422
        assert refused.json()["detail"] == "steps[0] can only move to a place in its list (0 to 1)"
        robot = client.get("/api/route", params={"path": "robot.yaml"})
        assert robot.status_code == 400
        assert robot.json()["detail"] == "robot.yaml isn't in a PROS project's routes/ folder"

        # New route…: in the project's routes/, never over a file, its start as LemLib's
        new = {"project": "project", "name": "Test route", "robot": "robot.yaml",
               "field": "field.yaml", "start": [-48, -24, 0]}  # fmt: skip
        made = [client.post("/api/routes/new", json=new).json()["path"] for _ in range(2)]
        assert made == ["project/routes/test_route.yaml", "project/routes/test_route_2.yaml"]
        written = (tmp_path / made[0]).read_text()
        assert "robot: ../../robot.yaml   # relative to this file\n" in written
        assert "start: [-48, -24, 90]   # chassis.setPose(x, y, theta)\n" in written  # facing +x
        assert written.endswith("steps: []\n") and load_route(tmp_path / made[0]).ok
        nowhere = client.post("/api/routes/new", json={"project": "nowhere", "name": "x"})
        assert (
            nowhere.status_code == 422
            and nowhere.json()["detail"] == "nowhere isn't a PROS project"
        )

        # mirrored: a copy beside it
        mirror = {"path": path, "text": text, "axis": "x"}
        mirrored = client.post("/api/routes/mirror", json=mirror).json()
        assert mirrored == {"path": "project/routes/test_mirrored.yaml", "notes": []}
        copy = (tmp_path / mirrored["path"]).read_text()
        assert "name: Test route (mirrored)\n" in copy and "start: [48, -24, 0]\n" in copy
        again = client.post("/api/routes/mirror", json=mirror).json()
        assert again["path"] == "project/routes/test_mirrored_2.yaml"


def test_the_server_offers_the_functions_of_the_headers_a_route_doesnt_list(tmp_path):
    """For *Add a step* to find: picking one lists its header in the route's functions."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from tests.test_pages import TOKEN
    from vexsim.ui.server import create_app

    project = team_project(tmp_path)
    moves = project / "include" / "moves.hpp"
    moves.write_text(MOVES + "void startIntake();\n")  # team.hpp has one too: the route's
    route_file(project, HEAD + "  - {wait: 100}\n")
    path = "project/routes/test.yaml"
    app = create_app(
        tmp_path, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as client:
        client.headers["authorization"] = f"Bearer {TOKEN}"
        checked = client.get("/api/route", params={"path": path}).json()["check"]
        assert "startIntake" in [f["name"] for f in checked["functions"]]
        more = {f["name"]: f for f in checked["more_functions"]}
        assert list(more) == [
            "turnBy", "goPoint", "sweep", "ahead", "quarter", "clamp", "notAParameter",
            "notANumber", "notAMotion", "tooMany", "unsaid",
        ]  # fmt: skip
        assert {f["header"] for f in more.values()} == {"include/moves.hpp"}
        turn = more["turnBy"]
        assert turn["declaration"] == "void turnBy(float degrees, int timeout = 800)"
        assert [p["name"] for p in turn["params"]] == ["degrees", "timeout"]
        assert turn["hint"] == {"motion": "turn_by", "args": ["degrees"]}

        moves.write_text(MOVES.replace("void unsaid(float inches);", "void later();"))
        again = client.post("/api/route/check", json={"path": path, "text": HEAD}).json()
        assert [f["name"] for f in again["more_functions"]][-1] == "later"  # read again

        listing = HEAD.replace("[include/team.hpp]", "[include/team.hpp, include/moves.hpp]")
        both = client.post("/api/route/check", json={"path": path, "text": listing}).json()
        assert "later" in [f["name"] for f in both["functions"]]
        assert both["more_functions"] == []


# --- where routes show up -------------------------------------------------------------------------


def test_routes_are_listed_and_run_as_their_files_say(tmp_path):
    items = Workspace(ROOT).scan()
    listed = [i for i in items if i.kind == "route" and i.path.startswith("examples/")]
    assert listed and listed[0].name == "Left start"
    assert listed[0].detail == "6 steps, from setPose(60, 0, 90)" and not listed[0].problem

    args = build_parser().parse_args(["run", "--route", str(LEFT_START)])
    spec = RunSpec.from_args(args)
    assert Path(spec.robot) == ROOT / "examples" / "robots" / "1239e_2026-27.yaml"
    assert Path(spec.program) == PROJECT and Path(spec.field).name == "1239e_2026-27.yaml"
    assert spec.start == (60, 0, 0) and spec.route == str(LEFT_START)
    assert "--route" in spec.to_args()
    prepared = check(spec)
    assert prepared.project == PROJECT and prepared.route.ok
    for change, why in (
        ({"routine": "left40"}, "a run picks a routine or runs a route, not both"),
        ({"mode": "driver"}, "a route runs in the autonomous period"),
        ({"program": str(TEMPLATE)}, "so the run's program is that project"),
    ):
        with pytest.raises(RunError, match=why):
            check(spec.model_copy(update=change))


def test_the_cli_checks_a_route(capsys):
    assert main(["route", "check", str(LEFT_START), "--functions"]) == 0
    out = capsys.readouterr().out
    assert "starts at (60, 0, 90), 6 step(s)" in out
    assert "    1  moveForward(inches=-10, timeout=800, minSpeed=1)" in out
    assert "  not callable: setEffector() (line 36) is overloaded" in out
    assert out.rstrip().endswith("no problems")


# --- running routes -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def route_build(lemlib_build, build):
    """1239E's project, built for its routes (LemLib built first, as the port's tests do)."""
    lemlib_build(PROJECT)
    return lambda: build(PROJECT, route=HEADERS)


def test_a_route_runs_in_1239es_autonomous_and_says_where_each_step_ended(route_build, in_cache):
    first = route_build()
    assert first.functions_left_out == {
        "partnercontrollervibrate": "is declared, but no file vexsim's build compiles defines it"
    }
    with in_cache():
        result = run_route(LEFT_START)
    assert result["error"] is None and result["finished"], result
    steps = result["steps"]
    assert [s["kind"] for s in steps] == [
        "call", "turn_to_heading", "move_to_point", "call", "wait", "move_to_point",
    ]  # fmt: skip
    back = steps[0]  # moveForward(-10, ...): 10 in back from (60, 0), facing +x
    assert back["pose"][0] == pytest.approx(50, abs=1) and back["pose"][1] == pytest.approx(
        0, abs=1
    )
    assert back["lemlib"][0] == pytest.approx(back["pose"][0], abs=1)
    turn = steps[1]  # queued behind it: it starts when moveForward's motion ends
    assert turn["ended_s"] > back["ended_s"] and turn["pose"][2] == pytest.approx(270, abs=10)
    assert steps[3]["duration_s"] == 0  # startFrontIntake() returns at once
    assert steps[4]["duration_s"] == pytest.approx(0.1)  # wait 100
    assert all(s["timed_out"] is None for s in steps if s["kind"] in ("call", "wait"))
    assert all(
        isinstance(s["timed_out"], bool) for s in steps if s["kind"].startswith(("move", "turn"))
    )
    assert result["ended_s"] == steps[-1]["ended_s"] and result["period_s"] == 15


def test_a_changed_step_reruns_without_a_rebuild(route_build, in_cache):
    route_build()
    changed = PROJECT / "routes" / "_changed_by_a_test.yaml"
    text = LEFT_START.read_text().replace("{inches: -10,", "{inches: -20,")
    try:
        changed.write_text(text)
        again = route_build()
        assert again.compiled == 0 and not again.linked  # the same build
        with in_cache():
            result = run_route(changed)
    finally:
        changed.unlink(missing_ok=True)
    assert result["steps"][0]["pose"][0] == pytest.approx(40, abs=1)  # 20 in back this time


def test_a_route_runs_in_place_of_autonomous_in_a_project_without_routines(
    lemlib_build, in_cache, tmp_path
):
    project = tmp_path / "template"
    shutil.copytree(TEMPLATE, project)
    (project / "routes").mkdir()
    shutil.copy(ROOT / "examples" / "robots" / "lemlib_example.yaml", tmp_path / "robot.yaml")
    route = route_file(
        project,
        "version: 1\nname: Square\nrobot: ../../robot.yaml\nstart: [0, 0, 0]\nsteps:\n"
        "  - {move_to_point: [0, 24], timeout: 2000}\n"
        "  - {turn_to_heading: 90, timeout: 1000}\n"
        "  - {swing_to_heading: 180, locked_side: right, timeout: 1500, async: false}\n"
        "  - {move_to_point: [0, 0], timeout: 3000, forwards: false}\n"
        "  - {wait_until: 4}\n"
        "  - wait_until_done\n",
    )
    lemlib_build(project)
    with in_cache():
        result = run_route(route)
    assert result["error"] is None and result["finished"], result
    up, turn, swing, back, until, done = result["steps"]
    assert up["pose"][1] == pytest.approx(24, abs=1.5)  # the template's own autonomous() didn't run
    assert turn["pose"][2] == pytest.approx(90, abs=5) and swing["pose"][2] == pytest.approx(
        180, abs=8
    )
    assert until["ended_s"] < back["ended_s"]
    assert done["ended_s"] == pytest.approx(back["ended_s"], abs=0.02)  # it looks every 10 ms
    assert back["lemlib"][1] == pytest.approx(back["pose"][1], abs=2)


def test_the_cli_runs_a_route(route_build, in_cache, capsys):
    route_build()
    with in_cache():
        assert main(["route", "run", str(LEFT_START), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)  # the build's log goes to stderr
    assert result["name"] == "Left start" and len(result["steps"]) == 6
    with in_cache():
        assert main(["route", "run", str(LEFT_START)]) == 0
    out = capsys.readouterr().out
    assert "Left start: 6 step(s), done " in out and "s into the 15 s autonomous period" in out
    assert "moveForward(inches=-10, timeout=800, minSpeed=1)" in out


def test_the_server_lists_a_projects_routes_and_runs_one(route_build, in_cache):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from tests.test_pages import TOKEN, finished
    from vexsim.ui.protocol import RouteRun
    from vexsim.ui.server import create_app

    route_build()
    project = "examples/pros_projects/1239e_2026-27"
    app = create_app(
        ROOT, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with in_cache(), TestClient(app) as client:
        client.headers["authorization"] = f"Bearer {TOKEN}"
        listed = client.get("/api/routines", params={"project": project}).json()
        assert listed["routes"] == [
            {
                "path": f"{project}/routes/left_start.yaml",
                "name": "Left start",
                "robot": "examples/robots/1239e_2026-27.yaml",
                "field": "examples/fields/1239e_2026-27.yaml",
                "start": [60, 0, 0],
                "problem": None,
            }
        ]
        job = finished(client, {"kind": "route", "route": f"{project}/routes/left_start.yaml"})
        assert job["state"] == "succeeded", job
        run = RouteRun.model_validate(job["result"])
        assert run.finished and run.steps[0].label.startswith("moveForward(")
        times = [t for t, _, _, _ in run.path]  # where it drove, every 20 ms
        assert 0 <= times[0] < 0.02 and times[1] - times[0] == pytest.approx(0.02)
        assert times[-1] == pytest.approx(run.ended_s, abs=0.02)  # until the last step ended
        # the editor's text, not saved: run as the file would be
        text = LEFT_START.read_text().replace("{inches: -10,", "{inches: -20,")
        route = {"kind": "route", "route": f"{project}/routes/left_start.yaml", "text": text}
        edited = RouteRun.model_validate(finished(client, route)["result"])
        assert edited.steps[0].pose[0] == pytest.approx(40, abs=1)  # 20 in back this time
        missing = client.post("/api/jobs", json={"kind": "route", "route": "nowhere.yaml"})
        assert missing.status_code == 422

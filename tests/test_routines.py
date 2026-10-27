"""A PROS project's autonomous routines (vexsim/bridge/routines.py): reading them from
include/custom/auton.hpp, and the switch that runs the one picked inside the project's own
autonomous(). The switch's tests build tests/cpp/routine_test, so they need g++."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest

from tests.conftest import ROOT
from vexsim.algorithms.localization.base import Pose
from vexsim.app.runspec import RunError, RunSpec, check
from vexsim.bridge.program import CppProgram
from vexsim.bridge.routines import Routine, find_routines, rename_header, switch_source
from vexsim.cli import main
from vexsim.config import load_robot
from vexsim.runtime.simulation import Simulation

PROJECT = Path(__file__).parent / "cpp" / "routine_test"
ROBOT = ROOT / "examples" / "robots" / "full_omni_6m.yaml"


def project(tmp_path: Path, header: str, sources: dict[str, str] | None = None) -> Path:
    """A PROS project with this auton.hpp and these sources."""
    (tmp_path / "include" / "custom").mkdir(parents=True)
    (tmp_path / "include" / "custom" / "auton.hpp").write_text(header)
    (tmp_path / "src").mkdir()
    for name, text in (sources or {"main.cpp": ""}).items():
        (tmp_path / "src" / name).write_text(text)
    return tmp_path


# --- reading the header -----------------------------------------------------------------------


def test_the_routines_are_the_functions_that_take_nothing(tmp_path):
    header = r"""
#pragma once
#include "main.h"
#define AUTON(name) void name(); \
    void fake_from_a_macro();
// void commented_out();
/* void also_commented();
   void still(); */
const char* note = "void in_a_string(); {";

void left40();
void left30(void), right30();  // two at once
[[maybe_unused]] void with_attribute() noexcept;
extern void declared_extern();
namespace auton {
void far_side();
namespace inner { void deep(); }
}  // namespace auton
namespace a::b { void nested(); }
inline namespace v2 { void versioned(); }
extern "C" void c_routine();
extern "C" {
void c_block_routine(void);
}

void drive(int ms);               // takes an argument
void tune(double kP = 1.0);       // has a default, still an argument
int points();                     // returns a value
static void hidden();             // only its own file sees it
namespace { void anonymous(); }
inline void defined_here() { left40(); }
void removed() = delete;
void (*selected)();               // a pointer, not a function
typedef void (*Routine)();
using Fn = void (*)();
template <typename T> void generic();
struct Selector { void run(); static void pick(); };
class Chooser { public: void choose(); };
enum Side { LEFT, RIGHT };
"""
    found = find_routines(project(tmp_path, header))
    names = [r.name for r in found.routines]
    assert names == [
        "left40", "left30", "right30", "with_attribute", "declared_extern", "auton::far_side",
        "auton::inner::deep", "a::b::nested", "v2::versioned", "c_routine", "c_block_routine",
    ]  # fmt: skip
    assert found.named("with_attribute").noexcept and not found.named("left40").noexcept
    assert found.named("c_routine").c_linkage and found.named("c_block_routine").c_linkage
    assert found.named("left40").line == 11
    why = {o.name: o.why for o in found.others}
    assert why == {
        "drive": "takes arguments",
        "tune": "takes arguments",
        "points": "returns a value",
        "hidden": "only the file that defines it can call it (static, or an anonymous namespace)",
        "anonymous": "only the file that defines it can call it (static, or an anonymous "
        "namespace)",
        "defined_here": "is defined in the header, so every file has its own copy",
    }
    assert find_routines(tmp_path / "nowhere") is None


def test_symbols_are_as_the_compiler_names_them():
    assert Routine("left40", 1).symbol == "_Z6left40v"
    assert Routine("extra::gamma", 1).symbol == "_ZN5extra5gammaEv"
    assert Routine("a::b::c", 1).symbol == "_ZN1a1b1cEv"
    assert Routine("c_routine", 1, c_linkage=True).symbol == "c_routine"
    assert Routine("left40", 1).renamed == "vexsim_routine__Z6left40v"


def test_a_routine_starts_where_its_set_pose_puts_the_robot(tmp_path):
    header = "void a(); void b(); void c(); void d(); void e(); void f();\n"
    header += "namespace side { void g(); void h(); }\n"
    source = """
#include "custom/auton.hpp"
void a() { chassis.setPose(60, 0, 90); chassis.moveToPoint(0, 0, 1000); }
void b() {
    chassis.setPose(-60.5, 24, -90);  // the other side
}
void c() { chassis.setPose(10, 20, 1.5708, true); }
void d() { chassis.setPose({12, -36, 180}); }
void e() { chassis.setPose(lemlib::Pose(0, -48, 0)); }
void f() { chassis.setPose(startX(), 0, 90); }  // not numbers
void side::g() { chassis.setPose(1, 2, 0); }
namespace side {
void h() { drive(); }
}
"""
    found = find_routines(project(tmp_path, header, {"auton.cpp": source}))
    start = {r.name: r.start for r in found.routines}
    assert start["a"] == (60, 0, 90) and start["b"] == (-60.5, 24, -90)
    assert start["c"] == pytest.approx((10, 20, 90), abs=1e-3)  # radians
    assert start["d"] == (12, -36, 180) and start["e"] == (0, -48, 0)
    assert start["f"] is None and start["side::h"] is None
    assert start["side::g"] == (1, 2, 0)
    assert {r.source for r in found.routines} == {"src/auton.cpp"}
    # as vexsim has poses: heading counter-clockwise from +x (LemLib's theta: clockwise from +y)
    pose = {r.name: r.start_pose() for r in found.routines}
    assert pose["a"] == (60, 0, 0) and pose["b"] == (-60.5, 24, 180)
    assert pose["d"] == (12, -36, -90) and pose["e"] == (0, -48, 90)


def test_the_switch_is_generated_for_the_routines():
    routines = [
        Routine("left40", 1, source="src/auton.cpp"),
        Routine("extra::gamma", 2, noexcept=True, source="src/auton.cpp"),
        Routine("c_routine", 3, c_linkage=True, source="src/auton.cpp"),
    ]
    header = rename_header(routines)
    assert 'void left40() VEXSIM_ROUTINE_NAMED("vexsim_routine__Z6left40v");' in header
    assert "namespace extra { void gamma() noexcept VEXSIM_ROUTINE_NAMED(" in header
    assert 'extern "C" void c_routine() VEXSIM_ROUTINE_NAMED("vexsim_routine_c_routine");' in header
    source = switch_source(routines)
    assert "void left40() { route(0); }" in source
    assert "namespace extra { void gamma() noexcept { route(1); } }" in source
    assert 'extern "C" void c_routine() { route(2); }' in source
    assert '{"extra::gamma", extra::vexsim_real_1}' in source
    assert '{"c_routine", vexsim_real_2}' in source


# --- picking one for a run --------------------------------------------------------------------


def test_a_run_picks_one_of_the_projects_routines(capsys):
    spec = RunSpec(robot=str(ROBOT), program=str(PROJECT), routine="beta")
    assert check(spec).warnings == []
    assert RunSpec.from_args(_args("--routine", "beta")).start == (12, -36, -90)  # its setPose
    driver = check(spec.model_copy(update={"mode": "driver"}))
    assert [w.location for w in driver.warnings] == ["routine"]
    for routine, message in (
        ("omega", r"there's no routine omega\(\) in include/custom/auton.hpp "
                  r"\(its routines: alpha, beta, extra::gamma, delta, ghost\)"),
        ("drive_for", r"drive_for\(\) takes arguments, so it isn't a routine"),
        ("ghost", r"ghost\(\) is declared in include/custom/auton.hpp, but vexsim can't tell"),
    ):  # fmt: skip
        with pytest.raises(RunError, match=message):
            check(spec.model_copy(update={"routine": routine}))
    tour = str(ROOT / "examples" / "programs" / "tour.py")
    with pytest.raises(RunError, match="a PROS project's routine, but the program isn't one"):
        check(spec.model_copy(update={"program": tour}))
    minimal = str(ROOT / "examples" / "pros_projects" / "minimal_pros4")
    with pytest.raises(RunError, match="has no include/custom/auton.hpp"):
        check(spec.model_copy(update={"program": minimal}))
    assert main(["routines", str(PROJECT)]) == 0
    listed = capsys.readouterr().out
    assert re.search(r"alpha +starts at --start=-60,24.5,0 \(setPose -60, 24.5, 90\)", listed)
    assert re.search(r"extra::gamma +defined in src/auton.cpp", listed)
    assert "Not a routine: drive_for() (line 13) takes arguments" in listed


def _args(*more: str):
    from vexsim.cli import build_parser

    return build_parser().parse_args(["run", str(ROBOT), "--program", str(PROJECT), *more])


# --- the switch, built and run ----------------------------------------------------------------


@pytest.fixture(scope="module")
def built(build):
    return build(PROJECT)


def run(built, routine: str | None, mode: str = "autonomous", calls: str | None = None):
    """The console of half a second of the test project, with ``routine`` picked; ``calls``
    makes its autonomous() call a routine of its own file (TEST_CALLS)."""
    env = {"TEST_CALLS": calls} if calls else {}
    program = CppProgram(built.executable, env=env, routine=routine)
    sim = Simulation(load_robot(ROBOT), program=program, start=Pose(0, 0, 0), echo=None)
    sim.start(mode)
    try:
        sim.run_for(0.5)
    finally:
        sim.close()
    return [re.sub(r"^\[\s*[\d.]+\] ", "", line) for line in sim.console]


def test_the_build_puts_the_switch_in_front_of_the_routines(built):
    assert built.routines == ["alpha", "beta", "extra::gamma", "delta"]
    assert any(note.startswith("ghost() is declared in") for note in built.notes)


def test_autonomous_runs_as_written_and_the_routine_it_calls_becomes_the_one_picked(built):
    assert run(built, None) == [
        "autonomous setup", "setPose -60 24.5 90", "alpha runs", "autonomous done",
    ]  # fmt: skip
    assert run(built, "beta") == [
        "autonomous setup",
        "vexsim: autonomous() called alpha(); running beta() instead",
        "setPose 12 -36 180",
        "beta runs",
        "setPose -60 24.5 90",  # beta calls alpha() itself: as written
        "alpha runs",
        "autonomous done",
    ]
    assert run(built, "extra::gamma")[1:3] == [
        "vexsim: autonomous() called alpha(); running extra::gamma() instead",
        "gamma runs",
    ]
    assert run(built, "alpha")[1] == "vexsim: autonomous() called alpha(), the routine picked"


def test_a_routine_called_from_its_own_file_cant_be_switched(built):
    assert run(built, "beta", calls="delta") == [
        "autonomous setup",
        "delta runs",  # main.cpp calls its own delta(): the switch never sees it
        "autonomous done",
        "vexsim: autonomous() didn't call a routine from include/custom/auton.hpp that vexsim "
        "can switch, so beta() didn't run",
    ]
    assert run(built, "beta", mode="driver") == []  # no autonomous period, no routine


def test_a_definition_the_build_doesnt_compile_is_left_out_of_the_switch(tmp_path, build):
    copy = tmp_path / "routine_test"
    shutil.copytree(PROJECT, copy)
    (copy / "src" / "disabled.cpp").write_text(
        '#include "custom/auton.hpp"\n#if 0\nvoid ghost() {}\n#endif\n'
    )  # vexsim reads past #if 0: the definition it finds isn't compiled
    found = find_routines(copy)
    assert found.named("ghost").source == "src/disabled.cpp"
    result = build(copy)
    assert result.routines == ["alpha", "beta", "extra::gamma", "delta"]
    assert "ghost() has no definition that vexsim's build compiles, so a run can't pick it" in (
        result.notes
    )
    os.environ.pop("VEXSIM_ROUTINE", None)
    assert run(result, "beta")[1] == "vexsim: autonomous() called alpha(); running beta() instead"

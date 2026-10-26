"""Phase 8: LemLib from source, ASSET files, pose readback, and C++ controllers in the bench.

The LemLib tests also need to fetch LemLib's source (git or a download) on their
first run; offline they are skipped, unless VEXSIM_REQUIRE_CXX is set (CI).
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np
import pytest

from vexsim.algorithms.localization.base import Pose
from vexsim.bench.scenario import load_scenario
from vexsim.bench.trial import ROBOT_CODE, encode_task
from vexsim.bridge.build import BuildError, _stage, asset_symbol, project_templates
from vexsim.bridge.program import CppProgram
from vexsim.config import load_robot
from vexsim.runtime.simulation import Simulation

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
TEMPLATE = EXAMPLES / "pros_projects" / "lemlib_template"
LEMLIB_ROBOT = EXAMPLES / "robots" / "lemlib_example.yaml"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def console(sim: Simulation) -> list[str]:
    return [re.sub(r"^\[\s*[\d.]+\] ", "", line) for line in sim.console]


# --- project files (no compiler) ----------------------------------------------------------------


def test_template_system_files_come_from_project_pros():
    templates = project_templates(TEMPLATE)
    assert templates["kernel"].version == "4.2.1"
    assert templates["LemLib"].version == "0.5.6"
    assert "include/lemlib/api.hpp" in templates["LemLib"].system_files
    assert "firmware/LemLib.a" in templates["LemLib"].system_files


def test_staging_leaves_out_template_files(tmp_path):
    project = tmp_path / "p"
    write(project / "src" / "main.cpp", "")
    write(project / "include" / "main.h", "")
    write(project / "include" / "vendor" / "lib.hpp", "")
    write(project / "include" / "mine.hpp", "")
    staged = tmp_path / "stage"
    sources = _stage(project, staged, {"include/vendor", "include/mine.hpp"})
    assert sources == [staged / "src" / "main.cpp"]
    assert (staged / "include" / "main.h").exists()
    assert not (staged / "include" / "vendor").exists()
    assert not (staged / "include" / "mine.hpp").exists()


def test_asset_symbols_follow_objcopy():
    assert asset_symbol("static/example.txt") == "static_example_txt"
    assert asset_symbol("static/paths/skills-1.txt") == "static_paths_skills_1_txt"


def test_benchmark_task_encoding_uses_lemlib_convention():
    scenario = load_scenario(EXAMPLES / "scenarios" / "lemlib_vs_python.yaml").scenario
    text = encode_task(scenario.task, Pose(1, 2, 90), 6, {"lead": 0.5})
    fields = dict(f.split("=", 1) for f in text.split(";"))
    assert fields["type"] == "move_to_pose"
    assert fields["start"] == "1,2,0"  # facing +y is theta 0 in LemLib
    assert fields["target"] == "30,30,0"
    assert fields["timeout_ms"] == "6000"
    assert fields["opt.lead"] == "0.5"


# --- building (g++, no LemLib) ------------------------------------------------------------------


ASSET_PROGRAM = """\
#include "main.h"
#include "lemlib/asset.hpp"

ASSET(hello_txt);
ASSET(paths_square_csv);

extern "C" void initialize() {
    const char* hello = (const char*)hello_txt.buf;
    printf("hello %u [%.*s]\\n", (unsigned)hello_txt.size, (int)hello_txt.size, hello);
    printf("square %u ends with NUL %d\\n", (unsigned)paths_square_csv.size,
           paths_square_csv.buf[paths_square_csv.size] == 0);
    printf("infinity %d\\n", infinity() > 1e308);  // newlib extension
    printf("%s\\n", helper_text());
}
"""


def test_assets_pros_include_rules_and_newlib(build, tmp_path):
    project = tmp_path / "assets"
    write(project / "include" / "main.h", '#include "api.h"\n')
    # PROS adds include/<dir> for sources in src/<dir>/, so a bare "helper.hpp" works there.
    write(project / "include" / "util" / "helper.hpp", "const char* helper_text();\n")
    write(
        project / "src" / "util" / "helper.cpp",
        '#include "helper.hpp"\nconst char* helper_text() { return "helper ok"; }\n',
    )
    write(project / "src" / "main.cpp", '#include "util/helper.hpp"\n' + ASSET_PROGRAM)
    write(project / "static" / "hello.txt", "hi there")
    (project / "static" / "paths").mkdir()
    (project / "static" / "paths" / "square.csv").write_bytes(b"0,0\n24,0\n" * 3)
    exe = build(project).executable
    sim = Simulation(load_robot(LEMLIB_ROBOT), program=CppProgram(exe), echo=None)
    sim.start("driver")
    sim.run_for(0.01)
    sim.close()
    assert console(sim) == [
        "hello 8 [hi there]",
        "square 27 ends with NUL 1",
        "infinity 1",
        "helper ok",
    ]


def test_missing_asset_explains_itself(build, tmp_path):
    project = tmp_path / "noasset"
    write(
        project / "src" / "main.cpp",
        '#include "api.h"\n#include "lemlib/asset.hpp"\nASSET(nothing_txt);\n'
        'extern "C" void initialize() { printf("%u", (unsigned)nothing_txt.size); }\n',
    )
    with pytest.raises(BuildError, match="needs a file static/"):
        build(project)


# --- LemLib --------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def template_exe(lemlib_build):
    result = lemlib_build(TEMPLATE)
    assert result.lemlib == "0.5.6"
    return result.executable


def run_template(exe, seconds: float) -> Simulation:
    sim = Simulation(
        load_robot(LEMLIB_ROBOT), program=CppProgram(exe), start=Pose(0, 0, 90), echo=None
    )
    sim.start("autonomous")
    try:
        sim.run_for(seconds)
    finally:
        sim.close()
    return sim


def test_lemlib_example_runs_unchanged(template_exe):
    # The template carries stand-ins for LemLib's template headers that #error if used, so
    # building at all shows they were replaced by the source.
    sim = run_template(template_exe, 12.0)
    out = console(sim)
    assert any(line.startswith("autonomous done at") for line in out), out
    assert sim.lcd[4] == "pure pursuit finished!"
    assert sim.lcd[0].startswith("X: ")  # LemLib's own brain-screen task
    rows = np.array([(r[2], r[3]) for r in sim.recorder.rows])
    assert np.hypot(rows[:, 0], rows[:, 1]).max() > 30  # the path ends near (18, 37)
    true = Pose.from_si(sim.robot.pose)
    assert np.hypot(true.x, true.y) < 4  # moveToPoint(0, 0) brought it back


def test_lemlib_pose_is_read_back(template_exe):
    sim = run_template(template_exe, 1.0)
    assert sim.reported_pose is None  # calibrating: LemLib's odometry hasn't started
    sim = run_template(template_exe, 12.0)
    true, est = Pose.from_si(sim.robot.pose), sim.estimated_pose
    assert est is sim.reported_pose
    assert true.distance_to(est) < 1.0  # LemLib's tracking-wheel odometry vs. the truth
    assert abs(true.heading_error(est)) < 3.0


EDITED_PID_PROGRAM = """\
#include "main.h"
#include "lemlib/api.hpp"

lemlib::PID pid(1, 0, 0);

extern "C" void initialize() {
    pid.kP = 2.5;  // only possible with this project's edited pid.hpp
    printf("kP %.1f output %.1f\\n", pid.kP, pid.update(2));
}
"""


def test_edited_lemlib_headers_are_used_as_on_the_robot(lemlib_build, in_cache, tmp_path):
    from vexsim.bridge import lemlib

    lemlib_build(TEMPLATE)  # fetches LemLib (skips when offline)
    with in_cache():
        source = lemlib.source_dir("0.5.6")
    project = tmp_path / "edited"
    shutil.copytree(TEMPLATE, project, ignore=shutil.ignore_patterns("lemlib", "src"))
    shutil.copytree(source / "include" / "lemlib", project / "include" / "lemlib")
    pid = project / "include" / "lemlib" / "pid.hpp"
    text = pid.read_text().replace("    protected:\n", "\n")
    pid.write_text(re.sub(r"const (float|bool) ", r"\1 ", text))
    write(project / "src" / "main.cpp", EDITED_PID_PROGRAM)
    result = lemlib_build(project)
    assert result.notes == [
        "the project's LemLib headers differ from LemLib 0.5.6's (include/lemlib/pid.hpp); "
        "its code compiles against its own copies, as on the robot"
    ]
    sim = Simulation(load_robot(LEMLIB_ROBOT), program=CppProgram(result.executable), echo=None)
    sim.start("driver")
    sim.run_for(0.01)
    sim.close()
    assert console(sim) == ["kP 2.5 output 5.0"]  # LemLib's own PID, built from its source


def test_lemlib_controller_in_the_bench(lemlib_build, in_cache, tmp_path):
    from vexsim.bench.runner import run_bench

    lemlib_build(EXAMPLES / "pros_projects" / "lemlib_bench")  # skips when offline
    scenario = tmp_path / "s.yaml"
    source = (EXAMPLES / "scenarios" / "lemlib_vs_python.yaml").read_text()
    source = source.replace("../robots/", f"{(EXAMPLES / 'robots').as_posix()}/")
    source = source.replace("../pros_projects/", f"{(EXAMPLES / 'pros_projects').as_posix()}/")
    scenario.write_text(source)
    with in_cache():
        result = run_bench(scenario, [0, 1], workers=1)
    assert result.combos() == [
        ("tracking wheels + IMU", "Python boomerang"),
        (ROBOT_CODE, "LemLib moveToPose"),
    ]
    lemlib = [r for r in result.rows if r["controller"] == "LemLib moveToPose"]
    assert len(lemlib) == 2 and all(r["localizer"] == ROBOT_CODE for r in lemlib)
    for row in lemlib:
        assert not row["timed_out"] and row["final_error_in"] < 3.0
        assert 0.5 < row["completion_time_s"] < 6.0
    json.dumps(result.summary())  # serializable for the report

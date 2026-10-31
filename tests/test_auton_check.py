"""Phase 14.5: the autonomous check's pieces, on runs made to a known answer.

The whole check (1239E's Left 40 on a simulated "real" robot, calibrated and not) is in
test_calibration_sessions.py, marked ``session``.
"""

import math

import numpy as np
import pytest

from tests.conftest import ROOT
from vexsim.calibration.auton import (
    AutonError,
    Marks,
    RealRun,
    SimRun,
    compare,
    end_pose,
    load_marks,
    named_corners,
    parse_end,
    routine_for,
    tape_marks,
)
from vexsim.calibration.log import RobotLog
from vexsim.cli import main
from vexsim.config import load_field, load_robot

ROBOT = ROOT / "examples" / "robots" / "1239e_2026-27.yaml"
FIELD = ROOT / "examples" / "fields" / "1239e_2026-27.yaml"
PROJECT = ROOT / "examples" / "pros_projects" / "1239e_2026-27"
CONFIG, FIELD_CONFIG = load_robot(ROBOT), load_field(FIELD)


# --- the end, from tape marks -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "front-left: 23.5 from -x, 40 from +y; back-right: 35.25 from -x, 52 from +y",
        "FL -x 23.5 +y 40, BR -x 35 1/4 +y 52",
        "left front 23.5 in from -x and 40 in from +y, right back 35.25 from -x and 52 from +y",
    ],
)
def test_tape_marks_read_however_theyre_written(text):
    corners = parse_end(text)
    assert [(c.name, c.x_wall, c.x_in, c.y_wall, c.y_in) for c in corners] == [
        ("front-left", "-x", 23.5, "+y", 40.0),
        ("back-right", "-x", 35.25, "+y", 52.0),
    ]


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ("front-left: 23.5 from -x; back-right: 3 from -x, 4 from +y", "one x wall and one y"),
        ("top-left: 1 from -x, 2 from +y; back-right: 3 from -x, 4 from +y", "name each corner"),
        ("front-left: 1 from -x, 2 from +y", "two different corners"),
        ("FL 1 -x 2 +y, FL 3 -x 4 +y", "two different corners"),
        ("FL 1 -x 2 -x, BR 3 -x 4 +y", "one x wall and one y"),
    ],
)
def test_tape_marks_that_dont_read_say_why(text, says):
    with pytest.raises(AutonError, match=says):
        parse_end(text)


@pytest.mark.parametrize("pose", [(47.95, 22.82, 205.3), (-30.0, 10.0, 90.0), (5.0, -40.0, 333.0)])
def test_the_end_pose_comes_back_from_its_tape_marks(pose):
    text = tape_marks(CONFIG, FIELD_CONFIG, pose, step=0.01)
    found = end_pose(CONFIG, FIELD_CONFIG, parse_end(text))
    assert math.dist(found.pose[:2], pose[:2]) < 0.02
    assert abs((found.heading - pose[2] + 180) % 360 - 180) < 0.1
    assert found.misfit_in < 0.03


def test_marks_that_dont_fit_the_robot_show_it():
    corners = parse_end("FL: 30 from -x, 40 from +y; BR: 47 from -x, 52 from +y")  # 21 in apart
    found = end_pose(CONFIG, FIELD_CONFIG, corners)
    assert found.misfit_in == pytest.approx(math.hypot(17, 12) - math.hypot(14, 12.5), abs=0.01)
    body = CONFIG.body.model_copy(update={"footprint_in": (5.0, 4.0)})
    small = CONFIG.model_copy(update={"body": body})  # its front corners 4 in apart
    with pytest.raises(AutonError, match="too close together"):
        end_pose(
            small, FIELD_CONFIG, parse_end("FL: 30 from -x, 40 from +y; FR: 30 from -x, 44 from +y")
        )


def test_the_robots_corners_are_its_outlines_furthest():
    assert named_corners(CONFIG) == {
        "front-left": (7.0, 6.25),
        "front-right": (7.0, -6.25),
        "back-left": (-7.0, 6.25),
        "back-right": (-7.0, -6.25),
    }


# --- the pass marks ---------------------------------------------------------------------------


def test_the_pass_marks_are_the_teams_if_it_has_them(tmp_path):
    assert load_marks(tmp_path) == Marks()
    team = tmp_path / "workspace"
    (team / ".vexsim").mkdir(parents=True)
    (team / ".vexsim" / "calibration.yaml").write_text("max_distance_in: 1.5\nmax_heading_deg: 3\n")
    inside = team / "logs" / "today"
    inside.mkdir(parents=True)
    marks = load_marks(inside)  # the nearest folder above that has one
    assert (marks.max_distance_in, marks.max_heading_deg) == (1.5, 3.0)
    assert "calibration.yaml" in marks.source
    marks = load_marks(inside, max_heading_deg=5.0)  # the command line's over the team's
    assert (marks.max_distance_in, marks.max_heading_deg) == (1.5, 5.0)
    (team / ".vexsim" / "calibration.yaml").write_text("max_distance_in: -1\n")
    with pytest.raises(AutonError, match="above 0"):
        load_marks(inside)


def test_marks_finer_than_a_tape_measure_warn():
    assert Marks(2.0, 2.0).warnings() == []
    warnings = Marks(0.25, 0.5).warnings()
    assert len(warnings) == 2 and "tape measure" in warnings[0]


def test_a_log_names_its_routine():
    assert routine_for(PROJECT, "Left 40") == "left40"
    with pytest.raises(AutonError, match="--routine"):
        routine_for(PROJECT, "Left 99")


# --- comparing, on made-up runs ---------------------------------------------------------------


def logged(path: np.ndarray) -> RobotLog:
    """A log of a code's pose (rows of time s, x, y in, heading degrees counter-clockwise),
    still at the origin for a moment before the routine's setPose puts it at its start."""
    rows = [[t * 1000.0, 0.0, 0.0, 90.0] for t in np.arange(0, 0.2, 0.01)]
    rows += [[1000 * (0.2 + t), x, y, 90.0 - h] for t, x, y, h in path]
    names = ["time_ms", "pose_lemlib_x_in", "pose_lemlib_y_in", "pose_lemlib_theta_deg"]
    return RobotLog.from_rows(names, rows, {"name": "Left 40"})


def drive(speed: float = 20.0, seconds: float = 5.0, offset: float = 0.0) -> np.ndarray:
    """Straight along +x from (10, 0) at ``speed`` in/s, ``offset`` in to the side."""
    t = np.arange(0, seconds, 0.01)
    return np.column_stack([t, 10 + speed * t, np.full(len(t), offset), np.zeros(len(t))])


MARKS = Marks(2.0, 2.0)


def made_check(real_path, real_end, sim_paths, sim_ends, marks=MARKS):
    from vexsim.calibration.auton import EndPose

    run = RealRun("real.csv", logged(real_path), EndPose(*real_end, 0.0, ()))
    sims = [
        SimRun(k, end, end, logged(p), np.zeros((0, 4)))
        for k, (p, end) in enumerate(zip(sim_paths, sim_ends, strict=True))
    ]
    return compare("left40", (10.0, 0.0, 0.0), marks, [run], sims)


def test_a_run_like_the_simulated_ones_passes():
    found = made_check(drive(), (110.3, 0.2, 0.5), [drive()] * 3, [(110.0, 0.0, 0.0)] * 3)
    assert found.passed and found.run_rms_in == pytest.approx(0.0, abs=1e-6)
    assert found.end_off[0] == pytest.approx(math.hypot(0.3, 0.2))
    assert found.runs[0].parted_s is None


def test_a_run_that_ends_elsewhere_fails_on_its_end():
    found = made_check(drive(), (113.0, 0.0, 3.0), [drive()] * 3, [(110.0, 0.0, 0.0)] * 3)
    assert not found.passed
    assert any("ends 3.0 in" in f for f in found.failures)
    assert any("turned 3.0 degrees" in f for f in found.failures)


def test_a_run_that_drives_differently_fails_on_the_run_though_it_ends_the_same():
    # the simulated robot is faster: the same path, sooner, ending in the same place
    found = made_check(drive(), (110.0, 0.0, 0.0), [drive(speed=24)] * 3, [(110.0, 0.0, 0.0)] * 3)
    assert not found.passed and found.end_off[0] == pytest.approx(0.0)
    assert found.run_rms_in > 2 and "through the run" in found.failures[0]
    assert found.runs[0].parted_s == pytest.approx(0.5, abs=0.02)  # 2 in apart at 4 in/s


def test_spreads_tell_when_the_marks_are_tighter_than_the_simulation_can_tell():
    ends = [(107.0, 0.0, 0.0), (110.0, 0.0, 0.0), (113.0, 0.0, 0.0)]
    found = made_check(drive(), (110.0, 0.0, 0.0), [drive()] * 3, ends)
    assert found.sim_spread == pytest.approx((3.0, 0.0))
    assert any("the simulated runs alone end up to 3.0 in" in w for w in found.warnings)


def test_check_auton_needs_an_end_for_each_log(tmp_path, capsys):
    log = tmp_path / "left40.csv"
    logged(drive()).write(log)
    args = ["calibration", "check-auton", str(ROBOT), str(log), str(log), "--program", str(PROJECT)]
    assert main([*args, "--field", str(FIELD), "--end", "FL 1 -x 2 +y, BR 3 -x 4 +y"]) != 0
    assert "one --end for each log" in capsys.readouterr().out


def test_logs_of_different_routines_arent_checked_together(tmp_path, capsys):
    left, right = tmp_path / "left.csv", tmp_path / "right.csv"
    logged(drive()).write(left)
    other = logged(drive())
    other.info["name"] = "Right 30"
    other.write(right)
    end = "FL 1 -x 2 +y, BR 3 -x 4 +y"
    args = ["calibration", "check-auton", str(ROBOT), str(left), str(right)]
    args += ["--program", str(PROJECT), "--field", str(FIELD), "--end", end, "--end", end]
    assert main(args) != 0
    assert "different routines (Left 40, Right 30)" in capsys.readouterr().out

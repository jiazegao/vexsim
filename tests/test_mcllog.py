"""MCL logs (vexsim.mcllog) and following one's path (vexsim.runtime.follow, run --follow)."""

from __future__ import annotations

import argparse
import math
import shutil
from pathlib import Path

import pytest

from vexsim.app import runs
from vexsim.app.runspec import Follow, RunError, RunSpec, check, program_factory, simulation_factory
from vexsim.app.workspace import Workspace
from vexsim.cli import build_parser
from vexsim.config import load_robot
from vexsim.mcllog import MclLog, MclLogError, looks_like_one, parse
from vexsim.runtime.follow import ExpoCurve, LoggedPath, PathFollower, drive_geometry

ROOT = Path(__file__).resolve().parents[1]
ROBOT = ROOT / "examples" / "robots" / "traction_6m.yaml"
TANK = ROOT / "examples" / "programs" / "tank_drive.py"


def log_text(poses, *, dt=0.03, sensors=5, particles=1, t0=1.5) -> str:
    """An MCL log in 1239E's format along ``poses`` (x, y, theta in radians)."""
    lines = []
    for i, (x, y, theta) in enumerate(poses):
        for k in range(sensors):
            lines.append(f"{9999 if k == 0 else 500 + k},{x},{y},{theta + k}")
        lines += [f"{x + 0.5},{y - 0.5}"] * particles
        lines += [f"{t0 + i * dt:.3f}", f"{x},{y},{theta}", "1.5,2,"]
    return "\n".join(lines) + "\n"


def straight(n: int = 101, speed_in_s: float = 20.0, dt: float = 0.03):
    """Driving +x from (-20, 10) at a steady speed, then still for 30 updates."""
    poses = [(-20 + speed_in_s * dt * min(i, n), 10.0, 0.0) for i in range(n + 30)]
    return poses


def test_logs_read_update_by_update(tmp_path):
    text = log_text([(1, 2, 0.5), (1.5, 2.5, 0.6), (2, 3, 0.7)])
    updates = parse(text)
    assert len(updates) == 3
    first = updates[0]
    assert first.t == 1.5 and first.estimate == (1, 2, 0.5) and first.spread == (1.5, 2)
    assert first.sensors[0] == (9999, 1, 2, 0.5) and first.particles == ((1.5, 1.5),)
    cut = text.splitlines()[:-4]  # switched off while it wrote the last update
    assert len(parse("\n".join(cut))) == 2
    # any number of sensors and particles, and blank lines, read
    assert [len(u.sensors) for u in parse(log_text([(0, 0, 0)] * 2, sensors=3, particles=0))] == [
        3,
        3,
    ]
    assert len(parse(log_text([(0, 0, 0)], particles=4).replace("\n", "\n\n"))[0].particles) == 4
    with pytest.raises(MclLogError):
        parse("time_ms,battery_mv\n1,2\n")
    assert looks_like_one(text) and not looks_like_one("x: 1\n")


def test_a_log_is_a_path_and_drawings(tmp_path):
    poses = [(0, 0, 3.0), (1, 0, 3.1), (2, 0, -3.1), (3, 0, -3.0)]  # through +-pi
    (tmp_path / "mcl_log7.1239e").write_text(log_text(poses))
    log = MclLog.read(tmp_path / "mcl_log7.1239e")
    assert log.name == "mcl_log7.1239e" and log.duration == pytest.approx(0.09)
    assert log.start == (0, 0, pytest.approx(math.degrees(3.0)))
    times, path = log.path()
    # each update logs the estimate from the update before: it goes with that one's time
    assert times == pytest.approx([0, 0.03, 0.06]) and [p[0] for p in path] == [1, 2, 3]
    assert path[1][2] == pytest.approx(math.tau - 3.1)  # unwrapped: no jump at +-pi
    drawn = log.drawings(log.updates[1])
    assert set(drawn) == {"rays", "particles", "spread"}
    nothing, seen = drawn["rays"][0], drawn["rays"][1]
    assert nothing[0] == "line" and nothing[-1] == "muted"  # 9999: read nothing
    assert math.dist(nothing[1:3], nothing[3:5]) == pytest.approx(10, abs=0.01)
    assert seen[-1] == "yellow"
    assert math.dist(seen[1:3], seen[3:5]) == pytest.approx(501 / 25.4, abs=0.01)
    assert drawn["rays"][2][0] == "point"  # where the reading ends
    assert drawn["particles"] == [["point", 1.5, -0.5, "violet", 4]]
    assert drawn["spread"] == [["ellipse", 1, 0, 3, 4, 0, "blue"]]  # 2 sigma
    summary = log.summary()
    assert summary["updates"] == 4 and summary["sensors"] == 5 and summary["particles"] == 1
    assert summary["interval_ms"] == pytest.approx([30, 30, 30], abs=0.01)
    assert summary["no_reading_pct"] == 20
    tape = runs.mcl_tape(tmp_path / "mcl_log7.1239e", "logs/mcl_log7.1239e")
    assert tape["path"] == "logs/mcl_log7.1239e" and len(tape["drawings"]) == 4
    assert tape["times"][0] == 0 and tape["estimate"][1][:2] == [1, 0]


def test_lemlibs_drive_curve_inverts():
    curve = ExpoCurve(15, 20, 1.05)
    assert curve.stick(0) == 0
    for output in (25, 50, 90, 126.9):
        stick = curve.stick(output)
        assert 15 < stick <= 127
        assert dict(curve.table)[stick] == pytest.approx(output, abs=3)
    assert curve.stick(-60) == -curve.stick(60) and curve.stick(500) == 127
    assert ExpoCurve().stick(42) == 42  # no curve: the stick is the output


def test_drive_geometry_comes_from_the_robot():
    track, top_speed = drive_geometry(load_robot(ROOT / "examples/robots/1239e_2026-27.yaml"))
    assert track == pytest.approx(10.4)
    assert top_speed == pytest.approx(450 / 60 * math.pi * 3.25)


def follow_workspace(folder: Path, poses) -> Path:
    shutil.copy(ROBOT, folder / "robot.yaml")
    shutil.copy(TANK, folder / "tank.py")
    (folder / "logs").mkdir()
    (folder / "logs" / "mcl_log1.1239e").write_text(log_text(poses))
    return folder


def test_a_run_follows_a_logs_path(tmp_path):
    folder = follow_workspace(tmp_path, straight())
    spec = RunSpec(
        robot="robot.yaml",
        program="tank.py",
        mode="driver",
        start=(-20, 10, 0),
        follow=Follow(log="logs/mcl_log1.1239e"),
    )
    prepared = check(spec, folder)
    make, mode = program_factory(prepared)
    factory = simulation_factory(prepared, make, mode, echo=None)
    sim = factory()
    assert sim.run_until_finished(30)
    follower = sim.input_source
    assert isinstance(follower, PathFollower) and follower.done
    # it began with opcontrol (after initialize waits for the IMU), and the run ended with the
    # path (+0.3 s)
    assert follower.start_s == pytest.approx(2.02, abs=0.02)
    assert sim.world.time == pytest.approx(follower.start_s + 129 * 0.03 + 0.3, abs=0.03)
    x, y = (v / 0.0254 for v in sim.robot.pose[:2])
    assert x == pytest.approx(40, abs=2) and y == pytest.approx(10, abs=1)
    assert max(follower.following) < 3
    assert factory().input_source is not follower  # a restart follows it afresh


def test_following_is_part_of_a_run_spec(tmp_path):
    folder = follow_workspace(tmp_path, straight())
    log = str(folder / "logs" / "mcl_log1.1239e")
    args = build_parser().parse_args(
        ["run", "robot.yaml", "--follow", log, "--sticks", "arcade", "--curve", "15,20,1.05"]
    )
    spec = RunSpec.from_args(args)
    assert spec.start == (-20, 10, 0)  # where the log starts, with no --start
    assert spec.follow == Follow(log=log, sticks="arcade", curve=(15, 20, 1.05))
    assert spec.to_args()[-5:] == ["--follow", log, "--sticks", "arcade", "--curve=15,20,1.05"]
    again = RunSpec.from_args(build_parser().parse_args(spec.to_args()))
    assert again == spec
    args = build_parser().parse_args(["run", "r.yaml", "--follow", log, "--start=1,2,3"])
    assert RunSpec.from_args(args).start == (1, 2, 3)
    for bad, message in (
        (["--curve", "15,20"], "--curve needs"),
        (["--sticks", "tank"], "go with --follow"),
    ):
        args = build_parser().parse_args(
            ["run", "r.yaml", *bad] + (["--follow", log] if "--curve" in bad else [])
        )
        with pytest.raises(RunError, match=message):
            RunSpec.from_args(args)
    with pytest.raises(RunError, match="not an MCL log"):
        (folder / "notes.txt").write_text("hello\n")
        RunSpec.from_args(
            build_parser().parse_args(["run", "r.yaml", "--follow", str(folder / "notes.txt")])
        )


@pytest.mark.parametrize(
    "follow, extra, message",
    [
        (Follow(), {}, "pick the log to follow"),
        (Follow(log="logs/none.1239e"), {}, "log not found: logs/none.1239e"),
        (Follow(log="tank.py"), {}, "tank.py: not an MCL log"),
        (Follow(log="logs/mcl_log1.1239e"), {"input": "tank.py"}, "not both"),
    ],
)
def test_a_log_to_follow_is_checked(tmp_path, follow, extra, message):
    folder = follow_workspace(tmp_path, straight())
    with pytest.raises(RunError, match=message):
        check(RunSpec(robot="robot.yaml", program="tank.py", follow=follow, **extra), folder)


def test_the_workspace_finds_mcl_logs(tmp_path):
    folder = follow_workspace(tmp_path, straight(5))
    (folder / "logs" / "DATA.1239e").write_text("3")  # the team's log counter
    (folder / "logs" / "notes").write_text("not a log\n")
    (folder / "logs" / "picture.png").write_bytes(b"\x89PNG\x00" + log_text([(0, 0, 0)]).encode())
    found = {item.path: item for item in Workspace(folder).scan() if item.kind == "mcllog"}
    assert list(found) == ["logs/mcl_log1.1239e"]
    assert found["logs/mcl_log1.1239e"].detail == "MCL log: 5 sensors, starts at (-20.0, 10.0)"


def test_namespace_parse_needs_no_follow_flags():
    # other callers' namespaces (without --follow) still make specs
    args = argparse.Namespace(
        robot="r.yaml", program=None, field=None, mode=None, start=None, seed=0, noise=None,
        input=None, env=None, busy_timeout=5.0,
    )  # fmt: skip
    assert RunSpec.from_args(args).follow is None and RunSpec.from_args(args).start == (0, 0, 0)


def test_logged_paths_need_two_poses():
    with pytest.raises(ValueError):
        LoggedPath([0.0], [(0, 0, 0)])

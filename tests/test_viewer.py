"""Phase 5: the pygame viewer, driven headlessly with injected key events."""

import os

import pytest

pygame = pytest.importorskip("pygame")

from tests.conftest import EXAMPLE_ROBOT  # noqa: E402
from vexsim.config import load_robot  # noqa: E402
from vexsim.runtime.program import load_program  # noqa: E402
from vexsim.runtime.recorder import Log  # noqa: E402
from vexsim.runtime.simulation import Simulation  # noqa: E402
from vexsim.viz.viewer import KeyboardInput, LiveSource, ReplaySource, Viewer  # noqa: E402

CONFIG = load_robot(EXAMPLE_ROBOT)


@pytest.fixture
def driver_viewer():
    def factory():
        sim = Simulation(CONFIG, noise="ideal", echo=None)
        sim.start("driver")
        return sim

    viewer = Viewer(LiveSource(factory), headless=True)
    yield viewer
    pygame.quit()


def key(viewer, name, down=True):
    event_type = pygame.KEYDOWN if down else pygame.KEYUP
    viewer.handle(pygame.event.Event(event_type, key=pygame.key.key_code(name)))


def test_keyboard_drives_the_robot(driver_viewer):
    v = driver_viewer
    for _ in range(140):  # ~2.3 s: IMU calibrates
        v.frame(1 / 60)
    key(v, "w")
    for _ in range(60):
        v.frame(1 / 60)
    assert v.source.sim.controller.get_analog("LEFT_Y") == 127
    x, _, _ = v.source.sim.robot.pose
    assert x > 0.3
    key(v, "w", down=False)
    key(v, "d")
    for _ in range(30):
        v.frame(1 / 60)
    assert v.source.sim.robot.body_velocity[2] < -0.5  # turning clockwise


def test_pause_step_speed_and_restart(driver_viewer):
    v = driver_viewer
    v.frame(1 / 60)
    key(v, "space")
    t = v.source.time
    v.frame(1 / 60)
    assert v.source.time == t
    key(v, ".")
    assert v.source.time == pytest.approx(t + 0.001)
    key(v, "space")
    key(v, "=")
    assert v.speed == 2.0
    key(v, "-")
    key(v, "-")
    assert v.speed == 0.5
    key(v, "r")
    assert v.source.time == 0.0
    assert v.source.sim.input_source is v.keyboard


def test_keyboard_mapping():
    kb = KeyboardInput()
    kb.held = {"w", "a", "left shift", "q", "l"}
    analog, digital = kb.poll(0.0)
    assert analog == {"LEFT_Y": 63.0, "RIGHT_X": -63.0}
    assert digital == {"L1", "A"}
    kb.held = {"left ctrl", "t"}
    assert kb.poll(0.0) == ({}, {"UP"})


def test_autonomous_overlay_and_screenshot(tmp_path):
    program = load_program(
        os.path.join(os.path.dirname(EXAMPLE_ROBOT), "..", "programs", "tour.py")
    )

    def factory():
        sim = Simulation(CONFIG, program=program, noise="ideal", echo=None)
        sim.start("autonomous")
        return sim

    v = Viewer(LiveSource(factory), headless=True, speed=4.0)
    overlays = set()
    for _ in range(180):  # 4x speed: ~12 s of simulation through several motions
        v.frame(1 / 60)
        snap = v.source.snapshot()
        overlays |= {"target"} if snap.overlay_target else set()
        overlays |= {"path"} if snap.overlay_path is not None else set()
    assert overlays == {"target", "path"}  # point/pose targets, then pursuit/RAMSETE paths
    assert len(snap.wheels) == 6 and len(snap.motors) == 6
    out = tmp_path / "frame.png"
    v.save(str(out))
    assert out.stat().st_size > 5_000
    pygame.quit()


def test_replay_source(tmp_path):
    sim = Simulation(CONFIG, noise="ideal", echo=None)
    sim.start("driver")
    sim.robot.group("left").set_velocity(30)
    sim.run_for(3.0)
    log = Log.read(sim.recorder.write_csv(tmp_path / "log.csv"))
    source = ReplaySource(CONFIG, log)
    source.advance(1.5)
    snap = source.snapshot()
    assert snap.time == pytest.approx(1.5, abs=0.011) and "replay" in snap.phase
    source.advance(100)
    assert source.finished
    v = Viewer(source, headless=True)
    v.frame(1 / 60)
    pygame.quit()

import pytest

from vexsim.physics import PRIORITY_CONTROL, PRIORITY_SENSOR, World


class Recorder:
    """A physics system that records when it was stepped."""

    def __init__(self, log):
        self.log = log

    def step(self, world, dt):
        self.log.append(("physics", world.clock.us, dt))


def test_step_advances_time():
    world = World(dt_ms=1)
    world.run_for(0.25)
    assert world.steps == 250
    assert world.clock.us == 250_000
    assert world.time == pytest.approx(0.25)
    assert world.dt == pytest.approx(0.001)


def test_periodic_event_fires_on_exact_ticks():
    world = World()
    times = []
    world.every(10, lambda w: times.append(w.clock.us))
    world.run_for(1.0)
    assert times == list(range(0, 1_000_000, 10_000))


def test_offset_and_one_shot():
    world = World()
    log = []
    world.every(10, lambda w: log.append(("every", w.clock.us)), offset_ms=5)
    world.after(12, lambda w: log.append(("after", w.clock.us)))
    world.run_for(0.03)
    assert log == [("every", 5_000), ("after", 12_000), ("every", 15_000), ("every", 25_000)]


def test_tick_order_events_by_priority_then_physics():
    world = World()
    log = []
    world.add_system(Recorder(log))
    world.every(10, lambda w: log.append(("control", w.clock.us)), priority=PRIORITY_CONTROL)
    world.every(10, lambda w: log.append(("sensor", w.clock.us)), priority=PRIORITY_SENSOR)
    world.step()
    assert log == [("sensor", 0), ("control", 0), ("physics", 0, pytest.approx(0.001))]


def test_systems_step_every_tick_in_insertion_order():
    world = World(dt_ms=0.5)
    log = []
    world.add_system(Recorder(log))
    world.add_system(type("Second", (), {"step": lambda self, w, dt: log.append("second")})())
    world.run_for(0.002)
    assert [entry if isinstance(entry, str) else entry[0] for entry in log] == [
        "physics",
        "second",
    ] * 4


@pytest.mark.parametrize("period", [0, -10, 2.5])
def test_periods_must_align_with_ticks(period):
    world = World(dt_ms=1)
    with pytest.raises(ValueError):
        world.every(period, lambda w: None)


def test_run_for_rejects_partial_ticks():
    with pytest.raises(ValueError):
        World(dt_ms=1).run_for(0.0005)


def test_run_until():
    world = World()
    assert world.run_until(lambda w: w.clock.us >= 50_000, timeout_s=1.0)
    assert world.clock.us == 50_000
    assert not world.run_until(lambda w: False, timeout_s=0.01)
    assert world.clock.us == 60_000


def test_stop_from_callback():
    world = World()
    world.after(30, lambda w: w.stop("robot crashed"))
    world.run_for(1.0)
    assert world.stop_reason == "robot crashed"
    assert world.clock.us == 31_000  # the tick that called stop() completes
    world.run_for(0.01)  # a new run clears the stop request
    assert world.stop_reason is None
    assert world.clock.us == 41_000


def test_same_seed_same_run():
    def simulate(seed):
        world = World(seed=seed)
        samples = []
        world.every(
            10,
            lambda w: samples.append((w.clock.us, w.rng.stream("imu").normal())),
            priority=PRIORITY_SENSOR,
        )
        world.every(5, lambda w: samples.append((w.clock.us, w.rng.stream("enc").random())))
        world.run_for(0.5)
        return samples

    assert simulate(11) == simulate(11)
    assert simulate(11) != simulate(12)

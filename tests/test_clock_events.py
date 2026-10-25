import pytest

from vexsim.core import EventScheduler, SimClock, ms_to_us, seconds_to_us


def test_unit_conversion_is_exact():
    assert ms_to_us(1) == 1000
    assert ms_to_us(0.5) == 500
    assert ms_to_us(10.001) == 10001
    assert seconds_to_us(0.1) == 100_000
    with pytest.raises(ValueError):
        ms_to_us(0.0001)


def test_clock_has_no_float_drift():
    clock = SimClock()
    for _ in range(1_000_000):
        clock.advance(1000)
    assert clock.us == 1_000_000_000
    assert clock.seconds == 1000.0


def test_clock_only_moves_forward():
    with pytest.raises(ValueError):
        SimClock().advance(0)
    with pytest.raises(ValueError):
        SimClock(-1)


def test_ordering_by_time_then_priority_then_registration():
    sched = EventScheduler()
    log = []
    sched.schedule_at(20, lambda _: log.append("t20"))
    sched.schedule_at(10, lambda _: log.append("t10-late"), priority=5)
    sched.schedule_at(10, lambda _: log.append("t10-first-registered"))
    sched.schedule_at(10, lambda _: log.append("t10-second-registered"))
    sched.schedule_at(10, lambda _: log.append("t10-sensor"), priority=-100)
    assert sched.run_due(10, None) == 4
    assert log == ["t10-sensor", "t10-first-registered", "t10-second-registered", "t10-late"]
    assert sched.next_time_us() == 20


def test_periodic_events_keep_registration_order():
    sched = EventScheduler()
    log = []
    sched.schedule_every(10, lambda _: log.append("a"), start_us=0)
    sched.schedule_every(10, lambda _: log.append("b"), start_us=0)
    sched.schedule_at(10, lambda _: log.append("one-shot"))  # registered after a and b
    for t in (0, 10, 20):
        sched.run_due(t, None)
    assert log == ["a", "b", "a", "b", "one-shot", "a", "b"]


def test_periodic_event_does_not_drift():
    sched = EventScheduler()
    times = []
    handle = sched.schedule_every(10_000, lambda t: times.append(t), start_us=5_000)
    for now in range(0, 100_001, 1_000):
        sched.run_due(now, now)
    assert times == list(range(5_000, 100_001, 10_000))
    assert handle.fire_count == 10


def test_cancel_including_from_own_callback():
    sched = EventScheduler()
    log = []

    def once_then_stop(_):
        log.append("tick")
        handle.cancel()

    handle = sched.schedule_every(1, once_then_stop, start_us=0)
    other = sched.schedule_at(0, lambda _: log.append("never"))
    other.cancel()
    for t in range(5):
        sched.run_due(t, None)
    assert log == ["tick"]
    assert len(sched) == 0
    assert sched.next_time_us() is None


def test_event_scheduled_for_now_runs_in_same_pass():
    sched = EventScheduler()
    log = []
    sched.schedule_at(0, lambda _: sched.schedule_at(0, lambda _: log.append("chained")))
    sched.run_due(0, None)
    assert log == ["chained"]

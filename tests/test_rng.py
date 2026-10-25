import os
import subprocess
import sys

import numpy as np
import pytest

from vexsim.core import RngStreams


def draws(seed, name, n=5):
    return RngStreams(seed).stream(name).normal(size=n)


def test_same_seed_and_name_repeat():
    np.testing.assert_array_equal(draws(7, "sensor.imu.10"), draws(7, "sensor.imu.10"))


def test_names_and_seeds_are_independent():
    assert not np.array_equal(draws(7, "sensor.imu.10"), draws(7, "sensor.rotation.11"))
    assert not np.array_equal(draws(7, "sensor.imu.10"), draws(8, "sensor.imu.10"))


def test_new_streams_do_not_disturb_existing_ones():
    a = RngStreams(3)
    first = a.stream("x").normal(size=3)

    b = RngStreams(3)
    b.stream("unrelated").normal(size=100)
    np.testing.assert_array_equal(b.stream("x").normal(size=3), first)


def test_stream_is_cached():
    rng = RngStreams(1)
    assert rng.stream("a") is rng.stream("a")
    assert rng.names() == ["a"]


@pytest.mark.parametrize("seed", [-1, 1.5, "1", True])
def test_bad_seeds(seed):
    with pytest.raises(ValueError):
        RngStreams(seed)


def test_streams_match_across_processes():
    # Python's built-in hash() is salted per process; stream derivation must not use it.
    code = "from vexsim.core import RngStreams; print(RngStreams(42).stream('motor.1').random())"
    outputs = set()
    for hash_seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        result = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
        )
        outputs.add(result.stdout.strip())
    assert len(outputs) == 1
    assert outputs == {repr(RngStreams(42).stream("motor.1").random())}

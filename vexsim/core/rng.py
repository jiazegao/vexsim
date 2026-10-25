"""Named, independent random streams derived from one master seed.

Every noise source asks for its own stream by a stable name (for example
"sensor.imu.10"). Adding or removing a sensor therefore never changes the noise
another sensor sees, which keeps algorithm comparisons fair across configs.
Names are hashed with BLAKE2, not Python's salted ``hash()``, so streams are
the same in every process.
"""

from __future__ import annotations

import hashlib

import numpy as np


def _name_key(name: str) -> tuple[int, ...]:
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=16).digest()
    return tuple(int.from_bytes(digest[i : i + 4], "little") for i in range(0, 16, 4))


class RngStreams:
    def __init__(self, seed: int):
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError(f"seed must be a non-negative integer, got {seed!r}")
        self._seed = seed
        self._streams: dict[str, np.random.Generator] = {}

    @property
    def seed(self) -> int:
        return self._seed

    def stream(self, name: str) -> np.random.Generator:
        """The generator for ``name``; the same object is returned on every call."""
        if not name:
            raise ValueError("stream name must be non-empty")
        gen = self._streams.get(name)
        if gen is None:
            seq = np.random.SeedSequence(entropy=self._seed, spawn_key=_name_key(name))
            gen = np.random.Generator(np.random.PCG64(seq))
            self._streams[name] = gen
        return gen

    def names(self) -> list[str]:
        return sorted(self._streams)

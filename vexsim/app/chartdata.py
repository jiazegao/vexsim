"""Series for the browser's charts: thinned to a size worth sending, and rounded."""

from __future__ import annotations

import numpy as np


def every(count: int, limit: int) -> np.ndarray:
    """Which of ``count`` samples to send: all of them, or ``limit`` spread evenly (the
    first and the last among them)."""
    if count <= limit:
        return np.arange(count)
    return np.unique(np.linspace(0, count - 1, limit).round().astype(int))


def rounded(values, digits: int) -> list:
    """Numbers (or arrays of them) as lists, rounded; NaN stays NaN."""
    return np.round(np.asarray(values, dtype=float), digits).tolist()

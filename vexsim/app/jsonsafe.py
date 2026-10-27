"""Data as JSON can hold it, for browsers: no NaN or infinities, no numpy values."""

from __future__ import annotations

import json
import math


def finite(value):
    """``value`` as plain JSON data: NaN and infinities become null (browsers can't parse
    them), numpy scalars and arrays become Python numbers and lists."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): finite(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [finite(v) for v in value]
    if type(value).__module__ == "numpy" and hasattr(value, "tolist"):
        return finite(value.tolist())
    return value


def dumps(value) -> str:
    return json.dumps(finite(value), separators=(",", ":"))

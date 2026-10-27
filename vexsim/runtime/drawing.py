"""What robot code draws on the field, to debug it: named layers of shapes.

C++ robot code draws with ``vexsim::draw_*`` (``vexsim/sim.hpp``), Python programs with
``bot.draw``; the browser app shows the layers over the field, live and in recorded runs.
Each layer keeps what was drawn into it until it's cleared, so code that redraws a layer
clears it first::

    bot.draw.clear("plan")
    bot.draw.line("plan", 0, 0, 24, 24)
    bot.draw.pose("plan", 24, 24, 45, color="orange")

Shapes are lists, ready for JSON, in field inches, with angles in degrees counter-clockwise
from +x (C++ code gives them as LemLib does; ``sim.hpp`` turns them around):

- ``["point", x, y, color, size]``: a dot, ``size`` pixels across, whatever the zoom
- ``["line", x1, y1, x2, y2, color]``
- ``["circle", x, y, radius, color]``
- ``["ellipse", x, y, rx, ry, rotation, color]``: half-widths along x and y, then turned
- ``["pose", x, y, heading, color]``: a dot with a heading tick
- ``["text", x, y, text, color]``

Colors are names from the field's palette (``COLORS``), so drawings follow the light and
dark themes.
"""

from __future__ import annotations

import math
from collections.abc import Callable

COLORS = ("violet", "blue", "orange", "aqua", "yellow", "magenta", "green", "red", "ink", "muted")
DEFAULT_COLOR = "violet"
DEFAULT_LAYER = "debug"
MAX_LAYERS = 32
MAX_SHAPES = 2000  # per layer; more aren't drawn
MAX_TEXT = 120
MAX_NAME = 40
POINT_SIZE = 3.0

# numbers each shape takes after its kind and before its color (text: x, y, then the text)
_NUMBERS = {"point": 2, "line": 4, "circle": 3, "ellipse": 5, "pose": 3}


def layer_name(name: str) -> str:
    """A layer's name as kept: no spaces, at most MAX_NAME characters."""
    name = "".join("_" if c.isspace() or not c.isprintable() else c for c in str(name))
    return name[:MAX_NAME] or DEFAULT_LAYER


def _number(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"not a finite number: {value}")
    return round(value, 3)


def _color(color: str) -> str:
    if color not in COLORS:
        raise ValueError(f"unknown color {color!r}: use one of {', '.join(COLORS)}")
    return color


class Drawings:
    """The layers robot code has drawn. ``version`` changes whenever they do."""

    def __init__(self, warn: Callable[[str], None] | None = None):
        self.layers: dict[str, list[list]] = {}
        self.version = 0
        self._warn = warn
        self._warned: set[str] = set()

    def clear(self, layer: str) -> None:
        layer = layer_name(layer)
        if self.layers.get(layer):
            self.layers[layer] = []
            self.version += 1

    def add(self, layer: str, shape: list) -> None:
        """Add a shape (already checked) to a layer."""
        layer = layer_name(layer)
        shapes = self.layers.get(layer)
        if shapes is None:
            if len(self.layers) >= MAX_LAYERS:
                self._once(
                    "layers",
                    f"robot code drew in more than {MAX_LAYERS} layers: "
                    f"layer {layer!r} and any after it aren't shown",
                )
                return
            shapes = self.layers[layer] = []
        if len(shapes) >= MAX_SHAPES:
            self._once(
                f"shapes:{layer}",
                f"layer {layer!r} has more than {MAX_SHAPES} shapes: "
                "the rest aren't shown (clear it before drawing it again)",
            )
            return
        shapes.append(shape)
        self.version += 1

    def apply(self, command: str) -> None:
        """A drawing command from C++ robot code (``D`` lines; see sim.hpp)."""
        try:
            op, _, rest = command.partition(" ")
            layer, _, args = rest.partition(" ")
            if op == "clear":
                self.clear(layer)
            elif op == "text":
                x, y, color, *text = args.split(" ", 3)
                self.add(layer, text_shape(float(x), float(y), text[0] if text else "", color))
            elif op in _NUMBERS:
                *numbers, color = args.split()
                if len(numbers) != _NUMBERS[op] + (op == "point"):
                    raise ValueError("wrong number of values")
                values = [float(v) for v in numbers]
                if op == "point":
                    values, size = values[:2], values[2]
                    self.add(layer, point_shape(*values, color=color, size=size))
                else:
                    self.add(layer, [op, *(_number(v) for v in values), _color(color)])
            else:
                raise ValueError(f"unknown drawing {op!r}")
        except ValueError as exc:
            self._once(f"bad:{command.split(' ', 1)[0]}", f"a drawing was left out: {exc}")

    def snapshot(self) -> dict[str, list[list]]:
        """The layers that have something in them, as they are now (copies)."""
        return {name: list(shapes) for name, shapes in self.layers.items() if shapes}

    def _once(self, key: str, message: str) -> None:
        if key not in self._warned and self._warn is not None:
            self._warned.add(key)
            self._warn(f"vexsim: {message}")


def point_shape(x: float, y: float, *, color: str = DEFAULT_COLOR, size: float = POINT_SIZE):
    size = min(max(float(size), 1.0), 40.0)
    return ["point", _number(x), _number(y), _color(color), round(size, 1)]


def text_shape(x: float, y: float, text: str, color: str = "ink") -> list:
    text = "".join(c if c.isprintable() else " " for c in str(text))[:MAX_TEXT]
    return ["text", _number(x), _number(y), text, _color(color)]


class Pen:
    """``bot.draw``: shapes on the field for a Python program, in named layers.

    Inches in the field's frame, headings and rotations in degrees counter-clockwise from
    +x (as ``bot.pose`` has them); colors are the names in ``COLORS``.
    """

    def __init__(self, drawings: Drawings):
        self._drawings = drawings

    def clear(self, layer: str = DEFAULT_LAYER) -> None:
        """Empty a layer, to draw it afresh."""
        self._drawings.clear(layer)

    def point(
        self,
        layer: str,
        x: float,
        y: float,
        *,
        color: str = DEFAULT_COLOR,
        size: float = POINT_SIZE,
    ) -> None:
        """A dot ``size`` pixels across (it stays that size when the view zooms)."""
        self._drawings.add(layer, point_shape(x, y, color=color, size=size))

    def line(
        self, layer: str, x1: float, y1: float, x2: float, y2: float, *, color: str = DEFAULT_COLOR
    ) -> None:
        self._drawings.add(layer, ["line", *map(_number, (x1, y1, x2, y2)), _color(color)])

    def circle(
        self, layer: str, x: float, y: float, radius: float, *, color: str = DEFAULT_COLOR
    ) -> None:
        self._drawings.add(layer, ["circle", *map(_number, (x, y, radius)), _color(color)])

    def ellipse(
        self,
        layer: str,
        x: float,
        y: float,
        rx: float,
        ry: float,
        rotation: float = 0.0,
        *,
        color: str = DEFAULT_COLOR,
    ) -> None:
        """Half-widths ``rx`` along x and ``ry`` along y, then turned by ``rotation``."""
        numbers = map(_number, (x, y, rx, ry, rotation))
        self._drawings.add(layer, ["ellipse", *numbers, _color(color)])

    def pose(
        self, layer: str, x: float, y: float, heading: float, *, color: str = DEFAULT_COLOR
    ) -> None:
        """A pose: a dot with a tick toward ``heading``."""
        self._drawings.add(layer, ["pose", *map(_number, (x, y, heading)), _color(color)])

    def text(self, layer: str, x: float, y: float, text: str, *, color: str = "ink") -> None:
        self._drawings.add(layer, text_shape(x, y, text, color))

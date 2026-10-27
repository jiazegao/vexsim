"""What robot code draws on the field: layers of shapes (vexsim.runtime.drawing)."""

from __future__ import annotations

from typing import get_args

import pytest

from vexsim.app import runs
from vexsim.runtime import drawing
from vexsim.runtime.drawing import Drawings, Pen
from vexsim.ui.protocol import DrawColor


def test_python_programs_draw_with_a_pen():
    drawings = Drawings()
    pen = Pen(drawings)
    pen.point("plan", 1, 2)
    pen.line("plan", 0, 0, 1.23456, 2, color="orange")
    pen.circle("plan", 3, 4, 5, color="aqua")
    pen.ellipse("plan", 1, 2, 3, 4, 30, color="blue")
    pen.pose("robot", 10, 20, 90, color="ink")
    pen.text("robot", 1, 1, "two\nlines", color="muted")
    assert drawings.snapshot() == {
        "plan": [
            ["point", 1, 2, "violet", 3],
            ["line", 0, 0, 1.235, 2, "orange"],
            ["circle", 3, 4, 5, "aqua"],
            ["ellipse", 1, 2, 3, 4, 30, "blue"],
        ],
        "robot": [["pose", 10, 20, 90, "ink"], ["text", 1, 1, "two lines", "muted"]],
    }
    version = drawings.version
    pen.clear("robot")
    pen.clear("robot")  # already empty: nothing changes
    pen.clear("nothing here")
    assert drawings.version == version + 1
    assert set(drawings.snapshot()) == {"plan"}  # empty layers aren't sent
    with pytest.raises(ValueError, match="unknown color 'pink'"):
        pen.point("plan", 0, 0, color="pink")
    with pytest.raises(ValueError, match="finite"):
        pen.line("plan", 0, 0, float("nan"), 1)


def test_the_colors_are_the_protocols():
    assert drawing.COLORS == get_args(DrawColor)


def test_cpp_drawing_commands_are_read():
    warnings: list[str] = []
    drawings = Drawings(warn=warnings.append)
    for command in [
        "point mcl 1 2 3 aqua",
        "line mcl 0 0 10 0 yellow",
        "circle mcl 5 6 2.5 violet",
        "ellipse mcl 5 6 4 2 -30 blue",
        "pose mcl 12 24 0 orange",
        "text mcl -1.5 2 muted spread  2.5 in",
        "text mcl 0 0 ink",
        "clear rays",
    ]:
        drawings.apply(command)
    assert drawings.snapshot() == {
        "mcl": [
            ["point", 1, 2, "aqua", 3],
            ["line", 0, 0, 10, 0, "yellow"],
            ["circle", 5, 6, 2.5, "violet"],
            ["ellipse", 5, 6, 4, 2, -30, "blue"],
            ["pose", 12, 24, 0, "orange"],
            ["text", -1.5, 2, "spread  2.5 in", "muted"],
            ["text", 0, 0, "", "ink"],
        ]
    }
    assert warnings == []
    bad = ["point mcl 1 2 aqua", "line mcl 0 0 x 0 red", "star mcl 0 0 red", "pose mcl 0 0 0 pink"]
    for command in bad:
        drawings.apply(command)
    drawings.apply("star mcl 1 1 red")  # warned about once
    assert len(warnings) == 4
    assert all(w.startswith("vexsim: a drawing was left out") for w in warnings)
    assert "unknown drawing 'star'" in warnings[2] and "unknown color 'pink'" in warnings[3]
    assert len(drawings.snapshot()["mcl"]) == 7


def test_layers_and_shapes_are_limited(monkeypatch):
    monkeypatch.setattr(drawing, "MAX_SHAPES", 3)
    monkeypatch.setattr(drawing, "MAX_LAYERS", 2)
    warnings: list[str] = []
    pen = Pen(drawings := Drawings(warn=warnings.append))
    for i in range(5):
        pen.point("a", i, 0)
    pen.point("my layer", 0, 0)
    pen.point("c", 0, 0)
    pen.point("c", 1, 0)
    assert [len(shapes) for shapes in drawings.snapshot().values()] == [3, 1]
    assert set(drawings.layers) == {"a", "my_layer"}  # names are one word
    assert warnings == [
        "vexsim: layer 'a' has more than 3 shapes: the rest aren't shown (clear it before "
        "drawing it again)",
        "vexsim: robot code drew in more than 2 layers: layer 'c' and any after it aren't shown",
    ]
    assert drawing.layer_name("") == "debug" and len(drawing.layer_name("x" * 99)) == 40


def test_tapes_keep_drawings_as_they_change(tmp_path, monkeypatch):
    tape = runs.TapeRecorder(tmp_path, {}, {"type": "scene"})
    drawings = Drawings()
    pen = Pen(drawings)

    def sample(t: float) -> None:
        frame = {"t": t, "lcd": [], "controller_screen": []}
        tape.sample(frame, {"path": None, "target": None}, drawings)

    sample(0.0)  # nothing drawn yet: nothing kept
    pen.point("a", 1, 1)
    sample(0.05)
    sample(0.1)  # unchanged
    pen.clear("a")
    pen.point("a", 1, 1)  # drawn again, the same
    sample(0.15)
    pen.point("a", 2, 2)
    sample(0.2)
    assert tape.events["drawings"] == [
        [0.05, {"a": [["point", 1, 1, "violet", 3]]}],
        [0.2, {"a": [["point", 1, 1, "violet", 3], ["point", 2, 2, "violet", 3]]}],
    ]
    # robot code that draws a lot is kept more coarsely
    monkeypatch.setattr(runs, "MAX_DRAWN", 10)
    for i in range(3, 9):
        pen.point("a", i, i)
        sample(0.05 * i)
    kept = [t for t, _ in tape.events["drawings"]]
    assert tape.drawing_period > runs.TAPE_PERIOD_S and tape.drawn_shapes <= 10
    assert len(kept) < 8 and kept == sorted(kept)

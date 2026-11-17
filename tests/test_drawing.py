"""What robot code draws on the field: layers of shapes (vexsim.runtime.drawing)."""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import TypeAdapter

from vexsim.app import runs
from vexsim.app.session import Session
from vexsim.runtime import drawing
from vexsim.runtime.drawing import Drawings, Pen, count, packed
from vexsim.ui.protocol import DrawColor, DrawingsMessage, RunSpec, ServerMessage, Shape


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


def test_nothing_is_kept_where_nobody_watches():
    """Phase 15.1: Simulation(drawings=False), for a sweep's trials and the like."""
    off = Drawings(enabled=False)
    pen = Pen(off)
    assert not pen.shown and Pen(Drawings()).shown
    pen.point("stops", 1, 2)
    pen.clear("stops")
    off.apply("point mcl 1 2 3 violet")
    assert off.snapshot() == {} and off.version == 0
    with pytest.raises(ValueError, match="color"):  # a mistake is one, watched or not
        pen.point("stops", 1, 2, color="plaid")


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
        [0.2, {"a": [["points", "violet", 3, [1, 1, 2, 2]]]}],  # two alike: packed (15.6)
    ]
    # robot code that draws a lot is kept more coarsely
    monkeypatch.setattr(runs, "MAX_DRAWN", 10)
    for i in range(3, 9):
        pen.point("a", i, i)
        sample(0.05 * i)
    kept = [t for t, _ in tape.events["drawings"]]
    assert tape.drawing_period > runs.TAPE_PERIOD_S and tape.drawn_shapes <= 10
    assert len(kept) < 8 and kept == sorted(kept)


# --- as drawings travel: runs of points packed (phase 15.6) -----------------------------------


def test_runs_of_points_travel_as_one_shape():
    pen = Pen(drawings := Drawings())
    for x in range(4):  # a cloud: four alike
        pen.point("mcl", x, 0, color="violet", size=4)
    pen.line("mcl", 0, 0, 1, 1)  # ends the run
    pen.point("mcl", 9, 9, color="violet", size=4)  # one alone stays a point
    pen.point("mcl", 5, 5, color="red", size=4)  # another color: not the same run
    pen.point("mcl", 6, 6, color="red", size=4)
    pen.point("mcl", 7, 7, color="red", size=2)  # another size
    pen.text("notes", 1, 2, "hello")
    drawn = drawings.snapshot()
    as_drawn = {name: [list(shape) for shape in shapes] for name, shapes in drawn.items()}
    sent = packed(drawn)
    assert sent == {
        "mcl": [
            ["points", "violet", 4, [0, 0, 1, 0, 2, 0, 3, 0]],
            ["line", 0, 0, 1, 1, "violet"],
            ["point", 9, 9, "violet", 4],
            ["points", "red", 4, [5, 5, 6, 6]],
            ["point", 7, 7, "red", 2],
        ],
        "notes": [["text", 1, 2, "hello", "ink"]],
    }
    assert drawn == as_drawn == drawings.snapshot()  # what was drawn is as it was
    assert count(sent) == count(drawn) == 10  # each point of a run counts
    assert packed({}) == {} and packed({"a": []}) == {"a": []} and count({}) == 0
    # and it's a shape the protocol has, in a message and on its own
    TypeAdapter(ServerMessage).validate_python({"type": "drawings", "layers": sent})
    DrawingsMessage.model_validate({"type": "drawings", "layers": sent})
    shapes = TypeAdapter(Shape)
    assert shapes.validate_python(["points", "violet", 4, [0, 0, 1, 0]])
    for wrong in (["points", "violet", 4], ["points", "puce", 4, [0, 0]], ["points", 4, [0, 0]]):
        with pytest.raises(ValueError):
            shapes.validate_python(wrong)


def test_a_cloud_of_points_is_a_third_of_the_bytes():
    import json
    import random

    rng = random.Random(1)
    pen = Pen(drawings := Drawings())
    for _ in range(500):  # MCL's particles, as the 1239E port draws them
        pen.point("particles", rng.uniform(-72, 72), rng.uniform(-72, 72), color="violet", size=4)
    plain = len(json.dumps(drawings.snapshot(), separators=(",", ":")))
    sent = len(json.dumps(packed(drawings.snapshot()), separators=(",", ":")))
    assert sent < 0.45 * plain, (plain, sent)


def test_a_tape_counts_the_points_it_keeps(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "MAX_DRAWN", 100)
    tape = runs.TapeRecorder(tmp_path, {}, {"type": "scene"})
    pen = Pen(drawings := Drawings())
    for i in range(8):
        pen.clear("cloud")
        for x in range(20):  # twenty points a time: one shape as kept, counted as twenty
            pen.point("cloud", x, i)
        frame = {"t": 0.05 * i, "lcd": [], "controller_screen": []}
        tape.sample(frame, {"path": None, "target": None}, drawings)
    events = tape.events["drawings"]
    assert all(
        len(layers["cloud"]) == 1 and layers["cloud"][0][0] == "points" for _, layers in events
    )
    assert tape.drawn_shapes == sum(count(layers) for _, layers in events) <= 100
    assert tape.drawing_period > runs.TAPE_PERIOD_S  # kept more coarsely, past the limit


def test_a_page_that_joins_mid_run_gets_what_was_drawn(tmp_path):
    """A reload mid-run: the session's catch-up has the code's drawings and where a run that
    follows a log began, which it used to leave out (they came only when they next changed)."""
    session = Session("s1", RunSpec(robot="robot.yaml"), base=tmp_path)
    kinds = lambda: [message["type"] for message in session.catch_up()[0]]  # noqa: E731
    assert kinds() == ["session", "status"]
    session._receive({"type": "scene", "run_id": "r1"})
    layers = packed({"mcl": [["point", 1, 2, "violet", 4], ["point", 3, 4, "violet", 4]]})
    session._receive({"type": "drawings", "layers": layers})
    session._receive({"type": "following", "start": 1.25})
    assert kinds() == ["session", "scene", "drawings", "following", "status"]
    caught_up = {message["type"]: message for message in session.catch_up()[0]}
    assert caught_up["drawings"]["layers"] == {"mcl": [["points", "violet", 4, [1, 2, 3, 4]]]}
    assert caught_up["following"]["start"] == 1.25
    session._receive({"type": "drawings", "layers": {}})  # the code cleared them: so they are
    assert {m["type"]: m for m in session.catch_up()[0]}["drawings"]["layers"] == {}
    session._receive({"type": "scene", "run_id": "r2"})  # a run begins: the last one's are gone
    assert kinds() == ["session", "scene", "status"]

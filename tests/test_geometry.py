"""Phase 12.2: the geometry of robot shapes (vexsim/geometry.py): the union of rectangles,
circles and outlines, its edge, and what the physics and checks ask of it."""

import math

import numpy as np
import pytest

from vexsim.geometry import Circle, Outline, Polygon, polygon_problem

rect = Polygon.rect


def by_grid(outline: Outline, step: float = 0.01) -> tuple[float, tuple[float, float], float]:
    """Area, centroid and polar moment about the centroid by counting grid cells: the check
    on the edge's exact numbers."""
    x0, y0, x1, y1 = outline.bounds
    gx, gy = np.meshgrid(np.arange(x0 + step / 2, x1, step), np.arange(y0 + step / 2, y1, step))
    inside = np.zeros(gx.shape, dtype=bool)
    for part in outline.parts:
        if isinstance(part, Circle):
            inside |= np.hypot(gx - part.center[0], gy - part.center[1]) < part.radius
        else:
            odd = np.zeros(gx.shape, dtype=bool)
            for (ax, ay), (bx, by) in part.edges():
                if ay != by:
                    odd ^= ((ay > gy) != (by > gy)) & (gx < ax + (gy - ay) * (bx - ax) / (by - ay))
            inside |= odd
    xs, ys = gx[inside], gy[inside]
    cx, cy = xs.mean(), ys.mean()
    cell = step * step
    return len(xs) * cell, (cx, cy), float(((xs - cx) ** 2 + (ys - cy) ** 2).sum() * cell)


def cycle(loop) -> list:
    """A loop from its least point on: loops that differ only in where they start match."""
    k = loop.index(min(loop))
    return loop[k:] + loop[:k]


# --- the edge --------------------------------------------------------------------------------


def test_a_rectangle_is_its_own_edge():
    shape = Outline([rect((0, 0), (15, 12))])
    assert len(shape.segments) == 4 and shape.arcs == []
    area, centroid, polar = shape.moments
    assert area == pytest.approx(180) and centroid == pytest.approx((0, 0))
    assert polar / area == pytest.approx((15**2 + 12**2) / 12)  # a box's m(L^2 + W^2)/12
    assert shape.bounds == pytest.approx((-7.5, -6, 7.5, 6))
    assert shape.loops() == [[(7.5, 6.0), (-7.5, 6.0), (-7.5, -6.0), (7.5, -6.0)]]


def test_overlapping_parts_merge_into_one_edge():
    # a circle half inside a square: the edge is the square's three sides, two pieces of its
    # fourth, and the half of the circle outside
    shape = Outline([rect((0, 0), (10, 10)), Circle((5, 0), 2)])
    assert len(shape.segments) == 5 and len(shape.arcs) == 1
    assert shape.arcs[0].sweep == pytest.approx(math.pi)
    assert shape.area == pytest.approx(100 + 2 * math.pi)
    assert len(shape.loops()) == 1
    two = Outline([Circle((0, 0), 2), Circle((2, 0), 2)])
    lens = 2 * 4 * math.acos(2 / 4) - 1 * math.sqrt(16 - 4)  # their overlap
    assert two.area == pytest.approx(2 * math.pi * 4 - lens)


def test_shared_and_repeated_edges_are_inside():
    # stacked: the edge between them is no edge; side by side along one line: one edge
    stacked = Outline([rect((5, 2.5), (10, 5)), rect((5, 7.5), (10, 5))])
    assert stacked.area == pytest.approx(100)
    [loop] = stacked.loops()
    assert cycle(loop) == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    along = Outline([rect((5, 2.5), (10, 5)), rect((10, 2.5), (10, 5))])
    assert along.area == pytest.approx(75)
    assert len(along.loops()[0]) == 4
    twice = Outline(
        [rect((0, 0), (4, 4)), rect((0, 0), (4, 4)), Circle((2, 0), 1), Circle((2, 0), 1)]
    )
    assert twice.area == pytest.approx(16 + math.pi / 2)


def test_parts_around_a_hole_leave_it_empty():
    ring = Outline(
        [
            rect((0, 4), (10, 2)),
            rect((0, -4), (10, 2)),
            rect((4, 0), (2, 10)),
            rect((-4, 0), (2, 10)),
        ]
    )
    assert ring.area == pytest.approx(64)
    outer, hole = ring.loops()
    assert len(outer) == 4 and len(hole) == 4
    signed = [
        sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(loop, loop[1:] + loop[:1], strict=True))
        for loop in (outer, hole)
    ]
    assert signed[0] > 0 > signed[1]  # the hole goes the other way round
    assert not ring.contains((0, 0)) and ring.contains((4.5, 0))


def test_area_centroid_and_inertia_match_counting_cells():
    shape = Outline([
        rect((0, 0), (12, 14)),
        Circle((-6, 0), 3),
        Polygon.of([(6, 7), (9, 7), (9, 2.5), (7, 0), (9, -2.5), (9, -7), (6, -7)]),
        rect((2, 8), (4, 3), math.radians(30)),
    ])  # fmt: skip
    area, centroid, polar = shape.moments
    counted, middle, spread = by_grid(shape)
    assert area == pytest.approx(counted, rel=1e-3)
    assert centroid == pytest.approx(middle, abs=2e-3)
    assert polar == pytest.approx(spread, rel=1e-3)


# --- what the physics asks -------------------------------------------------------------------


NOTCHED = Outline([Polygon.of([(0, 0), (10, 0), (10, 10), (5, 5), (0, 10)])])  # a V in its top


def test_a_disc_in_a_notch_touches_both_sides():
    (_, d1, n1, p1), (_, d2, n2, p2) = NOTCHED.discs([[5, 6.5]], 1.2)
    side = (6.5 - 5) / math.sqrt(2)  # from the center to each side
    assert d1 == pytest.approx(1.2 - side) and d2 == pytest.approx(1.2 - side)
    assert {tuple(np.round(n1, 6)), tuple(np.round(n2, 6))} == {
        (-0.707107, 0.707107),
        (0.707107, 0.707107),
    }
    assert {tuple(p1), tuple(p2)} == {(5.75, 5.75), (4.25, 5.75)}


def test_a_disc_at_a_corner_touches_it_once():
    [(_, depth, normal, point)] = NOTCHED.discs([[10.5, -0.5]], 1.0)
    assert depth == pytest.approx(1 - math.sqrt(0.5))
    assert normal == pytest.approx([math.sqrt(0.5), -math.sqrt(0.5)])  # out through the corner
    assert tuple(point) == (10, 0)


def test_a_disc_centered_inside_goes_out_the_nearest_way():
    [(_, depth, normal, point)] = NOTCHED.discs([[5, 1]], 0.5)
    assert depth == pytest.approx(1.5) and normal == pytest.approx([0, -1])
    assert tuple(point) == (5, 0)
    # radius 0: the points inside
    assert [(i, d) for i, d, _, _ in NOTCHED.discs([[5, 1], [20, 20], [9, 5]], 0.0)] == [
        (0, 1),
        (2, 1),
    ]


def test_signed_distance_reach_and_front():
    distance, normal, point = NOTCHED.signed_distance((5, -2))
    assert distance == pytest.approx(2) and normal == pytest.approx([0, -1])
    assert NOTCHED.signed_distance((5, 1))[0] == pytest.approx(-1)
    shape = Outline([rect((0, 0), (12, 14)), Circle((-6, 0), 3)])
    assert shape.reach() == pytest.approx(math.hypot(6, 7))
    assert shape.extreme((-1, 0)) == pytest.approx(9)  # the circle's back
    assert shape.extreme((0, 1)) == pytest.approx(7)
    assert shape.front() == pytest.approx(6)
    notch = Outline(
        [
            Polygon.of([(6, 7), (9, 7), (9, 2.5), (7, 0), (9, -2.5), (9, -7), (6, -7)]),
            rect((0, 0), (12, 14)),
        ]
    )
    assert notch.front() == pytest.approx(7)  # the +x axis leaves it at the notch
    assert Outline([Circle((5, 3), 1)]).front() == pytest.approx(6)  # misses it: the furthest


def test_overlap_with_a_convex_polygon():
    shape = Outline([rect((0, 0), (12, 14)), Circle((-6, 0), 3)])
    assert shape.overlaps(rect((0, 0), (2, 2)))  # inside it
    assert shape.overlaps(rect((0, 0), (40, 1)))  # across it: no corner inside either
    assert not shape.overlaps(rect((0, 9), (40, 4)))  # touching its side
    assert shape.overlaps(rect((-9.5, 0), (2, 2)))  # into the round back
    assert not shape.overlaps(rect((-10.01, 0), (2, 2)))


def test_parts_that_touch_make_one_piece():
    assert Outline([rect((0, 0), (2, 2)), Circle((5, 0), 1), rect((4, 0), (2, 1))]).groups() == [
        [0],
        [1, 2],
    ]
    assert Outline([rect((0, 0), (2, 2)), rect((2, 0), (2, 2))]).groups() == [
        [0, 1]
    ]  # sharing a side


# --- outlines that aren't shapes -------------------------------------------------------------


CROSSES = "it crosses itself: the edge from point {} to {} meets the edge from point {} to {}"


@pytest.mark.parametrize(
    ("points", "problem"),
    [
        ([(0, 0), (10, 0), (0, 10), (10, 10)], CROSSES.format(1, 2, 3, 0)),
        ([(0, 0), (10, 0), (10, 0), (0, 10)], "points 1 and 2 are the same point"),
        ([(0, 0), (10, 0), (20, 0)], "its points are all on one line"),
        ([(0, 0), (10, 0), (5, 0), (5, 5)], "the edge from point 1 doubles back along the edge "
                                            "before it"),
        ([(0, 0), (10, 0), (10, 10), (5, 0), (0, 10)], CROSSES.format(0, 1, 2, 3)),
        ([(0, 0), (10, 0), (10, 10), (0, 10)], None),
        ([(0, 0), (0, 10), (10, 10), (10, 0)], None),  # clockwise is fine
    ],
)  # fmt: skip
def test_an_outline_must_not_cross_itself(points, problem):
    assert polygon_problem(points) == problem

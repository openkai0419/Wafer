import pytest
from PySide6 import QtCore
from wafer.plugin.layout.calc import LayoutData
from wafer.builtins.layouts import MasonryLayoutCalculator


def _make_layout(rects, hz=True):
    if not rects:
        return LayoutData.empty()
    if hz:
        total = max(r.bottom() for r in rects) + 5
    else:
        total = max(r.right() for r in rects) + 5
    return LayoutData(rects, total, hz)


def test_empty_layout_data():
    d = LayoutData.empty()
    assert len(d) == 0
    assert d.total_extent == 0
    assert not d


def test_len_and_bool():
    rects = [
        QtCore.QRect(0, 0, 100, 100),
        QtCore.QRect(105, 0, 150, 100),
        QtCore.QRect(260, 0, 80, 100),
    ]
    d = _make_layout(rects)
    assert len(d) == 3
    assert d


def test_total_extent():
    rects = [QtCore.QRect(0, 0, 100, 100)]
    d = _make_layout(rects)
    assert d.total_extent > 0


def test_getitem_returns_qrect():
    rects = [
        QtCore.QRect(0, 0, 150, 100),
        QtCore.QRect(155, 0, 100, 100),
        QtCore.QRect(260, 0, 80, 100),
    ]
    d = _make_layout(rects)
    assert d[0] == QtCore.QRect(0, 0, 150, 100)
    assert isinstance(d[0], QtCore.QRect)
    assert d[0].width() > 0
    assert d[0].height() == 100


def test_items_no_overlap_horizontal():
    rects = [
        QtCore.QRect(0, 0, 100, 100),
        QtCore.QRect(105, 0, 100, 100),
        QtCore.QRect(210, 0, 100, 100),
        QtCore.QRect(315, 0, 100, 100),
    ]
    d = _make_layout(rects)
    for i in range(len(rects) - 1):
        assert d[i].right() < d[i + 1].left()


def test_multiple_rows():
    rects = [
        QtCore.QRect(0, 0, 150, 100),
        QtCore.QRect(155, 0, 100, 100),
        QtCore.QRect(260, 0, 80, 100),
        QtCore.QRect(0, 110, 120, 100),
        QtCore.QRect(125, 110, 150, 100),
        QtCore.QRect(280, 110, 100, 100),
    ]
    d = _make_layout(rects)
    assert len(d) == 6
    assert d[0].top() == 0
    assert d[3].top() == 110


def test_calculate_visible_indices_all():
    rects = [
        QtCore.QRect(0, 0, 100, 100),
        QtCore.QRect(105, 0, 100, 100),
        QtCore.QRect(210, 0, 100, 100),
    ]
    d = _make_layout(rects)
    visible = d.calculate_visible_indices(0, 9999)
    assert set(visible) == {0, 1, 2}


def test_calculate_visible_indices_empty_layout():
    d = LayoutData.empty()
    visible = d.calculate_visible_indices(0, 1000)
    assert len(visible) == 0


def test_calculate_visible_indices_partial():
    rects = [
        QtCore.QRect(0, 0, 100, 100),
        QtCore.QRect(105, 0, 100, 100),
        QtCore.QRect(210, 0, 100, 100),
        QtCore.QRect(0, 200, 100, 100),
        QtCore.QRect(105, 200, 100, 100),
        QtCore.QRect(210, 200, 100, 100),
    ]
    d = _make_layout(rects)
    visible = d.calculate_visible_indices(0, 150)
    assert 0 in visible
    assert 3 not in visible


def test_index_at_point():
    rects = [
        QtCore.QRect(0, 0, 100, 100),
        QtCore.QRect(105, 0, 100, 100),
        QtCore.QRect(210, 0, 100, 100),
    ]
    d = _make_layout(rects)
    center = QtCore.QPoint(rects[0].center().x(), rects[0].center().y())
    assert d.index_at_point(center) == 0


def test_index_at_point_empty_space():
    rects = [QtCore.QRect(0, 0, 100, 100)]
    d = _make_layout(rects)
    result = d.index_at_point(QtCore.QPoint(9999, 9999))
    assert result is None


def test_nearest_index_to_point_uses_rect_edges():
    rects = [
        QtCore.QRect(0, 0, 100, 100),
        QtCore.QRect(120, 0, 200, 100),
    ]
    d = _make_layout(rects)
    assert d.nearest_index_to_point(QtCore.QPoint(110, 50)) == 0
    assert d.nearest_index_to_point(QtCore.QPoint(116, 50)) == 1


def test_nearest_index_to_point_respects_candidates():
    rects = [
        QtCore.QRect(0, 0, 100, 100),
        QtCore.QRect(120, 0, 100, 100),
        QtCore.QRect(240, 0, 100, 100),
    ]
    d = _make_layout(rects)
    assert d.nearest_index_to_point(QtCore.QPoint(250, 50), indices=[0, 1]) == 1


def test_nearest_index_to_point_empty_layout():
    assert LayoutData.empty().nearest_index_to_point(QtCore.QPoint(0, 0)) is None


def test_intersecting_indices():
    rects = [
        QtCore.QRect(0, 0, 100, 100),
        QtCore.QRect(105, 0, 100, 100),
        QtCore.QRect(210, 0, 100, 100),
    ]
    d = _make_layout(rects)
    rect = QtCore.QRect(0, 0, rects[1].right() + 1, 100)
    result = d.intersecting_indices(rect)
    assert 0 in result
    assert 1 in result


def test_vertical_layout():
    rects = [
        QtCore.QRect(0, 0, 100, 100),
        QtCore.QRect(0, 105, 100, 50),
    ]
    d = _make_layout(rects, hz=False)
    assert d[0].left() == 0
    assert d[0].width() == 100


def test_layout_data_basic_construction():
    rects = [QtCore.QRect(0, 0, 100, 100), QtCore.QRect(105, 0, 100, 100)]
    d = LayoutData(rects, 200, True)
    assert len(d) == 2
    assert d.total_extent == 200


class TestNearestInDirection:
    def test_forward_justified(self):
        rects = [
            QtCore.QRect(0, 0, 150, 100),
            QtCore.QRect(155, 0, 100, 100),
            QtCore.QRect(0, 110, 120, 100),
            QtCore.QRect(125, 110, 150, 100),
        ]
        d = _make_layout(rects)
        nxt = d.nearest_in_direction(0, True)
        assert nxt in (2, 3)
        assert d[nxt].y() >= d[0].y() + d[0].height()

    def test_backward_justified(self):
        rects = [
            QtCore.QRect(0, 0, 150, 100),
            QtCore.QRect(155, 0, 100, 100),
            QtCore.QRect(0, 110, 120, 100),
            QtCore.QRect(125, 110, 150, 100),
        ]
        d = _make_layout(rects)
        prev = d.nearest_in_direction(2, False)
        assert prev in (0, 1)
        assert d[prev].y() + d[prev].height() <= d[2].y()

    def test_inverted_t_backward(self):
        rects = [
            QtCore.QRect(0, 0, 100, 100),
            QtCore.QRect(0, 105, 100, 100),
            QtCore.QRect(105, 0, 100, 210),
        ]
        d = _make_layout(rects)
        assert d.nearest_in_direction(1, False) == 0
        assert d.nearest_in_direction(2, False) is None


class TestSecondaryAxisFilter:
    def test_primary_only_returns_all_columns(self):
        rects = [
            QtCore.QRect(0, 0, 100, 100),
            QtCore.QRect(500, 0, 100, 100),
            QtCore.QRect(1000, 0, 100, 100),
        ]
        d = _make_layout(rects)
        visible = d.calculate_visible_indices(0, 200)
        assert set(visible) == {0, 1, 2}

    def test_secondary_filter_excludes_offscreen(self):
        rects = [
            QtCore.QRect(0, 0, 100, 100),
            QtCore.QRect(500, 0, 100, 100),
            QtCore.QRect(1000, 0, 100, 100),
        ]
        d = _make_layout(rects)
        visible = d.calculate_visible_indices(0, 200, s_start=0, s_end=200)
        assert 0 in visible
        assert 1 not in visible
        assert 2 not in visible

    def test_secondary_filter_partial(self):
        rects = [
            QtCore.QRect(0, 0, 100, 100),
            QtCore.QRect(500, 0, 100, 100),
            QtCore.QRect(1000, 0, 100, 100),
        ]
        d = _make_layout(rects)
        visible = d.calculate_visible_indices(0, 200, s_start=400, s_end=700)
        assert 0 not in visible
        assert 1 in visible
        assert 2 not in visible

    def test_bsp_like_large_rects(self):
        rects = [
            QtCore.QRect(0, 0, 500, 5000),
            QtCore.QRect(505, 0, 500, 2500),
            QtCore.QRect(505, 2505, 500, 2500),
            QtCore.QRect(0, 5005, 1005, 5000),
        ]
        d = _make_layout(rects)
        visible_no_filter = d.calculate_visible_indices(0, 800)
        visible_filtered = d.calculate_visible_indices(0, 800, s_start=0, s_end=1100)
        assert len(visible_no_filter) >= len(visible_filtered)
        for i in visible_filtered:
            r = rects[i]
            assert r.y() < 800 and r.y() + r.height() > 0
            assert r.x() < 1100 and r.x() + r.width() > 0

    def test_secondary_filter_vertical_layout(self):
        rects = [
            QtCore.QRect(0, 0, 100, 100),
            QtCore.QRect(0, 500, 100, 100),
            QtCore.QRect(0, 1000, 100, 100),
        ]
        d = _make_layout(rects, hz=False)
        visible = d.calculate_visible_indices(0, 200, s_start=0, s_end=200)
        assert 0 in visible
        assert 1 not in visible

    def test_none_secondary_preserves_old_behavior(self):
        rects = [
            QtCore.QRect(0, 0, 100, 100),
            QtCore.QRect(500, 0, 100, 100),
        ]
        d = _make_layout(rects)
        all_vis = d.calculate_visible_indices(0, 200)
        none_vis = d.calculate_visible_indices(0, 200, s_start=None, s_end=None)
        assert set(all_vis) == set(none_vis)

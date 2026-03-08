import pytest
from PySide6 import QtCore
from wafer.app.viewer.grid.calc_layout import LayoutData, JustifiedLayoutCalculator, MasonryLayoutCalculator


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
        QtCore.QRect(0, 0, 100, 100), QtCore.QRect(105, 0, 150, 100), QtCore.QRect(260, 0, 80, 100),
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
        QtCore.QRect(0, 0, 150, 100), QtCore.QRect(155, 0, 100, 100), QtCore.QRect(260, 0, 80, 100),
    ]
    d = _make_layout(rects)
    assert d[0] == QtCore.QRect(0, 0, 150, 100)
    assert isinstance(d[0], QtCore.QRect)
    assert d[0].width() > 0
    assert d[0].height() == 100


def test_items_no_overlap_horizontal():
    rects = [
        QtCore.QRect(0, 0, 100, 100), QtCore.QRect(105, 0, 100, 100),
        QtCore.QRect(210, 0, 100, 100), QtCore.QRect(315, 0, 100, 100),
    ]
    d = _make_layout(rects)
    for i in range(len(rects) - 1):
        assert d[i].right() < d[i + 1].left()


def test_multiple_rows():
    rects = [
        QtCore.QRect(0, 0, 150, 100), QtCore.QRect(155, 0, 100, 100), QtCore.QRect(260, 0, 80, 100),
        QtCore.QRect(0, 110, 120, 100), QtCore.QRect(125, 110, 150, 100), QtCore.QRect(280, 110, 100, 100),
    ]
    d = _make_layout(rects)
    assert len(d) == 6
    assert d[0].top() == 0
    assert d[3].top() == 110


def test_calculate_visible_indices_all():
    rects = [
        QtCore.QRect(0, 0, 100, 100), QtCore.QRect(105, 0, 100, 100), QtCore.QRect(210, 0, 100, 100),
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
        QtCore.QRect(0, 0, 100, 100), QtCore.QRect(105, 0, 100, 100), QtCore.QRect(210, 0, 100, 100),
        QtCore.QRect(0, 200, 100, 100), QtCore.QRect(105, 200, 100, 100), QtCore.QRect(210, 200, 100, 100),
    ]
    d = _make_layout(rects)
    visible = d.calculate_visible_indices(0, 150)
    assert 0 in visible
    assert 3 not in visible


def test_index_at_point():
    rects = [
        QtCore.QRect(0, 0, 100, 100), QtCore.QRect(105, 0, 100, 100), QtCore.QRect(210, 0, 100, 100),
    ]
    d = _make_layout(rects)
    center = QtCore.QPoint(rects[0].center().x(), rects[0].center().y())
    assert d.index_at_point(center) == 0


def test_index_at_point_empty_space():
    rects = [QtCore.QRect(0, 0, 100, 100)]
    d = _make_layout(rects)
    result = d.index_at_point(QtCore.QPoint(9999, 9999))
    assert result is None


def test_intersecting_indices():
    rects = [
        QtCore.QRect(0, 0, 100, 100), QtCore.QRect(105, 0, 100, 100), QtCore.QRect(210, 0, 100, 100),
    ]
    d = _make_layout(rects)
    rect = QtCore.QRect(0, 0, rects[1].right() + 1, 100)
    result = d.intersecting_indices(rect)
    assert 0 in result
    assert 1 in result


def test_vertical_layout():
    rects = [
        QtCore.QRect(0, 0, 100, 100), QtCore.QRect(0, 105, 100, 50),
    ]
    d = _make_layout(rects, hz=False)
    assert d[0].left() == 0
    assert d[0].width() == 100


def test_calculator_emits_layout(qtbot):
    received = []
    calc = JustifiedLayoutCalculator([1.0, 1.5, 0.8], 100, 5, 500, None, orientation=0)
    calc.signals.layout_ready.connect(lambda ld: received.append(ld))
    calc.run()
    assert len(received) == 1
    assert isinstance(received[0], LayoutData)
    assert len(received[0]) == 3


def test_calculator_cancel():
    calc = JustifiedLayoutCalculator([1.0] * 100, 100, 5, 500, None, orientation=0)
    calc.cancel()
    received = []
    calc.signals.layout_ready.connect(lambda ld: received.append(ld))
    calc.run()
    assert len(received) == 0


def test_calculator_none_aspect_ratios(qtbot):
    received = []
    calc = JustifiedLayoutCalculator([1.0, None, 0.8], 100, 5, 500, None, orientation=0)
    calc.signals.layout_ready.connect(lambda ld: received.append(ld))
    calc.run()
    assert len(received) == 1
    assert len(received[0]) == 3


def test_calculator_zero_aspect_ratios(qtbot):
    received = []
    calc = JustifiedLayoutCalculator([1.0, 0.0, 0.8], 100, 5, 500, None, orientation=0)
    calc.signals.layout_ready.connect(lambda ld: received.append(ld))
    calc.run()
    assert len(received) == 1
    assert len(received[0]) == 3


def test_justified_rects_no_overlap(qtbot):
    received = []
    calc = JustifiedLayoutCalculator([1.5, 1.0, 0.8, 1.2, 2.0], 100, 5, 500, None, orientation=0)
    calc.signals.layout_ready.connect(lambda ld: received.append(ld))
    calc.run()
    layout = received[0]
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            assert not layout[i].intersects(layout[j])


def test_justified_reversed_horizontal(qtbot):
    received = []
    calc = JustifiedLayoutCalculator([1.5, 1.0], 100, 5, 500, None, orientation=1)
    calc.signals.layout_ready.connect(lambda ld: received.append(ld))
    calc.run()
    layout = received[0]
    assert layout[0].left() > layout[1].left()


def test_masonry_emits_layout(qtbot):
    received = []
    calc = MasonryLayoutCalculator([1.0, 1.5, 0.8, 1.2], 150, 5, 500, None, orientation=0)
    calc.signals.layout_ready.connect(lambda ld: received.append(ld))
    calc.run()
    assert len(received) == 1
    assert isinstance(received[0], LayoutData)
    assert len(received[0]) == 4


def test_masonry_columns_equal_width(qtbot):
    received = []
    calc = MasonryLayoutCalculator([1.0, 1.5, 0.8, 1.2, 1.0, 0.5], 100, 5, 500, None, orientation=0)
    calc.signals.layout_ready.connect(lambda ld: received.append(ld))
    calc.run()
    layout = received[0]
    widths = {layout[i].width() for i in range(len(layout))}
    assert len(widths) == 1


def test_masonry_no_overlap(qtbot):
    received = []
    calc = MasonryLayoutCalculator([1.0, 1.5, 0.8, 1.2, 2.0, 0.5], 100, 5, 500, None, orientation=0)
    calc.signals.layout_ready.connect(lambda ld: received.append(ld))
    calc.run()
    layout = received[0]
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            assert not layout[i].intersects(layout[j])


def test_masonry_cancel():
    calc = MasonryLayoutCalculator([1.0] * 100, 100, 5, 500, None, orientation=0)
    calc.cancel()
    received = []
    calc.signals.layout_ready.connect(lambda ld: received.append(ld))
    calc.run()
    assert len(received) == 0


def test_masonry_reversed(qtbot):
    normal_received = []
    calc = MasonryLayoutCalculator([1.0, 1.5, 0.8], 100, 5, 500, None, orientation=0)
    calc.signals.layout_ready.connect(lambda ld: normal_received.append(ld))
    calc.run()

    rev_received = []
    calc2 = MasonryLayoutCalculator([1.0, 1.5, 0.8], 100, 5, 500, None, orientation=1)
    calc2.signals.layout_ready.connect(lambda ld: rev_received.append(ld))
    calc2.run()

    normal_item0_x = normal_received[0][0].x()
    rev_item0_x = rev_received[0][0].x()
    assert normal_item0_x != rev_item0_x


def test_masonry_none_aspect_ratios(qtbot):
    received = []
    calc = MasonryLayoutCalculator([1.0, None, 0.8], 100, 5, 500, None, orientation=0)
    calc.signals.layout_ready.connect(lambda ld: received.append(ld))
    calc.run()
    assert len(received) == 1
    assert len(received[0]) == 3


def test_masonry_single_item(qtbot):
    received = []
    calc = MasonryLayoutCalculator([1.0], 100, 5, 500, None, orientation=0)
    calc.signals.layout_ready.connect(lambda ld: received.append(ld))
    calc.run()
    assert len(received) == 1
    assert len(received[0]) == 1


def test_layout_data_basic_construction():
    rects = [QtCore.QRect(0, 0, 100, 100), QtCore.QRect(105, 0, 100, 100)]
    d = LayoutData(rects, 200, True)
    assert len(d) == 2
    assert d.total_extent == 200


class TestNearestInDirection:
    def test_forward_justified(self):
        rects = [
            QtCore.QRect(0, 0, 150, 100), QtCore.QRect(155, 0, 100, 100),
            QtCore.QRect(0, 110, 120, 100), QtCore.QRect(125, 110, 150, 100),
        ]
        d = _make_layout(rects)
        nxt = d.nearest_in_direction(0, True)
        assert nxt in (2, 3)
        assert d[nxt].y() >= d[0].y() + d[0].height()

    def test_backward_justified(self):
        rects = [
            QtCore.QRect(0, 0, 150, 100), QtCore.QRect(155, 0, 100, 100),
            QtCore.QRect(0, 110, 120, 100), QtCore.QRect(125, 110, 150, 100),
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

    def test_inverted_t_forward(self):
        rects = [
            QtCore.QRect(0, 0, 100, 100),
            QtCore.QRect(0, 105, 100, 100),
            QtCore.QRect(105, 0, 100, 210),
        ]
        d = _make_layout(rects)
        assert d.nearest_in_direction(0, True) == 1

    def test_no_neighbor_single_item(self):
        rects = [QtCore.QRect(0, 0, 100, 100)]
        d = _make_layout(rects)
        assert d.nearest_in_direction(0, True) is None
        assert d.nearest_in_direction(0, False) is None

    def test_none_idx(self):
        rects = [QtCore.QRect(0, 0, 100, 100)]
        d = _make_layout(rects)
        assert d.nearest_in_direction(None, True) is None

    def test_prefers_same_column(self):
        rects = [
            QtCore.QRect(0, 0, 100, 100),
            QtCore.QRect(110, 0, 100, 100),
            QtCore.QRect(220, 0, 100, 100),
            QtCore.QRect(0, 110, 100, 100),
            QtCore.QRect(110, 110, 100, 100),
            QtCore.QRect(220, 110, 100, 100),
        ]
        d = _make_layout(rects)
        assert d.nearest_in_direction(1, True) == 4
        assert d.nearest_in_direction(4, False) == 1

    def test_vertical_layout(self):
        rects = [
            QtCore.QRect(0, 0, 100, 100),
            QtCore.QRect(0, 105, 100, 100),
            QtCore.QRect(110, 0, 100, 100),
            QtCore.QRect(110, 105, 100, 100),
        ]
        d = _make_layout(rects, hz=False)
        nxt = d.nearest_in_direction(0, True)
        assert nxt in (2, 3)
        assert d[nxt].x() >= d[0].x() + d[0].width()

    def test_masonry_varied_heights(self, qtbot):
        aspects = [1.0, 0.5, 1.5, 0.8, 2.0, 0.7, 1.2, 0.6, 0.9, 1.1, 0.4, 1.8]
        calc = MasonryLayoutCalculator(aspects, 100, 5, 400, None, orientation=0)
        received = []
        calc.signals.layout_ready.connect(lambda ld: received.append(ld))
        calc.run()
        layout = received[0]
        for i in range(len(layout)):
            fwd = layout.nearest_in_direction(i, True)
            bwd = layout.nearest_in_direction(i, False)
            if fwd is not None:
                assert (layout[fwd].y()) >= (layout[i].y() + layout[i].height())
            if bwd is not None:
                assert (layout[bwd].y() + layout[bwd].height()) <= layout[i].y()

    def test_forward_chain_no_stall(self, qtbot):
        aspects = [1.0, 0.5, 1.5, 0.8, 2.0, 0.7, 1.2, 0.6, 0.9, 1.1, 0.4, 1.8]
        calc = MasonryLayoutCalculator(aspects, 100, 5, 400, None, orientation=0)
        received = []
        calc.signals.layout_ready.connect(lambda ld: received.append(ld))
        calc.run()
        layout = received[0]
        idx = 0
        steps = 0
        for _ in range(50):
            nxt = layout.nearest_in_direction(idx, True)
            if nxt is None:
                break
            assert nxt != idx
            idx = nxt
            steps += 1
        assert steps > 0

    def test_backward_chain_no_stall(self, qtbot):
        aspects = [1.0, 0.5, 1.5, 0.8, 2.0, 0.7, 1.2, 0.6, 0.9, 1.1, 0.4, 1.8]
        calc = MasonryLayoutCalculator(aspects, 100, 5, 400, None, orientation=0)
        received = []
        calc.signals.layout_ready.connect(lambda ld: received.append(ld))
        calc.run()
        layout = received[0]
        last_idx = len(layout) - 1
        idx = last_idx
        steps = 0
        for _ in range(50):
            prev = layout.nearest_in_direction(idx, False)
            if prev is None:
                break
            assert prev != idx
            idx = prev
            steps += 1
        assert steps > 0

    def test_roundtrip_consistency(self, qtbot):
        aspects = [0.8, 1.2, 0.5, 1.5, 1.0, 0.7, 2.0, 0.6]
        calc = MasonryLayoutCalculator(aspects, 120, 5, 500, None, orientation=0)
        received = []
        calc.signals.layout_ready.connect(lambda ld: received.append(ld))
        calc.run()
        layout = received[0]
        idx = 0
        forward_path = [idx]
        for _ in range(50):
            nxt = layout.nearest_in_direction(idx, True)
            if nxt is None:
                break
            idx = nxt
            forward_path.append(idx)
        backward_path = [idx]
        for _ in range(50):
            prev = layout.nearest_in_direction(idx, False)
            if prev is None:
                break
            idx = prev
            backward_path.append(idx)
        assert forward_path[-1] == backward_path[0]
        assert backward_path[-1] == forward_path[0]

import pytest
from PySide6 import QtCore
from source.image_viewer.viewer.calc_layout import LayoutData, JustifiedLayoutCalculator


def _make_layout(aspects, base_height=100, spacing=5, container_width=500, hz=True, reverse=False, groups=None):
    if groups is None:
        groups = [(0, len(aspects), 0, 1.0)]
    return LayoutData(aspects, base_height, spacing, container_width, hz, reverse, groups)


def test_empty_layout_data():
    d = LayoutData.empty()
    assert len(d) == 0
    assert d.total_extent == 0
    assert d.group_starts == []
    assert d.group_ends == []
    assert d.group_mids == []
    assert not d


def test_layout_data_group_ends():
    aspects = [1.5, 1.0, 0.8, 1.2, 1.5, 1.0]
    groups = [
        (0, 3, 0, 1.0),
        (3, 3, 110, 1.0),
    ]
    d = LayoutData(aspects, 100, 5, 500, True, False, groups)
    assert len(d.group_starts) == 2
    assert len(d.group_ends) == 2
    assert len(d.group_mids) == 2
    for s, e in zip(d.group_starts, d.group_ends):
        assert e > s


def test_len_and_bool():
    d = _make_layout([1.0, 1.5, 0.8])
    assert len(d) == 3
    assert d


def test_total_extent():
    d = _make_layout([1.0], base_height=100, spacing=5)
    assert d.total_extent > 0


def test_getitem_returns_qrect():
    d = _make_layout([1.5, 1.0, 0.8])
    rect = d[0]
    assert isinstance(rect, QtCore.QRect)
    assert rect.width() > 0
    assert rect.height() == 100


def test_getitem_caches():
    d = _make_layout([1.5, 1.0])
    r1 = d[0]
    r2 = d[0]
    assert r1 == r2


def test_items_no_overlap_horizontal():
    aspects = [1.5, 1.0, 0.8, 1.2]
    d = _make_layout(aspects)
    for i in range(len(aspects) - 1):
        assert d[i].right() < d[i + 1].left()


def test_multiple_groups():
    aspects = [1.5, 1.0, 0.8, 1.2, 1.5, 1.0]
    groups = [
        (0, 3, 0, 1.0),
        (3, 3, 110, 1.0),
    ]
    d = LayoutData(aspects, 100, 5, 500, True, False, groups)
    assert len(d) == 6
    r0 = d[0]
    r3 = d[3]
    assert r0.top() == 0
    assert r3.top() == 110


def test_calculate_visible_indices_all():
    aspects = [1.0, 1.0, 1.0]
    d = _make_layout(aspects)
    visible = d.calculate_visible_indices(0, 9999)
    assert set(visible) == {0, 1, 2}


def test_calculate_visible_indices_empty_layout():
    d = LayoutData.empty()
    visible = d.calculate_visible_indices(0, 1000)
    assert len(visible) == 0


def test_calculate_visible_indices_partial():
    aspects = [1.0] * 6
    groups = [
        (0, 3, 0, 1.0),
        (3, 3, 200, 1.0),
    ]
    d = LayoutData(aspects, 100, 5, 500, True, False, groups)
    visible = d.calculate_visible_indices(0, 150)
    assert 0 in visible
    assert 3 not in visible


def test_index_at_point():
    aspects = [1.0, 1.0, 1.0]
    d = _make_layout(aspects, base_height=100, spacing=5, container_width=500)
    r0 = d[0]
    center = QtCore.QPoint(r0.center().x(), r0.center().y())
    assert d.index_at_point(center) == 0


def test_index_at_point_empty_space():
    d = _make_layout([1.0], base_height=100, spacing=5, container_width=500)
    result = d.index_at_point(QtCore.QPoint(9999, 9999))
    assert result is None


def test_intersecting_indices():
    aspects = [1.0, 1.0, 1.0]
    d = _make_layout(aspects, base_height=100, spacing=5, container_width=500)
    r0 = d[0]
    r1 = d[1]
    rect = QtCore.QRect(r0.left(), r0.top(), r1.right() - r0.left() + 1, 100)
    result = d.intersecting_indices(rect)
    assert 0 in result
    assert 1 in result


def test_reversed_secondary():
    aspects = [1.5, 1.0]
    d = _make_layout(aspects, container_width=500, reverse=True)
    r0 = d[0]
    r1 = d[1]
    assert r0.left() > r1.left()


def test_vertical_layout():
    aspects = [1.0, 2.0]
    groups = [(0, 2, 0, 1.0)]
    d = LayoutData(aspects, 100, 5, 500, hz=False, reversed_secondary=False, groups=groups)
    r0 = d[0]
    r1 = d[1]
    assert r0.left() == 0
    assert r0.width() == 100


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

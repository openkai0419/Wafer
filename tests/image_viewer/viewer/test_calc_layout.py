import py_compile
from source.image_viewer.viewer.calc_layout import LayoutData


def test_compile():
    py_compile.compile('source/image_viewer/viewer/calc_layout.py')


def test_empty_layout_data():
    d = LayoutData.empty()
    assert len(d) == 0
    assert d.total_extent == 0
    assert d.group_starts == []
    assert d.group_ends == []
    assert d.group_mids == []


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

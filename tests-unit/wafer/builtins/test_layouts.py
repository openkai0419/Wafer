from wafer.builtins.layouts import (
    JustifiedLayout,
    MasonryLayout,
    JustifiedLayoutCalculator,
    MasonryLayoutCalculator,
)
from wafer.plugin.layout.base import BaseLayoutPlugin
from wafer.plugin.layout.calc import LayoutData


def test_justified_layout_is_plugin():
    assert issubclass(JustifiedLayout, BaseLayoutPlugin)
    assert JustifiedLayout.NAME == "justified"
    assert JustifiedLayout.DISPLAY_NAME == "Justified"


def test_masonry_layout_is_plugin():
    assert issubclass(MasonryLayout, BaseLayoutPlugin)
    assert MasonryLayout.NAME == "masonry"
    assert MasonryLayout.DISPLAY_NAME == "Masonry"


def test_justified_create_calculator():
    calc = JustifiedLayout.create_calculator([1.0, 1.5], 100, 5, 500, None, 0)
    assert isinstance(calc, JustifiedLayoutCalculator)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 2


def test_masonry_create_calculator():
    calc = MasonryLayout.create_calculator([1.0, 1.5], 100, 5, 500, None, 0)
    assert isinstance(calc, MasonryLayoutCalculator)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 2


def test_justified_priority_higher_than_masonry():
    assert JustifiedLayout.PRIORITY > MasonryLayout.PRIORITY


def test_justified_produces_layout():
    calc = JustifiedLayoutCalculator([1.0, 1.5, 0.8], 100, 5, 500, None, orientation=0)
    calc.run()
    assert calc._result is not None
    assert isinstance(calc._result, LayoutData)
    assert len(calc._result) == 3


def test_justified_cancel():
    calc = JustifiedLayoutCalculator([1.0] * 100, 100, 5, 500, None, orientation=0)
    calc.cancel()
    calc.run()
    assert calc._result is None


def test_justified_none_aspect_ratios():
    calc = JustifiedLayoutCalculator([1.0, None, 0.8], 100, 5, 500, None, orientation=0)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 3


def test_justified_zero_aspect_ratios():
    calc = JustifiedLayoutCalculator([1.0, 0.0, 0.8], 100, 5, 500, None, orientation=0)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 3


def test_justified_rects_no_overlap():
    calc = JustifiedLayoutCalculator([1.5, 1.0, 0.8, 1.2, 2.0], 100, 5, 500, None, orientation=0)
    calc.run()
    layout = calc._result
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            assert not layout[i].intersects(layout[j])


def test_justified_reversed_horizontal():
    calc = JustifiedLayoutCalculator([1.5, 1.0], 100, 5, 500, None, orientation=1)
    calc.run()
    layout = calc._result
    assert layout[0].left() > layout[1].left()


def test_justified_reversed_vertical_total_extent_matches_forward():
    aspects = [1.5, 1.0, 0.8, 1.2, 2.0, 0.9, 1.1, 1.4]

    forward = JustifiedLayoutCalculator(aspects, 100, 5, 500, 300, orientation=2)
    forward.run()

    reversed_calc = JustifiedLayoutCalculator(aspects, 100, 5, 500, 300, orientation=3)
    reversed_calc.run()

    forward_layout = forward._result
    reversed_layout = reversed_calc._result

    assert reversed_layout.total_extent == forward_layout.total_extent
    assert max(r.x() + r.width() for r in reversed_layout) + 5 == reversed_layout.total_extent


def test_justified_row_height_uniformity():
    aspects = [2.0, 0.5, 1.5, 0.7, 1.0, 1.3, 0.8, 2.5, 0.6, 1.8, 1.1, 0.9, 1.4, 0.7, 2.2]
    calc = JustifiedLayoutCalculator(aspects, 100, 5, 500, None, orientation=0)
    calc.run()
    layout = calc._result
    assert layout is not None
    row_heights = set()
    for i in range(len(layout)):
        row_heights.add(layout[i].height())
    if len(row_heights) > 1:
        heights = [layout[i].height() for i in range(len(layout))]
        mean_h = sum(heights) / len(heights)
        variance = sum((h - mean_h) ** 2 for h in heights) / len(heights)
        assert variance < 2000


def test_justified_empty_aspects():
    calc = JustifiedLayoutCalculator([], 100, 5, 500, None, orientation=0)
    calc.run()
    assert calc._result is None


def test_justified_single_item():
    calc = JustifiedLayoutCalculator([1.5], 100, 5, 500, None, orientation=0)
    calc.run()
    layout = calc._result
    assert layout is not None
    assert len(layout) == 1


def test_justified_uniform_aspects_equal_row_heights():
    aspects = [1.5] * 12
    calc = JustifiedLayoutCalculator(aspects, 100, 5, 500, None, orientation=0)
    calc.run()
    layout = calc._result
    assert layout is not None
    row_y_to_height = {}
    for i in range(len(layout)):
        y = layout[i].y()
        row_y_to_height[y] = layout[i].height()
    non_last_heights = sorted(row_y_to_height.items(), key=lambda x: x[0])
    for _, h in non_last_heights[:-1]:
        assert h == non_last_heights[0][1]


def test_masonry_produces_layout():
    calc = MasonryLayoutCalculator([1.0, 1.5, 0.8, 1.2], 150, 5, 500, None, orientation=0)
    calc.run()
    assert calc._result is not None
    assert isinstance(calc._result, LayoutData)
    assert len(calc._result) == 4


def test_masonry_columns_equal_width():
    calc = MasonryLayoutCalculator([1.0, 1.5, 0.8, 1.2, 1.0, 0.5], 100, 5, 500, None, orientation=0)
    calc.run()
    layout = calc._result
    widths = {layout[i].width() for i in range(len(layout))}
    assert len(widths) == 1


def test_masonry_no_overlap():
    calc = MasonryLayoutCalculator([1.0, 1.5, 0.8, 1.2, 2.0, 0.5], 100, 5, 500, None, orientation=0)
    calc.run()
    layout = calc._result
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            assert not layout[i].intersects(layout[j])


def test_masonry_cancel():
    calc = MasonryLayoutCalculator([1.0] * 100, 100, 5, 500, None, orientation=0)
    calc.cancel()
    calc.run()
    assert calc._result is None


def test_masonry_reversed():
    calc = MasonryLayoutCalculator([1.0, 1.5, 0.8], 100, 5, 500, None, orientation=0)
    calc.run()

    calc2 = MasonryLayoutCalculator([1.0, 1.5, 0.8], 100, 5, 500, None, orientation=1)
    calc2.run()

    normal_item0_x = calc._result[0].x()
    rev_item0_x = calc2._result[0].x()
    assert normal_item0_x != rev_item0_x


def test_masonry_none_aspect_ratios():
    calc = MasonryLayoutCalculator([1.0, None, 0.8], 100, 5, 500, None, orientation=0)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 3


def test_justified_inscribed_rendering():
    calc = JustifiedLayoutCalculator([4.0], 100, 5, 500, None, orientation=0)
    calc.run()
    assert calc._result is not None
    r = calc._result[0]
    assert r.width() > 0 and r.height() > 0


def test_masonry_inscribed_rendering():
    calc = MasonryLayoutCalculator([0.5], 100, 5, 500, None, orientation=0)
    calc.run()
    assert calc._result is not None
    r = calc._result[0]
    assert r.width() > 0 and r.height() > 0


def test_masonry_single_item():
    calc = MasonryLayoutCalculator([1.0], 100, 5, 500, None, orientation=0)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 1

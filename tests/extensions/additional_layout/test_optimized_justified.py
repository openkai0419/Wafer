from extensions.additional_layout.optimized_justified import (
    OptimizedJustifiedLayout, OptimizedJustifiedLayoutCalculator,
)
from wafer.plugin.layout.base import BaseLayoutPlugin
from wafer.plugin.layout.calc import LayoutData


def test_optimized_justified_layout_is_plugin():
    assert issubclass(OptimizedJustifiedLayout, BaseLayoutPlugin)
    assert OptimizedJustifiedLayout.NAME == 'optimizedJustified'
    assert OptimizedJustifiedLayout.DISPLAY_NAME == 'Optimized Justified'


def test_optimized_justified_create_calculator():
    calc = OptimizedJustifiedLayout.create_calculator([1.0, 1.5], 100, 5, 500, None, 0)
    assert isinstance(calc, OptimizedJustifiedLayoutCalculator)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 2


def test_optimized_justified_priority():
    assert OptimizedJustifiedLayout.PRIORITY == 95


def test_optimized_justified_produces_layout():
    calc = OptimizedJustifiedLayoutCalculator([1.0, 1.5, 0.8], 100, 5, 500, None, orientation=0)
    calc.run()
    assert calc._result is not None
    assert isinstance(calc._result, LayoutData)
    assert len(calc._result) == 3


def test_optimized_justified_cancel():
    calc = OptimizedJustifiedLayoutCalculator([1.0] * 100, 100, 5, 500, None, orientation=0)
    calc.cancel()
    calc.run()
    assert calc._result is None


def test_optimized_justified_none_aspect_ratios():
    calc = OptimizedJustifiedLayoutCalculator([1.0, None, 0.8], 100, 5, 500, None, orientation=0)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 3


def test_optimized_justified_rects_no_overlap():
    calc = OptimizedJustifiedLayoutCalculator([1.5, 1.0, 0.8, 1.2, 2.0], 100, 5, 500, None, orientation=0)
    calc.run()
    layout = calc._result
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            assert not layout[i].intersects(layout[j])


def test_optimized_justified_reversed_horizontal():
    calc = OptimizedJustifiedLayoutCalculator([1.5, 1.0], 100, 5, 500, None, orientation=1)
    calc.run()
    layout = calc._result
    assert layout[0].left() > layout[1].left()


def test_optimized_justified_reversed_vertical_total_extent_matches_forward():
    aspects = [1.5, 1.0, 0.8, 1.2, 2.0, 0.9, 1.1, 1.4]
    forward = OptimizedJustifiedLayoutCalculator(aspects, 100, 5, 500, 300, orientation=2)
    forward.run()
    reversed_calc = OptimizedJustifiedLayoutCalculator(aspects, 100, 5, 500, 300, orientation=3)
    reversed_calc.run()
    assert reversed_calc._result.total_extent == forward._result.total_extent


def test_optimized_justified_empty_aspects():
    calc = OptimizedJustifiedLayoutCalculator([], 100, 5, 500, None, orientation=0)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 0


def test_optimized_justified_single_item():
    calc = OptimizedJustifiedLayoutCalculator([1.5], 100, 5, 500, None, orientation=0)
    calc.run()
    layout = calc._result
    assert layout is not None
    assert len(layout) == 1
    assert layout[0].height() == 100


def test_optimized_justified_last_row_not_over_stretched():
    aspects = [1.5, 1.0, 0.8, 1.2, 2.0, 0.9, 1.1, 1.4, 0.7, 1.3]
    calc = OptimizedJustifiedLayoutCalculator(aspects, 100, 5, 800, None, orientation=0)
    calc.run()
    layout = calc._result
    assert layout is not None
    last_idx = len(layout) - 1
    last_height = layout[last_idx].height()
    assert last_height <= 100


def test_optimized_justified_row_height_uniformity():
    aspects = [2.0, 0.5, 1.5, 0.7, 1.0, 1.3, 0.8, 2.5, 0.6, 1.8, 1.1, 0.9, 1.4, 0.7, 2.2]
    calc = OptimizedJustifiedLayoutCalculator(aspects, 100, 5, 500, None, orientation=0)
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


def test_optimized_justified_uniform_aspects_equal_row_heights():
    aspects = [1.5] * 12
    calc = OptimizedJustifiedLayoutCalculator(aspects, 100, 5, 500, None, orientation=0)
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

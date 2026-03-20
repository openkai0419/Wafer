from extensions.additional_layout.mosaic import (
    MosaicLayout, MosaicLayoutCalculator,
)
from wafer.plugin.layout.base import BaseLayoutPlugin
from wafer.plugin.layout.calc import LayoutData


def test_mosaic_is_plugin():
    assert issubclass(MosaicLayout, BaseLayoutPlugin)
    assert MosaicLayout.NAME == 'mosaic'
    assert MosaicLayout.DISPLAY_NAME == 'Mosaic'


def test_mosaic_priority():
    assert MosaicLayout.PRIORITY == 85


def test_mosaic_create_calculator():
    calc = MosaicLayout.create_calculator([1.0, 1.5], 100, 5, 500, 500, 0)
    assert isinstance(calc, MosaicLayoutCalculator)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 2


def test_mosaic_produces_layout():
    calc = MosaicLayoutCalculator([1.0, 1.5, 0.8], 100, 5, 500, 500, 0)
    calc.run()
    result = calc._result
    assert result is not None
    assert isinstance(result, LayoutData)
    assert len(result) == 3


def test_mosaic_empty():
    calc = MosaicLayoutCalculator([], 100, 5, 500, 500, 0)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 0


def test_mosaic_cancel():
    calc = MosaicLayoutCalculator([1.0] * 100, 100, 5, 500, 500, 0)
    calc.cancel()
    calc.run()
    assert calc._result is None


def test_mosaic_none_aspect():
    calc = MosaicLayoutCalculator([1.0, None, 0.8], 100, 5, 500, 500, 0)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 3


def test_mosaic_single_item():
    calc = MosaicLayoutCalculator([1.0], 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    assert layout is not None
    assert len(layout) == 1
    assert layout[0].width() > 0
    assert layout[0].height() > 0


def test_mosaic_no_overlap():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8, 1.2, 0.6,
               1.0, 1.5, 0.7, 2.5, 1.0, 0.4, 1.3, 1.0, 0.9, 1.1]
    calc = MosaicLayoutCalculator(aspects, 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    assert layout is not None
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            assert not layout[i].intersects(layout[j]), f"Items {i} and {j} overlap"


def test_mosaic_no_overlap_many_items():
    aspects = [0.5 + (i % 7) * 0.4 for i in range(100)]
    calc = MosaicLayoutCalculator(aspects, 100, 5, 800, 800, 0)
    calc.run()
    layout = calc._result
    assert layout is not None
    assert len(layout) == 100
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            assert not layout[i].intersects(layout[j]), f"Items {i} and {j} overlap"


def test_mosaic_feature_item_larger():
    aspects = [1.0] * 14
    calc = MosaicLayoutCalculator(aspects, 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    feature_area_0 = layout[0].width() * layout[0].height()
    feature_area_7 = layout[7].width() * layout[7].height()
    regular_area = layout[1].width() * layout[1].height()
    assert feature_area_0 > regular_area
    assert feature_area_7 > regular_area


def test_mosaic_wide_aspect_spans_two_lanes():
    aspects = [1.0, 2.0, 1.0]
    calc = MosaicLayoutCalculator(aspects, 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    assert layout[1].width() > layout[2].width()


def test_mosaic_tall_aspect_spans_two_rows():
    aspects = [1.0, 0.5, 1.0]
    calc = MosaicLayoutCalculator(aspects, 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    assert layout[1].height() > layout[2].height()


def test_mosaic_all_orientations():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0]
    for orientation in range(4):
        calc = MosaicLayoutCalculator(aspects, 100, 5, 500, 500, orientation)
        calc.run()
        assert calc._result is not None
        assert len(calc._result) == len(aspects)


def test_mosaic_no_overlap_all_orientations():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8, 1.2, 0.6,
               1.0, 1.5, 0.7, 2.5, 1.0, 0.4, 1.3, 1.0, 0.9, 1.1]
    for orientation in range(4):
        calc = MosaicLayoutCalculator(aspects, 100, 5, 500, 500, orientation)
        calc.run()
        layout = calc._result
        for i in range(len(layout)):
            for j in range(i + 1, len(layout)):
                assert not layout[i].intersects(layout[j]), (
                    f"orientation={orientation}: items {i} and {j} overlap"
                )


def test_mosaic_reversed_horizontal():
    aspects = [1.0] * 8
    normal = MosaicLayoutCalculator(aspects, 100, 5, 500, 500, 0)
    normal.run()
    rev = MosaicLayoutCalculator(aspects, 100, 5, 500, 500, 1)
    rev.run()
    assert normal._result.total_extent == rev._result.total_extent
    normal_xs = [normal._result[i].x() for i in range(len(aspects))]
    rev_xs = [rev._result[i].x() for i in range(len(aspects))]
    assert normal_xs != rev_xs


def test_mosaic_reversed_vertical():
    aspects = [1.0, 1.0, 0.5, 1.8, 1.0, 2.0, 1.0]
    forward = MosaicLayoutCalculator(aspects, 100, 5, 500, 500, 2)
    forward.run()
    rev = MosaicLayoutCalculator(aspects, 100, 5, 500, 500, 3)
    rev.run()
    assert forward._result.total_extent == rev._result.total_extent


def test_mosaic_single_lane():
    aspects = [1.0, 0.5, 2.0, 1.0, 0.3, 1.5, 0.8, 1.0]
    calc = MosaicLayoutCalculator(aspects, 500, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    assert layout is not None
    assert len(layout) == len(aspects)
    widths = {layout[i].width() for i in range(len(layout))}
    assert len(widths) == 1


def test_mosaic_single_lane_feature_still_tall():
    aspects = [1.0, 1.0, 1.0]
    calc = MosaicLayoutCalculator(aspects, 500, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    assert layout[0].height() > layout[1].height()


def test_mosaic_size_variety():
    aspects = [1.0] * 14
    calc = MosaicLayoutCalculator(aspects, 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    areas = {layout[i].width() * layout[i].height() for i in range(len(layout))}
    assert len(areas) >= 2


def test_mosaic_positive_dimensions():
    aspects = [0.1, 5.0, 0.01, 10.0, 1.0, 0.5, 2.0]
    calc = MosaicLayoutCalculator(aspects, 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    for i in range(len(layout)):
        assert layout[i].width() > 0
        assert layout[i].height() > 0

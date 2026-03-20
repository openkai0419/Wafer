from extensions.additional_layout.partition_geometric import (
    GeometricPartitionLayout, GeometricPartitionCalculator,
)
from extensions.additional_layout.partition_organic import (
    OrganicPartitionCalculator,
)
from wafer.plugin.layout.base import BaseLayoutPlugin
from wafer.plugin.layout.calc import LayoutData


def test_is_plugin():
    assert issubclass(GeometricPartitionLayout, BaseLayoutPlugin)
    assert GeometricPartitionLayout.NAME == 'partitionGeometric'
    assert GeometricPartitionLayout.DISPLAY_NAME == 'Partition (Geometric)'


def test_priority():
    assert GeometricPartitionLayout.PRIORITY == 84


def test_create_calculator():
    calc = GeometricPartitionLayout.create_calculator([1.0, 1.5], 100, 5, 500, 500, 0)
    assert isinstance(calc, GeometricPartitionCalculator)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 2


def test_produces_layout():
    calc = GeometricPartitionCalculator([1.0, 1.5, 0.8], 100, 5, 500, 500, 0)
    calc.run()
    result = calc._result
    assert result is not None
    assert isinstance(result, LayoutData)
    assert len(result) == 3


def test_empty():
    calc = GeometricPartitionCalculator([], 100, 5, 500, 500, 0)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 0


def test_none_aspect():
    calc = GeometricPartitionCalculator([1.0, None, 0.8], 100, 5, 500, 500, 0)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 3


def test_single_item():
    calc = GeometricPartitionCalculator([1.0], 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    assert layout is not None
    assert len(layout) == 1
    assert layout[0].width() > 0
    assert layout[0].height() > 0


def test_no_overlap():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8, 1.2, 0.6,
               1.0, 1.5, 0.7, 2.5, 1.0, 0.4, 1.3, 1.0, 0.9, 1.1]
    calc = GeometricPartitionCalculator(aspects, 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    assert layout is not None
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            assert not layout[i].intersects(layout[j]), f"Items {i} and {j} overlap"


def test_no_overlap_many_items():
    aspects = [0.5 + (i % 7) * 0.4 for i in range(100)]
    calc = GeometricPartitionCalculator(aspects, 100, 5, 800, 800, 0)
    calc.run()
    layout = calc._result
    assert layout is not None
    assert len(layout) == 100
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            assert not layout[i].intersects(layout[j]), f"Items {i} and {j} overlap"


def test_all_orientations():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0]
    for orientation in range(4):
        calc = GeometricPartitionCalculator(aspects, 100, 5, 500, 500, orientation)
        calc.run()
        assert calc._result is not None
        assert len(calc._result) == len(aspects)


def test_no_overlap_all_orientations():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8, 1.2, 0.6,
               1.0, 1.5, 0.7, 2.5, 1.0, 0.4, 1.3, 1.0, 0.9, 1.1]
    for orientation in range(4):
        calc = GeometricPartitionCalculator(aspects, 100, 5, 500, 500, orientation)
        calc.run()
        layout = calc._result
        for i in range(len(layout)):
            for j in range(i + 1, len(layout)):
                assert not layout[i].intersects(layout[j]), (
                    f"orientation={orientation}: items {i} and {j} overlap"
                )


def test_reversed_horizontal():
    aspects = [1.0] * 8
    normal = GeometricPartitionCalculator(aspects, 100, 5, 500, 500, 0)
    normal.run()
    rev = GeometricPartitionCalculator(aspects, 100, 5, 500, 500, 1)
    rev.run()
    assert normal._result.total_extent == rev._result.total_extent
    normal_xs = [normal._result[i].x() for i in range(len(aspects))]
    rev_xs = [rev._result[i].x() for i in range(len(aspects))]
    assert normal_xs != rev_xs


def test_reversed_vertical():
    aspects = [1.0, 1.0, 0.5, 1.8, 1.0, 2.0, 1.0]
    forward = GeometricPartitionCalculator(aspects, 100, 5, 500, 500, 2)
    forward.run()
    rev = GeometricPartitionCalculator(aspects, 100, 5, 500, 500, 3)
    rev.run()
    assert forward._result.total_extent == rev._result.total_extent


def test_n_series_rect_axes():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8, 1.2, 0.6]
    cw, ch = 200, 800
    calc = GeometricPartitionCalculator(aspects, 100, 5, cw, ch, 2)
    calc.run()
    layout = calc._result
    for i in range(len(layout)):
        r = layout[i]
        assert r.y() >= 0 and r.y() + r.height() <= ch, (
            f"item {i}: y={r.y()} h={r.height()} exceeds container_height={ch}"
        )


def test_n_series_reverse_flips_x():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8, 1.2, 0.6,
               1.0, 1.5, 0.7, 2.5, 1.0, 0.4, 1.3, 1.0, 0.9, 1.1]
    cw, ch = 200, 400
    fwd = GeometricPartitionCalculator(aspects, 100, 5, cw, ch, 2)
    fwd.run()
    rev = GeometricPartitionCalculator(aspects, 100, 5, cw, ch, 3)
    rev.run()
    fwd_xs = [fwd._result[i].x() for i in range(len(aspects))]
    rev_xs = [rev._result[i].x() for i in range(len(aspects))]
    assert fwd_xs != rev_xs
    assert fwd._result.total_extent == rev._result.total_extent


def test_n_series_no_overlap_asymmetric():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8, 1.2, 0.6,
               1.0, 1.5, 0.7, 2.5, 1.0, 0.4, 1.3, 1.0, 0.9, 1.1]
    for ori in (2, 3):
        calc = GeometricPartitionCalculator(aspects, 100, 5, 300, 900, ori)
        calc.run()
        layout = calc._result
        for i in range(len(layout)):
            for j in range(i + 1, len(layout)):
                assert not layout[i].intersects(layout[j]), (
                    f"orientation={ori}: items {i} and {j} overlap"
                )


def test_positive_dimensions():
    aspects = [0.1, 5.0, 0.01, 10.0, 1.0, 0.5, 2.0]
    calc = GeometricPartitionCalculator(aspects, 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    for i in range(len(layout)):
        assert layout[i].width() > 0
        assert layout[i].height() > 0


def test_covers_area():
    calc = GeometricPartitionCalculator([1.0] * 20, 100, 0, 500, 500, 0)
    calc.run()
    layout = calc._result
    total_area = sum(layout[i].width() * layout[i].height() for i in range(len(layout)))
    expected_area = 500 * layout.total_extent
    assert total_area == expected_area


def test_deterministic():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8]
    calc1 = GeometricPartitionCalculator(aspects, 100, 5, 500, 500, 0)
    calc1.run()
    calc2 = GeometricPartitionCalculator(aspects, 100, 5, 500, 500, 0)
    calc2.run()
    for i in range(len(aspects)):
        assert calc1._result[i] == calc2._result[i]


def test_wide_image_gets_wider_cell():
    aspects = [3.0, 0.3]
    calc = GeometricPartitionCalculator(aspects, 200, 5, 600, 600, 0)
    calc.run()
    layout = calc._result
    wide_ar = layout[0].width() / max(1, layout[0].height())
    tall_ar = layout[1].width() / max(1, layout[1].height())
    assert wide_ar > tall_ar


def test_ar_matching_score():
    aspects = [0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 2.5, 3.0,
               0.4, 0.6, 0.8, 1.2, 1.8, 2.2, 0.35, 1.0]
    calc = GeometricPartitionCalculator(aspects, 100, 5, 600, 600, 0)
    calc.run()
    layout = calc._result
    scores = []
    for i in range(len(aspects)):
        cell_ar = layout[i].width() / max(1, layout[i].height())
        img_ar = aspects[i] if aspects[i] and aspects[i] > 0 else 1.0
        scores.append(min(img_ar, cell_ar) / max(img_ar, cell_ar))
    mean_score = sum(scores) / len(scores)
    assert mean_score > 0.5


def test_ar_matching_consistent_across_counts():
    for n in [10, 30, 60, 100]:
        aspects = [0.3 + (i % 10) * 0.3 for i in range(n)]
        calc = GeometricPartitionCalculator(aspects, 100, 5, 800, 800, 0)
        calc.run()
        layout = calc._result
        scores = []
        for i in range(len(layout)):
            cell_ar = layout[i].width() / max(1, layout[i].height())
            img_ar = aspects[i] if aspects[i] > 0 else 1.0
            scores.append(min(img_ar, cell_ar) / max(img_ar, cell_ar))
        assert sum(scores) / len(scores) > 0.45, f"n={n} mean score too low"


def test_differs_from_organic():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8, 1.2, 0.6,
               1.0, 1.5, 0.7, 2.5, 1.0, 0.4, 1.3, 1.0, 0.9, 1.1]
    geo = GeometricPartitionCalculator(aspects, 100, 5, 500, 500, 0)
    geo.run()
    org = OrganicPartitionCalculator(aspects, 100, 5, 500, 500, 0)
    org.run()
    differ = False
    for i in range(len(aspects)):
        if geo._result[i] != org._result[i]:
            differ = True
            break
    assert differ, "Geometric should produce different results from Organic"

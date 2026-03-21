from extensions.additional_layout.multispan import (
    MultiSpanLayout, MultiSpanCalculator,
)
from wafer.plugin.layout.base import BaseLayoutPlugin
from wafer.plugin.layout.calc import LayoutData


def test_is_plugin():
    assert issubclass(MultiSpanLayout, BaseLayoutPlugin)
    assert MultiSpanLayout.NAME == 'multiSpan'
    assert MultiSpanLayout.DISPLAY_NAME == 'MultiSpan Grid'


def test_priority():
    assert MultiSpanLayout.PRIORITY == 86


def test_create_calculator():
    calc = MultiSpanLayout.create_calculator([1.0, 1.5], 100, 5, 500, 500, 0)
    assert isinstance(calc, MultiSpanCalculator)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 2


def test_produces_layout():
    calc = MultiSpanCalculator([1.0, 1.5, 0.8], 100, 5, 500, 500, 0)
    calc.run()
    result = calc._result
    assert result is not None
    assert isinstance(result, LayoutData)
    assert len(result) == 3


def test_empty():
    calc = MultiSpanCalculator([], 100, 5, 500, 500, 0)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 0


def test_none_aspect():
    calc = MultiSpanCalculator([1.0, None, 0.8], 100, 5, 500, 500, 0)
    calc.run()
    assert calc._result is not None
    assert len(calc._result) == 3


def test_single_item():
    calc = MultiSpanCalculator([1.0], 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    assert layout is not None
    assert len(layout) == 1
    assert layout[0].width() > 0
    assert layout[0].height() > 0


def test_no_overlap():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8, 1.2, 0.6,
               1.0, 1.5, 0.7, 2.5, 1.0, 0.4, 1.3, 1.0, 0.9, 1.1]
    calc = MultiSpanCalculator(aspects, 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    assert layout is not None
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            assert not layout[i].intersects(layout[j]), f"Items {i} and {j} overlap"


def test_no_overlap_many_items():
    aspects = [0.5 + (i % 7) * 0.4 for i in range(100)]
    calc = MultiSpanCalculator(aspects, 100, 5, 800, 800, 0)
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
        calc = MultiSpanCalculator(aspects, 100, 5, 500, 500, orientation)
        calc.run()
        assert calc._result is not None
        assert len(calc._result) == len(aspects)


def test_no_overlap_all_orientations():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8, 1.2, 0.6,
               1.0, 1.5, 0.7, 2.5, 1.0, 0.4, 1.3, 1.0, 0.9, 1.1]
    for orientation in range(4):
        calc = MultiSpanCalculator(aspects, 100, 5, 500, 500, orientation)
        calc.run()
        layout = calc._result
        for i in range(len(layout)):
            for j in range(i + 1, len(layout)):
                assert not layout[i].intersects(layout[j]), (
                    f"orientation={orientation}: items {i} and {j} overlap"
                )


def test_reversed_horizontal():
    aspects = [1.0] * 8
    normal = MultiSpanCalculator(aspects, 100, 5, 500, 500, 0)
    normal.run()
    rev = MultiSpanCalculator(aspects, 100, 5, 500, 500, 1)
    rev.run()
    assert normal._result.total_extent == rev._result.total_extent
    normal_xs = [normal._result[i].x() for i in range(len(aspects))]
    rev_xs = [rev._result[i].x() for i in range(len(aspects))]
    assert normal_xs != rev_xs


def test_reversed_vertical():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0,
               0.8, 1.2, 0.6, 1.0, 1.5, 0.7, 2.5]
    forward = MultiSpanCalculator(aspects, 100, 5, 500, 500, 2)
    forward.run()
    rev = MultiSpanCalculator(aspects, 100, 5, 500, 500, 3)
    rev.run()
    assert forward._result.total_extent == rev._result.total_extent


def test_n_series_rect_axes():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8, 1.2, 0.6]
    cw, ch = 200, 800
    calc = MultiSpanCalculator(aspects, 100, 5, cw, ch, 2)
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
    fwd = MultiSpanCalculator(aspects, 100, 5, cw, ch, 2)
    fwd.run()
    rev = MultiSpanCalculator(aspects, 100, 5, cw, ch, 3)
    rev.run()
    fwd_xs = [fwd._result[i].x() for i in range(len(aspects))]
    rev_xs = [rev._result[i].x() for i in range(len(aspects))]
    assert fwd_xs != rev_xs
    assert fwd._result.total_extent == rev._result.total_extent


def test_n_series_no_overlap_asymmetric():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8, 1.2, 0.6,
               1.0, 1.5, 0.7, 2.5, 1.0, 0.4, 1.3, 1.0, 0.9, 1.1]
    for ori in (2, 3):
        calc = MultiSpanCalculator(aspects, 100, 5, 300, 900, ori)
        calc.run()
        layout = calc._result
        for i in range(len(layout)):
            for j in range(i + 1, len(layout)):
                assert not layout[i].intersects(layout[j]), (
                    f"orientation={ori}: items {i} and {j} overlap"
                )


def test_positive_dimensions():
    aspects = [0.1, 5.0, 0.01, 10.0, 1.0, 0.5, 2.0]
    calc = MultiSpanCalculator(aspects, 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    for i in range(len(layout)):
        assert layout[i].width() > 0
        assert layout[i].height() > 0


def test_grid_alignment():
    aspects = [1.0] * 20
    calc = MultiSpanCalculator(aspects, 100, 0, 500, 500, 0)
    calc.run()
    layout = calc._result
    xs = sorted(set(layout[i].x() for i in range(len(layout))))
    ys = sorted(set(layout[i].y() for i in range(len(layout))))
    assert len(xs) <= 6
    assert len(ys) <= 20


def test_wide_image_gets_wide_cell():
    aspects = [2.5, 0.4, 1.0, 2.5, 0.4, 1.0, 2.5, 0.4, 1.0]
    calc = MultiSpanCalculator(aspects, 100, 5, 600, 600, 0)
    calc.run()
    layout = calc._result
    assert layout[0].width() > layout[0].height()


def test_tall_image_gets_tall_cell():
    aspects = [0.4, 2.5, 1.0, 0.4, 2.5, 1.0, 0.4, 2.5, 1.0]
    calc = MultiSpanCalculator(aspects, 100, 5, 600, 600, 0)
    calc.run()
    layout = calc._result
    assert layout[0].height() > layout[0].width()


def test_deterministic():
    aspects = [1.5, 1.0, 0.5, 1.8, 0.3, 2.0, 1.0, 0.8]
    calc1 = MultiSpanCalculator(aspects, 100, 5, 500, 500, 0)
    calc1.run()
    calc2 = MultiSpanCalculator(aspects, 100, 5, 500, 500, 0)
    calc2.run()
    for i in range(len(aspects)):
        assert calc1._result[i] == calc2._result[i]


def test_ar_matching_score():
    aspects = [0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 2.5, 3.0,
               0.4, 0.6, 0.8, 1.2, 1.8, 2.2, 0.35, 1.0]
    calc = MultiSpanCalculator(aspects, 100, 5, 600, 600, 0)
    calc.run()
    layout = calc._result
    scores = []
    for i in range(len(aspects)):
        cell_ar = layout[i].width() / max(1, layout[i].height())
        img_ar = aspects[i] if aspects[i] and aspects[i] > 0 else 1.0
        scores.append(min(img_ar, cell_ar) / max(img_ar, cell_ar))
    mean_score = sum(scores) / len(scores)
    assert mean_score > 0.4


def test_block_fills_completely():
    aspects = [1.0] * 50
    calc = MultiSpanCalculator(aspects, 100, 5, 500, 500, 0)
    calc.run()
    layout = calc._result
    areas = set()
    for i in range(len(layout)):
        r = layout[i]
        for px in range(r.x(), r.x() + r.width()):
            for py in range(r.y(), r.y() + r.height()):
                assert (px, py) not in areas, f"Pixel overlap at ({px},{py})"
                areas.add((px, py))


def test_n_series_wide_image_gets_wide_cell():
    aspects = [2.5, 0.4, 1.0, 2.5, 0.4, 1.0, 2.5, 0.4, 1.0]
    calc = MultiSpanCalculator(aspects, 100, 5, 600, 600, 2)
    calc.run()
    layout = calc._result
    assert layout[0].width() > layout[0].height()


def test_n_series_tall_image_gets_tall_cell():
    aspects = [0.4, 2.5, 1.0, 0.4, 2.5, 1.0, 0.4, 2.5, 1.0]
    calc = MultiSpanCalculator(aspects, 100, 5, 600, 600, 2)
    calc.run()
    layout = calc._result
    assert layout[0].height() > layout[0].width()


def test_square_image_gets_larger_span():
    aspects = [1.0] * 10
    calc = MultiSpanCalculator(aspects, 100, 5, 600, 600, 0)
    calc.run()
    layout = calc._result
    cell_w = int((600 - 5 * 5) / 6)
    has_larger = any(layout[i].width() > cell_w + 10 for i in range(len(layout)))
    assert has_larger


def test_cancel_prevents_result():
    calc = MultiSpanCalculator([1.0] * 100, 100, 5, 500, 500, 0)
    calc.cancel()
    calc.run()
    assert calc._result is None


def test_cancel_token_stops_calculation():
    from wafer.core.qt.dispatcher import CancelToken
    token = CancelToken()
    calc = MultiSpanCalculator([1.0] * 100, 100, 5, 500, 500, 0)
    calc.bind_cancel_token(token)
    token.cancel()
    calc.run()
    assert calc._result is None


def test_cancel_token_mid_calculation():
    import threading
    from wafer.core.qt.dispatcher import CancelToken
    token = CancelToken()
    calc = MultiSpanCalculator([1.0] * 50000, 100, 5, 500, 500, 0)
    calc.bind_cancel_token(token)
    timer = threading.Timer(0.05, token.cancel)
    timer.start()
    calc.run()
    timer.cancel()
    result = calc._result
    assert result is None or len(result) < 50000


def test_gap_fill_no_overlap():
    aspects = [0.3, 3.0, 0.3, 3.0, 1.0, 0.5, 2.0, 1.0] * 20
    calc = MultiSpanCalculator(aspects, 100, 5, 600, 600, 0)
    calc.run()
    layout = calc._result
    assert len(layout) == len(aspects)
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            assert not layout[i].intersects(layout[j]), f"Items {i} and {j} overlap"


def test_gap_fill_uses_multispan():
    aspects = [0.3, 3.0, 1.0] * 30
    calc = MultiSpanCalculator(aspects, 100, 5, 600, 600, 0)
    calc.run()
    layout = calc._result
    num_cols = max(1, round(605 / 105))
    cell_w = (600 - 5 * (num_cols - 1)) / num_cols
    min_cell = int(cell_w)
    multispan_count = sum(1 for i in range(len(layout))
                          if layout[i].width() > min_cell + 10
                          or layout[i].height() > min_cell + 10)
    assert multispan_count > len(aspects) * 0.3, (
        f"Expected >30% multispan cells, got {multispan_count}/{len(aspects)}"
    )


def test_gap_fill_all_orientations_no_overlap():
    aspects = [0.3, 3.0, 0.5, 2.0, 1.0] * 15
    for orientation in range(4):
        calc = MultiSpanCalculator(aspects, 100, 5, 500, 500, orientation)
        calc.run()
        layout = calc._result
        assert len(layout) == len(aspects)
        for i in range(len(layout)):
            for j in range(i + 1, len(layout)):
                assert not layout[i].intersects(layout[j]), (
                    f"orientation={orientation}: items {i} and {j} overlap"
                )


def test_gap_fill_prefers_multispan_over_1x1():
    aspects = [3.0, 0.3] * 50
    calc = MultiSpanCalculator(aspects, 100, 5, 600, 600, 0)
    calc.run()
    layout = calc._result
    num_cols = max(1, round(605 / 105))
    cell_w = (600 - 5 * (num_cols - 1)) / num_cols
    min_cell = int(cell_w)
    multispan_count = sum(1 for i in range(len(aspects))
                          if layout[i].width() > min_cell + 10
                          or layout[i].height() > min_cell + 10)
    assert multispan_count > len(aspects) * 0.5, (
        f"Gap fill should prefer multispan: got {multispan_count}/{len(aspects)}"
    )
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            assert not layout[i].intersects(layout[j]), f"Items {i} and {j} overlap"

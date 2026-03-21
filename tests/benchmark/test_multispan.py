import time
import random

import pytest

from extensions.additional_layout.multispan import MultiSpanCalculator


SIZES = [100, 500, 1000, 5000, 10000]
WARMUP = 1
ITERATIONS = 3
CONTAINER = 1200
BASE_SIZE = 200
SPACING = 5


def _random_aspects(n, seed=42):
    rng = random.Random(seed)
    return [0.3 + rng.random() * 2.7 for _ in range(n)]


def _run_calc(aspects):
    calc = MultiSpanCalculator(aspects, BASE_SIZE, SPACING, CONTAINER, CONTAINER, 0)
    calc.run()
    return calc._result


def _measure(aspects, warmup=WARMUP, iterations=ITERATIONS):
    for _ in range(warmup):
        _run_calc(aspects)
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        _run_calc(aspects)
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return min(times), sum(times) / len(times)


def _coverage_ratio(layout, n, container, cell_size, spacing, num_cols):
    total_cell_area = sum(layout[i].width() * layout[i].height() for i in range(n))
    max_row = 0
    for i in range(n):
        r = layout[i]
        bottom = r.y() + r.height() + spacing
        if bottom > max_row:
            max_row = bottom
    bounding_area = container * max_row if max_row > 0 else 1
    return total_cell_area / bounding_area if bounding_area > 0 else 0.0


def _multispan_ratio(layout, n, cell_w):
    threshold = cell_w + 5
    count = sum(1 for i in range(n)
                if layout[i].width() > threshold or layout[i].height() > threshold)
    return count / n if n > 0 else 0.0


@pytest.mark.parametrize('n', SIZES)
def test_benchmark_speed(n):
    aspects = _random_aspects(n)
    best, avg = _measure(aspects)
    print(f"\n[MultiSpan] n={n:>5d}  best={best:.4f}s  avg={avg:.4f}s  "
          f"per_item={avg/n*1e6:.1f}us")


@pytest.mark.parametrize('n', SIZES)
def test_benchmark_coverage(n):
    aspects = _random_aspects(n)
    layout = _run_calc(aspects)
    num_cols = max(1, round((CONTAINER + SPACING) / (BASE_SIZE / 2 + SPACING)))
    cell_w = (CONTAINER - SPACING * (num_cols - 1)) / num_cols
    cov = _coverage_ratio(layout, n, CONTAINER, cell_w, SPACING, num_cols)
    multi = _multispan_ratio(layout, n, cell_w)
    print(f"\n[MultiSpan] n={n:>5d}  coverage={cov:.3f}  multispan_ratio={multi:.3f}")


def test_benchmark_no_gap_in_grid():
    aspects = _random_aspects(500)
    layout = _run_calc(aspects)
    n = len(aspects)
    num_cols = max(1, round((CONTAINER + SPACING) / (BASE_SIZE / 2 + SPACING)))
    cell_w = (CONTAINER - SPACING * (num_cols - 1)) / num_cols

    max_row = 0
    for i in range(n):
        r = layout[i]
        bottom = r.y() + r.height()
        if bottom > max_row:
            max_row = bottom

    grid = bytearray(int(CONTAINER) * int(max_row))
    width_i = int(CONTAINER)
    for i in range(n):
        r = layout[i]
        for py in range(r.y(), r.y() + r.height()):
            for px in range(r.x(), r.x() + r.width()):
                idx = py * width_i + px
                if 0 <= idx < len(grid):
                    grid[idx] = 1

    uncovered = 0
    total = 0
    for py in range(int(max_row)):
        for px in range(int(CONTAINER)):
            total += 1
            if not grid[py * width_i + px]:
                uncovered += 1

    gap_ratio = uncovered / total if total > 0 else 0
    print(f"\n[MultiSpan] gap_pixel_ratio={gap_ratio:.4f} ({uncovered}/{total})")


@pytest.mark.parametrize('n', [100, 500, 1000])
def test_benchmark_no_overlap(n):
    aspects = _random_aspects(n)
    layout = _run_calc(aspects)
    for i in range(n):
        for j in range(i + 1, n):
            assert not layout[i].intersects(layout[j]), f"Items {i} and {j} overlap"

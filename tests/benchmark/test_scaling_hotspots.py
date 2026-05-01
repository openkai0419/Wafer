from __future__ import annotations

import gc
import os
import time
import tracemalloc

import pytest

from wafer.app.viewer.grid.items import GridItemModel
from wafer.builtins.layouts import MasonryLayoutCalculator

pytestmark = pytest.mark.benchmark

MB = 1024 * 1024


def _benchmark_sizes() -> list[int]:
    raw = os.environ.get("WAFER_SCALING_BENCHMARK_SIZES", "")
    if raw.strip():
        return [int(part.strip().replace("_", "")) for part in raw.split(",") if part.strip()]
    sizes = [100_000, 200_000]
    if os.environ.get("WAFER_BENCHMARK_LARGE") == "1":
        sizes.extend([500_000, 1_000_000])
    return sizes


SIZES = _benchmark_sizes()


def _path(i: int) -> str:
    return f"c:/dataset/{i // 1000:05d}/file_{i:08d}.png"


def _cloned_text(text: str) -> str:
    return (" " + text)[1:]


@pytest.mark.parametrize("n", SIZES)
def test_indexer_scan_state_materialization(n):
    gc.collect()
    tracemalloc.start()
    t0 = time.perf_counter()
    current_compare = {}
    file_info = {}
    for i in range(n):
        p = _path(i)
        mtime = 1_700_000_000.0 + i
        size = 4096 + i % 65536
        current_compare[p] = (mtime, size)
        file_info[p] = (mtime, size, mtime - 10.0)
    previous = {_cloned_text(p): v for p, v in current_compare.items()}
    build_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    added = [p for p in current_compare if p not in previous or current_compare[p] != previous[p]]
    removed = [p for p in previous if p not in current_compare]
    diff_s = time.perf_counter() - t1
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"\n[scaling] indexer_state n={n:,} build={build_s:.3f}s diff={diff_s:.3f}s peak={peak / MB:.1f}MB added={len(added)} removed={len(removed)}")
    assert not added and not removed


@pytest.mark.parametrize("n", SIZES)
def test_grid_item_model_materialization(n):
    gc.collect()
    paths = [_path(i) for i in range(n)]
    sources = list(paths)
    aspects = [1.0 + (i % 7) * 0.1 for i in range(n)]
    tracemalloc.start()
    t0 = time.perf_counter()
    model = GridItemModel()
    model.set_items(paths, sources, aspects)
    elapsed = time.perf_counter() - t0
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"\n[scaling] grid_model n={n:,} set_items={elapsed:.3f}s peak={peak / MB:.1f}MB index={len(model._path_to_index):,}")
    assert model.count() == n


@pytest.mark.parametrize("n", SIZES)
def test_masonry_layout_materialization(n):
    gc.collect()
    aspects = [0.5 + (i % 11) * 0.17 for i in range(n)]
    tracemalloc.start()
    t0 = time.perf_counter()
    calc = MasonryLayoutCalculator(aspects, 180, 4, 1200, 800, 0)
    calc.run()
    elapsed = time.perf_counter() - t0
    layout = calc._result
    _current, peak = tracemalloc.get_traced_memory()
    visible = layout.calculate_visible_indices(0, 1000, 0, 1200)
    tracemalloc.stop()
    print(f"\n[scaling] masonry_layout n={n:,} run={elapsed:.3f}s per_item={elapsed / n * 1e6:.1f}us peak={peak / MB:.1f}MB visible={len(visible)} total_extent={layout.total_extent}")
    assert len(layout) == n

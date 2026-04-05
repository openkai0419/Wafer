import time
from pathlib import PureWindowsPath as FakePath

import pytest

from wafer.builtins.batch_renamer.engine import PostProcess, RenameColumn, RenameEngine
from wafer.builtins.rename_sources import NameSource, ExtSource

pytestmark = pytest.mark.benchmark

GENERATED_SIZES = [100, 1_000, 5_000, 10_000]
WARMUP = 2
ITERATIONS = 5


def _make_data(n):
    paths = [FakePath(f'C:/images/folder{i % 50:03d}/img_{i:06d}.png') for i in range(n)]
    metadata = {
        str(p).replace('\\', '/'): {'exif.Software': f'tool_{i % 10}'}
        for i, p in enumerate(paths)
    }
    name_col = RenameColumn(
        NameSource(),
        post=PostProcess(
            prefix='prefix_',
            suffix='_end',
            find=r'(\d{3})',
            replace=r'[\1]',
            find_regex=True,
            trim_start=None,
            trim_end=20,
        ),
    )
    fixed_col = RenameColumn(
        NameSource(),
        post=PostProcess(case_mode='upper'),
    )
    ext_column = RenameColumn(ExtSource())
    columns = [name_col, fixed_col]
    return paths, columns, ext_column, metadata


@pytest.mark.parametrize('n', GENERATED_SIZES)
def test_preview_performance(n):
    paths, columns, ext_column, metadata = _make_data(n)
    for _ in range(WARMUP):
        RenameEngine.preview(paths, columns, ext_column, metadata)

    elapsed = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        results, _ = RenameEngine.preview(paths, columns, ext_column, metadata)
        elapsed.append(time.perf_counter() - t0)

    avg = sum(elapsed) / len(elapsed)
    per_file = avg / n * 1000
    assert len(results) == n
    print(f'\n  [{n:>6} files]  avg={avg*1000:.1f}ms  per_file={per_file:.3f}ms')

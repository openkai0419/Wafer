import pytest
from pathlib import Path

from wafer.builtins.rename_sources import (
    NameSource, FixedSource, SequentialSource, ExtSource,
)
from wafer.app.viewer.renamer._engine import (
    PostProcess, RenameColumn, RenameResult, RenameEngine,
)


class TestPostProcess:

    def test_no_op(self):
        assert PostProcess().apply('hello') == 'hello'

    def test_trim(self):
        assert PostProcess(trim_start=2, trim_end=5).apply('abcdefg') == 'cde'

    def test_trim_start_only(self):
        assert PostProcess(trim_start=3).apply('abcde') == 'de'

    def test_trim_end_only(self):
        assert PostProcess(trim_end=-1).apply('abcde') == 'abcd'

    def test_find_replace(self):
        assert PostProcess(find='a', replace='x').apply('banana') == 'bxnxnx'

    def test_find_replace_regex(self):
        assert PostProcess(find=r'\d+', replace='N', find_regex=True).apply('abc123def') == 'abcNdef'

    def test_find_replace_regex_invalid(self):
        assert PostProcess(find='[invalid', replace='x', find_regex=True).apply('test') == 'test'

    def test_case_upper(self):
        assert PostProcess(case_mode='upper').apply('hello') == 'HELLO'

    def test_case_lower(self):
        assert PostProcess(case_mode='lower').apply('HeLLo') == 'hello'

    def test_case_title(self):
        assert PostProcess(case_mode='title').apply('hello world') == 'Hello World'

    def test_prefix_suffix(self):
        assert PostProcess(prefix='[', suffix=']').apply('x') == '[x]'

    def test_combined(self):
        pp = PostProcess(find='a', replace='x', case_mode='upper', prefix='(', suffix=')')
        assert pp.apply('abca') == '(XBCX)'


class TestRenameColumn:

    def test_basic(self):
        col = RenameColumn(NameSource())
        from wafer.plugin.rename.base import SegmentInfo
        seg = SegmentInfo(0, 1, Path('test.jpg'), 'test', 'jpg')
        assert col.evaluate(seg) == 'test'

    def test_with_post(self):
        col = RenameColumn(NameSource(), PostProcess(case_mode='upper'))
        from wafer.plugin.rename.base import SegmentInfo
        seg = SegmentInfo(0, 1, Path('test.jpg'), 'test', 'jpg')
        assert col.evaluate(seg) == 'TEST'

    def test_disabled(self):
        col = RenameColumn(NameSource(), enabled=False)
        assert not col.enabled


class TestRenameEngine:

    def test_simple(self):
        paths = [Path('a.jpg'), Path('b.jpg')]
        cols = [RenameColumn(NameSource())]
        ext = RenameColumn(ExtSource())
        results = RenameEngine.preview(paths, cols, ext)
        assert len(results) == 2
        assert results[0].new_name == 'a.jpg'
        assert results[1].new_name == 'b.jpg'
        assert not results[0].conflict
        assert not results[1].conflict

    def test_with_fixed(self):
        paths = [Path('a.jpg'), Path('b.jpg')]
        cols = [RenameColumn(FixedSource('prefix_')), RenameColumn(NameSource())]
        ext = RenameColumn(ExtSource())
        results = RenameEngine.preview(paths, cols, ext)
        assert results[0].new_name == 'prefix_a.jpg'
        assert results[1].new_name == 'prefix_b.jpg'

    def test_conflict_detection(self):
        paths = [Path('a.jpg'), Path('b.jpg')]
        cols = [RenameColumn(FixedSource('same'))]
        ext = RenameColumn(ExtSource())
        results = RenameEngine.preview(paths, cols, ext)
        assert results[0].conflict
        assert results[1].conflict

    def test_sequential(self):
        paths = [Path('x.jpg'), Path('y.jpg'), Path('z.jpg')]
        cols = [RenameColumn(SequentialSource(start=1, step=1, padding=3))]
        ext = RenameColumn(ExtSource())
        results = RenameEngine.preview(paths, cols, ext)
        assert results[0].new_name == '001.jpg'
        assert results[1].new_name == '002.jpg'
        assert results[2].new_name == '003.jpg'

    def test_disabled_column(self):
        paths = [Path('a.jpg')]
        cols = [
            RenameColumn(FixedSource('skip_'), enabled=False),
            RenameColumn(NameSource()),
        ]
        ext = RenameColumn(ExtSource())
        results = RenameEngine.preview(paths, cols, ext)
        assert results[0].new_name == 'a.jpg'

    def test_segments_include_all(self):
        paths = [Path('a.jpg')]
        cols = [RenameColumn(FixedSource('x')), RenameColumn(NameSource())]
        ext = RenameColumn(ExtSource())
        results = RenameEngine.preview(paths, cols, ext)
        assert len(results[0].segments) == 3
        assert results[0].segments[0] == 'x'
        assert results[0].segments[1] == 'a'
        assert results[0].segments[2] == '.jpg'

    def test_remove_ext(self):
        paths = [Path('a.jpg')]
        cols = [RenameColumn(NameSource())]
        ext = RenameColumn(ExtSource('remove'))
        results = RenameEngine.preview(paths, cols, ext)
        assert results[0].new_name == 'a'

    def test_custom_ext(self):
        paths = [Path('a.jpg')]
        cols = [RenameColumn(NameSource())]
        ext = RenameColumn(ExtSource('custom', 'png'))
        results = RenameEngine.preview(paths, cols, ext)
        assert results[0].new_name == 'a.png'

    def test_metadata_pass_through(self):
        paths = [Path('a.jpg')]
        from wafer.builtins.rename_sources import MetaSource
        cols = [RenameColumn(MetaSource(key='width'))]
        ext = RenameColumn(ExtSource())
        key = str(Path('a.jpg')).replace('\\', '/')
        results = RenameEngine.preview(
            paths, cols, ext,
            metadata={key: {'width': '1920'}},
            keys=[key],
        )
        assert results[0].new_name == '1920.jpg'

    def test_initial_paths_reindexing(self):
        paths = [Path('b.jpg'), Path('a.jpg')]
        keys = [str(p).replace('\\', '/') for p in paths]
        initial_keys = [str(p).replace('\\', '/') for p in [Path('a.jpg'), Path('b.jpg')]]
        cols = [RenameColumn(SequentialSource(start=1, step=1, padding=1))]
        ext = RenameColumn(ExtSource())
        results = RenameEngine.preview(paths, cols, ext, keys=keys, initial_keys=initial_keys)
        assert results[0].new_name == '2.jpg'
        assert results[1].new_name == '1.jpg'

    def test_case_insensitive_conflict(self):
        paths = [Path('a.jpg'), Path('b.jpg')]
        f1 = FixedSource('Name')
        f2 = FixedSource('name')
        f1.overrides = {str(Path('a.jpg')): 'Name'}
        f2.overrides = {str(Path('b.jpg')): 'name'}
        cols_a = [RenameColumn(FixedSource('test'))]
        cols_a[0].source.overrides[str(Path('a.jpg'))] = 'Name'
        cols_a[0].source.overrides[str(Path('b.jpg'))] = 'name'
        ext = RenameColumn(ExtSource())
        results = RenameEngine.preview(paths, cols_a, ext)
        assert results[0].conflict
        assert results[1].conflict

    def test_empty_paths(self):
        results = RenameEngine.preview(
            [], [RenameColumn(NameSource())], RenameColumn(ExtSource()),
        )
        assert results == []

    def test_errors_on_invalid_filename(self):
        paths = [Path('a.jpg')]
        cols = [RenameColumn(FixedSource('CON'))]
        ext = RenameColumn(ExtSource())
        results = RenameEngine.preview(paths, cols, ext)
        assert 'reserved_name' in results[0].errors

    def test_no_errors_on_valid_filename(self):
        paths = [Path('a.jpg')]
        cols = [RenameColumn(NameSource())]
        ext = RenameColumn(ExtSource())
        results = RenameEngine.preview(paths, cols, ext)
        assert results[0].errors == []

    def test_conflict_with_existing_sibling(self):
        paths = [Path('a.jpg'), Path('b.jpg')]
        cols = [RenameColumn(FixedSource('b'))]
        ext = RenameColumn(ExtSource())
        results = RenameEngine.preview(paths, cols, ext)
        assert results[0].conflict

    def test_errors_on_path_separator(self):
        paths = [Path('a.jpg')]
        cols = [RenameColumn(FixedSource('sub/name'))]
        ext = RenameColumn(ExtSource())
        results = RenameEngine.preview(paths, cols, ext)
        assert 'invalid_chars' in results[0].errors

    def test_errors_on_backslash(self):
        paths = [Path('a.jpg')]
        cols = [RenameColumn(FixedSource('sub\\name'))]
        ext = RenameColumn(ExtSource())
        results = RenameEngine.preview(paths, cols, ext)
        assert 'invalid_chars' in results[0].errors

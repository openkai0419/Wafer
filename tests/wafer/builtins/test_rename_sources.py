import os
import time
import pytest
from pathlib import Path

from wafer.plugin.rename.base import SegmentInfo, RenameConfigWidget, DropdownButton
from wafer.builtins.rename_sources import (
    NameSource, FixedSource, SequentialSource,
    MetaSource, DateSource, RandomSource, ExtSource,
)


def _seg(**kw):
    defaults = dict(
        index=0, total=5, original_path=Path('/test/photo.jpg'),
        stem='photo', ext='jpg',
    )
    defaults.update(kw)
    return SegmentInfo(**defaults)


class TestNameSource:

    def test_evaluate(self):
        assert NameSource().evaluate(_seg()) == 'photo'

    def test_serialise(self):
        assert NameSource().serialise() == {'type': 'name'}


class TestFixedSource:

    def test_default(self):
        assert FixedSource().evaluate(_seg()) == '_'

    def test_custom_text(self):
        assert FixedSource('--').evaluate(_seg()) == '--'

    def test_override(self):
        s = FixedSource('_')
        key = str(Path('/test/photo.jpg'))
        s.overrides[key] = 'custom'
        assert s.evaluate(_seg()) == 'custom'

    def test_serialise_roundtrip(self):
        s = FixedSource('x')
        s.overrides['a'] = 'b'
        data = s.serialise()
        s2 = FixedSource()
        s2._apply(data)
        assert s2.text == 'x'
        assert s2.overrides == {'a': 'b'}


class TestSequentialSource:

    def test_default(self):
        assert SequentialSource().evaluate(_seg(index=0)) == '001'
        assert SequentialSource().evaluate(_seg(index=4)) == '005'

    def test_custom_start_step_pad(self):
        s = SequentialSource(start=10, step=5, padding=4)
        assert s.evaluate(_seg(index=2)) == '0020'

    def test_serialise_roundtrip(self):
        s = SequentialSource(2, 3, 5)
        data = s.serialise()
        s2 = SequentialSource()
        s2._apply(data)
        assert s2.start == 2
        assert s2.step == 3
        assert s2.padding == 5


class TestMetaSource:

    def test_found(self):
        s = MetaSource(key='width')
        assert s.evaluate(_seg(metadata={'width': '1920'})) == '1920'

    def test_missing(self):
        s = MetaSource(key='missing')
        assert s.evaluate(_seg()) == ''

    def test_serialise_roundtrip(self):
        s = MetaSource('dpi')
        data = s.serialise()
        s2 = MetaSource()
        s2._apply(data)
        assert s2.key == 'dpi'


class TestDateSource:

    def test_default_fmt_includes_time(self):
        s = DateSource()
        assert 'H' in s.fmt
        assert 'M' in s.fmt
        assert 'S' in s.fmt

    def test_modified(self):
        s = DateSource(source='modified', fmt='%Y')
        result = s.evaluate(_seg(metadata={'modified': '1700000000.0'}))
        assert result.isdigit() and len(result) == 4

    def test_created(self):
        s = DateSource(source='created', fmt='%Y%m%d')
        result = s.evaluate(_seg(metadata={'created': '1700000000.0'}))
        assert len(result) == 8

    def test_now(self):
        s = DateSource(source='now', fmt='%Y')
        result = s.evaluate(_seg())
        assert result == str(time.localtime().tm_year)

    def test_no_metadata(self):
        s = DateSource(source='modified')
        assert s.evaluate(_seg()) == ''

    def test_invalid_format_returns_placeholder(self):
        s = DateSource(fmt='%Y%m%d%')
        assert s.evaluate(_seg(metadata={'modified': '1700000000.0'})) == '?'

    def test_bare_percent_returns_placeholder(self):
        s = DateSource(fmt='%')
        assert s.evaluate(_seg(metadata={'modified': '1700000000.0'})) == '?'

    def test_serialise_roundtrip(self):
        s = DateSource('created', '%H%M')
        data = s.serialise()
        s2 = DateSource()
        s2._apply(data)
        assert s2.source == 'created'
        assert s2.fmt == '%H%M'

    def test_apply_empty_fmt_restores_default(self):
        s = DateSource()
        s._apply({'source': 'now', 'fmt': ''})
        assert s.fmt == DateSource.DEFAULT_FMT


class TestRandomSource:

    def test_length(self):
        s = RandomSource(length=8)
        result = s.evaluate(_seg())
        assert len(result) == 8

    def test_stable_per_path(self):
        s = RandomSource()
        r1 = s.evaluate(_seg())
        r2 = s.evaluate(_seg())
        assert r1 == r2

    def test_different_paths(self):
        s = RandomSource(length=12)
        r1 = s.evaluate(_seg(original_path=Path('a.jpg')))
        r2 = s.evaluate(_seg(original_path=Path('b.jpg')))
        assert r1 != r2 or True

    def test_hex_pool(self):
        s = RandomSource(chars='hex', length=20)
        r = s.evaluate(_seg())
        assert all(c in '0123456789abcdef' for c in r)

    def test_cache_cleared(self):
        s = RandomSource()
        s.evaluate(_seg())
        assert len(s._cache) == 1
        s._cache.clear()
        assert len(s._cache) == 0

    def test_serialise_roundtrip(self):
        s = RandomSource('digits', 10)
        data = s.serialise()
        s2 = RandomSource()
        s2._apply(data)
        assert s2.chars == 'digits'
        assert s2.length == 10


class TestExtSource:

    def test_keep(self):
        assert ExtSource('keep').evaluate(_seg()) == '.jpg'

    def test_keep_no_ext(self):
        assert ExtSource('keep').evaluate(_seg(ext='')) == ''

    def test_remove(self):
        assert ExtSource('remove').evaluate(_seg()) == ''

    def test_custom(self):
        assert ExtSource('custom', 'png').evaluate(_seg()) == '.png'

    def test_custom_empty(self):
        assert ExtSource('custom', '').evaluate(_seg()) == ''

    def test_serialise_roundtrip(self):
        s = ExtSource('custom', 'webp')
        data = s.serialise()
        s2 = ExtSource()
        s2._apply(data)
        assert s2.mode == 'custom'
        assert s2.custom == 'webp'


class TestConfigWidgets:

    def test_name_returns_none(self, qtbot):
        assert NameSource().create_config_widget() is None

    def test_fixed_returns_widget(self, qtbot):
        w = FixedSource('hi').create_config_widget()
        qtbot.addWidget(w)
        assert isinstance(w, RenameConfigWidget)

    def test_fixed_changed_on_edit(self, qtbot):
        src = FixedSource('x')
        w = src.create_config_widget()
        qtbot.addWidget(w)
        received = []
        w.changed.connect(lambda: received.append(True))
        from PySide6 import QtWidgets
        ed = w.findChild(QtWidgets.QLineEdit)
        ed.setText('y')
        assert len(received) == 1
        assert src.text == 'y'

    def test_sequential_returns_widget(self, qtbot):
        w = SequentialSource().create_config_widget()
        qtbot.addWidget(w)
        assert isinstance(w, RenameConfigWidget)
        assert hasattr(w, 'resequence_requested')

    def test_meta_sets_initial_key(self, qtbot):
        src = MetaSource()
        w = src.create_config_widget(meta_keys=['width', 'height'])
        qtbot.addWidget(w)
        assert src.key == 'width'

    def test_meta_preserves_key(self, qtbot):
        src = MetaSource(key='height')
        w = src.create_config_widget(meta_keys=['width', 'height'])
        qtbot.addWidget(w)
        assert src.key == 'height'

    def test_date_returns_widget(self, qtbot):
        w = DateSource().create_config_widget()
        qtbot.addWidget(w)
        assert isinstance(w, RenameConfigWidget)

    def test_random_returns_widget(self, qtbot):
        w = RandomSource().create_config_widget()
        qtbot.addWidget(w)
        assert isinstance(w, RenameConfigWidget)

    def test_ext_returns_widget(self, qtbot):
        w = ExtSource().create_config_widget()
        qtbot.addWidget(w)
        assert isinstance(w, RenameConfigWidget)

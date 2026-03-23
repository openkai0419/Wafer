import pytest
from pathlib import Path

from wafer.plugin.rename.base import (
    BaseRenameSourcePlugin,
    SegmentInfo,
    RenameConfigWidget,
)


def _make_segment(**kw):
    defaults = dict(
        index=0, total=1, original_path=Path('img.jpg'),
        stem='img', ext='jpg',
    )
    defaults.update(kw)
    return SegmentInfo(**defaults)


class TestSegmentInfo:

    def test_defaults(self):
        s = _make_segment()
        assert s.metadata == {}
        assert s.stat is None

    def test_with_metadata(self):
        s = _make_segment(metadata={'width': '1920'})
        assert s.metadata['width'] == '1920'


class TestBaseRenameSourcePlugin:

    def test_abstract(self):
        with pytest.raises(TypeError):
            BaseRenameSourcePlugin()

    def test_concrete(self):
        class Dummy(BaseRenameSourcePlugin):
            NAME = 'dummy'
            DISPLAY = 'Dummy'
            def evaluate(self, segment):
                return segment.stem

        d = Dummy()
        assert d.evaluate(_make_segment()) == 'img'

    def test_serialise_default(self):
        class Src(BaseRenameSourcePlugin):
            NAME = 'src'
            def evaluate(self, segment):
                return ''

        assert Src().serialise() == {'type': 'src'}

    def test_apply_noop(self):
        class Src(BaseRenameSourcePlugin):
            NAME = 'src'
            def evaluate(self, segment):
                return ''

        Src()._apply({'extra': 1})

    def test_create_config_widget_returns_none(self):
        class Src(BaseRenameSourcePlugin):
            NAME = 'src'
            def evaluate(self, segment):
                return ''

        assert Src().create_config_widget() is None


class TestRenameConfigWidget:

    def test_instantiate(self):
        w = RenameConfigWidget()
        assert w is not None

    def test_connect_extra_noop(self):
        w = RenameConfigWidget()
        w.connect_extra(object())

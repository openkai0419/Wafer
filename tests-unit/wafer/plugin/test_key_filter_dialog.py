import pytest

from wafer.plugin.key_filter_dialog import recollect_target_lines


class _FakeRegistry:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, prefix):
        return self._mapping.get(prefix)


@pytest.fixture
def _patch_registry(monkeypatch):
    def apply(mapping, parser_mapping=None):
        monkeypatch.setattr(
            "wafer.plugin.key_filter_dialog.collector_resolver.registry",
            _FakeRegistry(mapping),
        )
        monkeypatch.setattr(
            "wafer.plugin.key_filter_dialog.parser_resolver.registry",
            _FakeRegistry(parser_mapping or {}),
        )

    return apply


class TestRecollectTargetLines:
    def test_no_collector(self, _patch_registry):
        _patch_registry({})
        lines = recollect_target_lines(["ghost"])
        assert lines == ["  ghost: no collector (delete only)"]

    def test_with_collector_shows_prefix_only(self, _patch_registry):
        cls = type("C", (), {"EXTENSIONS": (".jpg", ".png")})
        _patch_registry({"exiftool": cls})
        lines = recollect_target_lines(["exiftool"])
        assert lines == ["  exiftool"]

    def test_parser_shows_delete_only(self, _patch_registry):
        cls = type("P", (), {"TRIGGER_KEYS": ("exiftool.PNG:Comment",)})
        _patch_registry({}, {"novelai": cls})
        lines = recollect_target_lines(["novelai"])
        assert lines == ["  novelai: parser (delete only)"]

    def test_empty_extensions_shows_prefix_only(self, _patch_registry):
        cls = type("C", (), {"EXTENSIONS": ()})
        _patch_registry({"wd14": cls})
        lines = recollect_target_lines(["wd14"])
        assert lines == ["  wd14"]

    def test_multiple_prefixes(self, _patch_registry):
        cls = type("C", (), {"EXTENSIONS": (".mp4",)})
        _patch_registry({"ffmpeg": cls})
        lines = recollect_target_lines(["ffmpeg", "missing"])
        assert lines == ["  ffmpeg", "  missing: no collector (delete only)"]

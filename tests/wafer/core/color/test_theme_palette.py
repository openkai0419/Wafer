import pytest
from wafer.core.color.theme_palette import DARK, LIGHT, ThemePalette


class TestThemePalette:

    def test_dark_is_frozen(self):
        with pytest.raises(AttributeError):
            DARK.bg_primary = "#000"

    def test_light_is_frozen(self):
        with pytest.raises(AttributeError):
            LIGHT.bg_primary = "#fff"

    def test_dark_and_light_differ(self):
        assert DARK.bg_primary != LIGHT.bg_primary
        assert DARK.text_primary != LIGHT.text_primary

    def test_all_fields_are_strings(self):
        for palette in (DARK, LIGHT):
            for field in ThemePalette.__dataclass_fields__:
                assert isinstance(getattr(palette, field), str)

    def test_custom_palette(self):
        p = ThemePalette(
            bg_primary="#111", bg_secondary="#222", bg_elevated="#333",
            bg_hover="rgba(0,0,0,0.1)", bg_pressed="rgba(0,0,0,0.2)",
            text_primary="#eee", text_secondary="#ddd",
            text_muted="#bbb", text_accent="#00f",
            border_default="#444", border_subtle="#555",
            success="#0f0", warning="#ff0", error="#f00", info="#00f",
        )
        assert p.bg_primary == "#111"

    def test_from_system(self, qtbot):
        p = ThemePalette.from_system()
        assert isinstance(p, ThemePalette)
        for field in ThemePalette.__dataclass_fields__:
            assert isinstance(getattr(p, field), str)

    def test_from_system_no_app(self, monkeypatch):
        from PySide6 import QtGui
        monkeypatch.setattr(QtGui.QGuiApplication, "instance", staticmethod(lambda: None))
        assert ThemePalette.from_system() is DARK

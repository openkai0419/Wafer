import pytest
from wafer.qt.palette import DARK, ThemePalette


class TestThemePalette:
    def test_dark_is_frozen(self):
        with pytest.raises(AttributeError):
            DARK.bg_primary = "#000"

    def test_from_system(self, qtbot):
        p = ThemePalette.from_system()
        assert isinstance(p, ThemePalette)
        for field in ThemePalette.__dataclass_fields__:
            assert isinstance(getattr(p, field), str)

    def test_from_system_no_app(self, monkeypatch):
        from PySide6 import QtGui

        monkeypatch.setattr(QtGui.QGuiApplication, "instance", staticmethod(lambda: None))
        assert ThemePalette.from_system() is DARK

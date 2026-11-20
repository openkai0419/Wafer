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


def test_rgba_accepts_hex_and_qcolor():
    from PySide6 import QtGui
    from wafer.qt.palette import rgba

    assert rgba("#3B80FF", 0.15) == "rgba(59,128,255,0.15)"
    assert rgba("#ccc", 0.5) == "rgba(204,204,204,0.5)"
    assert rgba(QtGui.QColor(1, 2, 3), 1) == "rgba(1,2,3,1)"

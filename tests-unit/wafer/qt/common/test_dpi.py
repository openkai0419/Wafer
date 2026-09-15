import wafer.qt.common.dpi as _dpi_mod
from wafer.qt.common.dpi import dpix


def test_dpix_caches_dpi_value():
    _dpi_mod._cached_dpi = None
    from PySide6 import QtGui

    if QtGui.QGuiApplication.primaryScreen() is None:
        assert dpix(10) == 10
        return
    result1 = dpix(10)
    assert _dpi_mod._cached_dpi is not None
    cached = _dpi_mod._cached_dpi
    result2 = dpix(10)
    assert _dpi_mod._cached_dpi is cached
    assert result1 == result2


def test_dpix_uses_cached_value():
    _dpi_mod._cached_dpi = 192.0
    assert dpix(10) == 20
    assert dpix(5) == 10
    _dpi_mod._cached_dpi = None


def test_dpix_no_screen_returns_raw(monkeypatch):
    _dpi_mod._cached_dpi = None
    from PySide6 import QtGui

    monkeypatch.setattr(QtGui.QGuiApplication, "primaryScreen", lambda: None)
    assert dpix(5) == 5
    _dpi_mod._cached_dpi = None

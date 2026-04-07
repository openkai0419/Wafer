from wafer.utils.formatting import split_last, format_timestamp, format_aspect, format_size, format_size_detail
import wafer.utils.formatting as _fmt_mod


def test_dpix_caches_dpi_value():
    _fmt_mod._cached_dpi = None
    from wafer.utils.formatting import dpix
    from PySide6 import QtGui

    if QtGui.QGuiApplication.primaryScreen() is None:
        assert dpix(10) == 10
        return
    result1 = dpix(10)
    assert _fmt_mod._cached_dpi is not None
    cached = _fmt_mod._cached_dpi
    result2 = dpix(10)
    assert _fmt_mod._cached_dpi is cached
    assert result1 == result2


def test_dpix_uses_cached_value():
    _fmt_mod._cached_dpi = 192.0
    from wafer.utils.formatting import dpix

    assert dpix(10) == 20
    assert dpix(5) == 10
    _fmt_mod._cached_dpi = None


def test_dpix_no_screen_returns_raw(monkeypatch):
    _fmt_mod._cached_dpi = None
    from PySide6 import QtGui

    monkeypatch.setattr(QtGui.QGuiApplication, "primaryScreen", lambda: None)
    from wafer.utils.formatting import dpix

    assert dpix(5) == 5
    _fmt_mod._cached_dpi = None


def test_split_last():
    rest, last = split_last([1, 2, 3])
    assert rest == [1, 2]
    assert last == 3


def test_split_last_empty():
    rest, last = split_last([])
    assert rest == []
    assert last is None


def test_split_last_single():
    rest, last = split_last([42])
    assert rest == []
    assert last == 42


def test_format_timestamp():
    import datetime

    ts = datetime.datetime(2024, 1, 15, 12, 30, 45).timestamp()
    result = format_timestamp(ts)
    assert "2024-01-15" in result
    assert "12:30:45" in result


def test_format_timestamp_none():
    assert format_timestamp(None) is None


def test_format_aspect():
    assert format_aspect(1.0) == "1:1"
    assert format_aspect(None) is None
    assert format_aspect(0) == "N/A"
    assert format_aspect(-1) == "N/A"


def test_format_aspect_ratio():
    result = format_aspect(16 / 9)
    assert "16" in result
    assert "9" in result


def test_format_size():
    assert format_size(0) == "0.0 B"
    assert "KB" in format_size(1024)
    assert "MB" in format_size(1024 * 1024)
    assert format_size(None) is None


def test_format_size_detail():
    result = format_size_detail(1500)
    assert "bytes" in result
    assert "1,500" in result
    assert format_size_detail(None) is None

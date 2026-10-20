import ctypes
import sys
from types import SimpleNamespace

import pytest

from wafer.core.platform import foreground


def fake_user32(iconic: int, result: int, calls: list):
    return SimpleNamespace(
        IsIconic=lambda hwnd: iconic,
        ShowWindow=lambda hwnd, cmd: calls.append(("ShowWindow", hwnd, cmd)),
        SetForegroundWindow=lambda hwnd: calls.append(("SetForegroundWindow", hwnd)) or result,
    )


def test_zero_hwnd_returns_false():
    assert foreground.activate_window(0) is False


@pytest.mark.skipif(sys.platform != "win32", reason="win32-only")
def test_minimized_window_is_restored_before_foreground(monkeypatch):
    calls = []
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=fake_user32(1, 1, calls)), raising=False)
    assert foreground.activate_window(99) is True
    assert calls == [("ShowWindow", 99, 9), ("SetForegroundWindow", 99)]


@pytest.mark.skipif(sys.platform != "win32", reason="win32-only")
def test_visible_window_is_not_restored(monkeypatch):
    calls = []
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=fake_user32(0, 1, calls)), raising=False)
    assert foreground.activate_window(99) is True
    assert calls == [("SetForegroundWindow", 99)]


@pytest.mark.skipif(sys.platform != "win32", reason="win32-only")
def test_any_pointer_sized_handle_is_accepted():
    assert foreground.activate_window(2**31 + 12345) is False
    assert foreground.activate_window(2**32 + 5) is False
    assert foreground.activate_window(2**40) is False


@pytest.mark.skipif(sys.platform != "win32", reason="win32-only")
def test_failed_foreground_returns_false(monkeypatch):
    calls = []
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=fake_user32(0, 0, calls)), raising=False)
    assert foreground.activate_window(99) is False

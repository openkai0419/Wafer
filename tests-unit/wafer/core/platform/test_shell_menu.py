import ctypes
import ctypes.wintypes as wt
import sys

import pytest

from wafer.core.platform import shell_menu
from wafer.core.platform.shell_menu import show_shell_context_menu


@pytest.fixture
def hwnd():
    user32 = ctypes.windll.user32
    user32.CreateWindowExW.restype = wt.HWND
    handle = user32.CreateWindowExW(0, "STATIC", "shell_menu_test", 0, 0, 0, 10, 10, None, None, None, None)
    yield handle
    user32.DestroyWindow(wt.HWND(handle))


@pytest.fixture
def com_spy(monkeypatch):
    real_vt = shell_menu._vt
    real_query_interface = shell_menu._query_interface
    real_release = shell_menu._release
    spy = {"folders": [], "context_menus": [], "acquired": [], "released": []}

    def vt(obj, index, restype, *argtypes):
        if index == shell_menu._ISF_GetUIObjectOf:
            spy["folders"].append(obj)
            spy["acquired"].append(obj)
        if index == shell_menu._ICM_QueryContextMenu:
            return lambda *args: 0
        return real_vt(obj, index, restype, *argtypes)

    def query_interface(obj, iid):
        if obj not in spy["context_menus"]:
            spy["context_menus"].append(obj)
            spy["acquired"].append(obj)
        result = real_query_interface(obj, iid)
        if result:
            spy["acquired"].append(result)
        return result

    def release(obj):
        if obj:
            spy["released"].append(obj)
        real_release(obj)

    monkeypatch.setattr(shell_menu, "_vt", vt)
    monkeypatch.setattr(shell_menu, "_query_interface", query_interface)
    monkeypatch.setattr(shell_menu, "_release", release)
    shell_menu._ensure_argtypes()
    monkeypatch.setattr(ctypes.windll.user32, "TrackPopupMenu", lambda *args: 0)
    return spy


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
class TestShellContextMenu:
    def test_empty_paths_returns_false(self):
        assert show_shell_context_menu([], 0, 0, 0) is False

    def test_nonexistent_path_returns_false(self, tmp_path):
        fake = str(tmp_path / "nonexistent_file_12345.txt")
        assert show_shell_context_menu([fake], 0, 0, 0) is False

    def test_valid_path_no_hwnd_returns_false(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        assert show_shell_context_menu([str(f)], 0, 0, 0) is False

    def test_multiple_same_dir_no_hwnd_returns_false(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("a", encoding="utf-8")
        b.write_text("b", encoding="utf-8")
        assert show_shell_context_menu([str(a), str(b)], 0, 0, 0) is False

    def test_multiple_different_dirs_uses_desktop_folder(self, tmp_path):
        d1 = tmp_path / "dir1"
        d2 = tmp_path / "dir2"
        d1.mkdir()
        d2.mkdir()
        f1 = d1 / "x.txt"
        f2 = d2 / "y.txt"
        f1.write_text("x", encoding="utf-8")
        f2.write_text("y", encoding="utf-8")
        assert show_shell_context_menu([str(f1), str(f2)], 0, 0, 0) is False

    def test_releases_folder_and_context_menu_same_dir(self, tmp_path, hwnd, com_spy):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("a", encoding="utf-8")
        b.write_text("b", encoding="utf-8")

        assert show_shell_context_menu([str(a), str(b)], hwnd, 0, 0) is False

        assert len(com_spy["folders"]) == 1
        assert len(com_spy["context_menus"]) == 1
        assert sorted(com_spy["released"]) == sorted(com_spy["acquired"])

    def test_releases_desktop_folder_once_for_different_dirs(self, tmp_path, hwnd, com_spy):
        d1 = tmp_path / "dir1"
        d2 = tmp_path / "dir2"
        d1.mkdir()
        d2.mkdir()
        f1 = d1 / "x.txt"
        f2 = d2 / "y.txt"
        f1.write_text("x", encoding="utf-8")
        f2.write_text("y", encoding="utf-8")

        assert show_shell_context_menu([str(f1), str(f2)], hwnd, 0, 0) is False

        assert len(com_spy["folders"]) == 1
        assert len(com_spy["context_menus"]) == 1
        assert sorted(com_spy["released"]) == sorted(com_spy["acquired"])


class TestShellContextMenuNonWindows:
    def test_non_windows_returns_false(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert show_shell_context_menu(["C:\\some\\path"], 123, 0, 0) is False

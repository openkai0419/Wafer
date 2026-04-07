import sys
import pytest

from wafer.core.platform.shell_menu import show_shell_context_menu


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


class TestShellContextMenuNonWindows:
    def test_non_windows_returns_false(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert show_shell_context_menu(["C:\\some\\path"], 123, 0, 0) is False

import sys
from types import SimpleNamespace

from PySide6 import QtWidgets

from source.actions.bridge import Menu
from source.image_viewer.commands import file_commands
from source.image_viewer.commands.file_commands import FileCommands
from source.os.save import get_os_new_folder_name


def test_file_commands_register_paths(qtbot):
    FileCommands.register()
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    m = Menu.session(parent).menu(["file.copy_path", "file.paste"]).build()
    assert m is not None
    assert m.actions()


class _Ctx:
    def __init__(self, path=None, paths=None):
        self._path = path
        self._paths = list(paths) if paths else None

    def get(self, key, default=None):
        if key == "path":
            return self._path
        if key == "paths":
            return self._paths
        return default

    def get_instance(self, name):
        return None


def test_delete_files_cancel_does_not_delete(tmp_path, monkeypatch):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    monkeypatch.setattr(file_commands.ThumbnailConfirmDialog, "ask", lambda *a, **k: "Cancel")
    file_commands.delete_files(_Ctx(path=str(p)))
    assert p.exists()


def test_delete_files_send2trash_failure_falls_back(tmp_path, monkeypatch):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    monkeypatch.setattr(file_commands.ThumbnailConfirmDialog, "ask", lambda *a, **k: "Delete")
    dummy = SimpleNamespace(send2trash=lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")))
    monkeypatch.setitem(sys.modules, "send2trash", dummy)
    file_commands.delete_files(_Ctx(path=str(p)))
    assert not p.exists()


def test_show_in_explorer_ignores_missing_path():
    file_commands.show_in_explorer(_Ctx(path="Z:/__missing__"))


def test_make_new_folder_here_creates_folder(tmp_path):
    folder = file_commands.make_new_folder_here(_Ctx(path=str(tmp_path)))
    assert folder is not None
    assert (tmp_path / get_os_new_folder_name()).exists()


def test_make_new_folder_here_unique_names(tmp_path):
    name = get_os_new_folder_name()
    (tmp_path / name).mkdir()
    folder = file_commands.make_new_folder_here(_Ctx(path=str(tmp_path)))
    assert folder is not None
    assert (tmp_path / f"{name} (2)").exists()


def test_make_new_folder_here_with_file_path(tmp_path):
    file_path = tmp_path / "test.txt"
    file_path.write_text("x", encoding="utf-8")
    folder = file_commands.make_new_folder_here(_Ctx(path=str(file_path)))
    assert folder is not None
    assert (tmp_path / get_os_new_folder_name()).exists()


def test_make_new_folder_here_custom_name(tmp_path):
    folder = file_commands.make_new_folder_here(_Ctx(path=str(tmp_path)), folder_name="MyFolder")
    assert folder is not None
    assert (tmp_path / "MyFolder").exists()


def test_make_new_folder_here_returns_none_without_path():
    result = file_commands.make_new_folder_here(_Ctx(path=None))
    assert result is None

import sys
from types import SimpleNamespace

from PySide6 import QtWidgets

from source.actions.bridge import Menu
from source.image_viewer.commands import file_commands
from source.image_viewer.commands.file_commands import FileCommands


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
    monkeypatch.setattr(file_commands.ConfirmDialog, "ask", lambda *a, **k: "Cancel")
    file_commands.delete_files(_Ctx(path=str(p)))
    assert p.exists()


def test_delete_files_send2trash_failure_falls_back(tmp_path, monkeypatch):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    monkeypatch.setattr(file_commands.ConfirmDialog, "ask", lambda *a, **k: "Delete")
    dummy = SimpleNamespace(send2trash=lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")))
    monkeypatch.setitem(sys.modules, "send2trash", dummy)
    file_commands.delete_files(_Ctx(path=str(p)))
    assert not p.exists()


def test_show_in_explorer_ignores_missing_path():
    file_commands.show_in_explorer(_Ctx(path="Z:/__missing__"))

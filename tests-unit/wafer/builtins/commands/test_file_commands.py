import sys
from types import SimpleNamespace

from PySide6 import QtWidgets

from wafer.core.commands.bridge import Menu
from wafer.builtins.commands import file_commands
from wafer.builtins.commands.file_commands import FileCommands
from wafer.core.platform.path_utils import get_os_new_folder_name


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
    monkeypatch.setattr(
        file_commands.ThumbnailConfirmDialog, "exec",
        lambda self: setattr(self, "result_text", "Cancel"),
    )
    file_commands.delete_files(_Ctx(path=str(p)))
    assert p.exists()


def test_delete_files_send2trash_failure_falls_back(tmp_path, monkeypatch):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        file_commands.ThumbnailConfirmDialog, "exec",
        lambda self: setattr(self, "result_text", "Delete"),
    )
    dummy = SimpleNamespace(send2trash=lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")))
    monkeypatch.setitem(sys.modules, "send2trash", dummy)
    file_commands.delete_files(_Ctx(path=str(p)))
    assert not p.exists()


def test_delete_files_calls_delete_to_trash(tmp_path, monkeypatch):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        file_commands.ThumbnailConfirmDialog, "exec",
        lambda self: setattr(self, "result_text", "Delete"),
    )
    from wafer.core.platform.file_operations import OperationResult

    called_with: list = []
    monkeypatch.setattr(
        file_commands, "delete_to_trash",
        lambda paths: (called_with.extend(paths), [OperationResult(action="delete", src=str(p), dst="", status="ok")])[1],
    )
    file_commands.delete_files(_Ctx(path=str(p)))
    assert str(p) in called_with


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


def test_rename_file_success(tmp_path, monkeypatch):
    f = tmp_path / "old.txt"
    f.write_text("hi", encoding="utf-8")
    from wafer.ui import dialogs as _dlg_mod

    monkeypatch.setattr(
        _dlg_mod.InputDialog,
        "get_text",
        staticmethod(lambda *a, **k: "new.txt"),
    )
    file_commands.rename_file(_Ctx(path=str(f)))
    assert not f.exists()
    assert (tmp_path / "new.txt").exists()


def test_rename_file_cancel(tmp_path, monkeypatch):
    f = tmp_path / "old.txt"
    f.write_text("hi", encoding="utf-8")
    from wafer.ui import dialogs as _dlg_mod

    monkeypatch.setattr(
        _dlg_mod.InputDialog,
        "get_text",
        staticmethod(lambda *a, **k: None),
    )
    file_commands.rename_file(_Ctx(path=str(f)))
    assert f.exists()


def test_rename_file_same_name(tmp_path, monkeypatch):
    f = tmp_path / "old.txt"
    f.write_text("hi", encoding="utf-8")
    from wafer.ui import dialogs as _dlg_mod

    monkeypatch.setattr(
        _dlg_mod.InputDialog,
        "get_text",
        staticmethod(lambda *a, **k: "old.txt"),
    )
    file_commands.rename_file(_Ctx(path=str(f)))
    assert f.exists()


def test_rename_file_conflict(tmp_path, monkeypatch):
    f = tmp_path / "old.txt"
    f.write_text("hi", encoding="utf-8")
    (tmp_path / "taken.txt").write_text("x", encoding="utf-8")
    from wafer.ui import dialogs as _dlg_mod

    monkeypatch.setattr(
        _dlg_mod.InputDialog,
        "get_text",
        staticmethod(lambda *a, **k: "taken.txt"),
    )
    from wafer.core.platform.file_operations import OperationResult

    monkeypatch.setattr(
        file_commands,
        "execute_paste_plans_with_ui",
        lambda **kw: [OperationResult(action="skip", src=str(f), dst="", status="skipped")],
    )
    file_commands.rename_file(_Ctx(path=str(f)))
    assert f.exists()


def test_rename_file_invalid_name(tmp_path, monkeypatch):
    f = tmp_path / "old.txt"
    f.write_text("hi", encoding="utf-8")
    from wafer.ui import dialogs as _dlg_mod

    monkeypatch.setattr(
        _dlg_mod.InputDialog,
        "get_text",
        staticmethod(lambda *a, **k: "bad<name>.txt"),
    )
    file_commands.rename_file(_Ctx(path=str(f)))
    assert f.exists()


def test_rename_file_no_path():
    file_commands.rename_file(_Ctx())


def test_make_new_folder_here_custom_name(tmp_path):
    folder = file_commands.make_new_folder_here(_Ctx(path=str(tmp_path)), folder_name="MyFolder")
    assert folder is not None
    assert (tmp_path / "MyFolder").exists()


def test_make_new_folder_here_returns_none_without_path():
    result = file_commands.make_new_folder_here(_Ctx(path=None))
    assert result is None

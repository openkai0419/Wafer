import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6 import QtWidgets

from wafer.qt.commands.bridge import Command, Menu
from wafer.builtins.commands import file as file_mod
from wafer.builtins.commands.file import FileCommands
from wafer.core.platform.path_utils import get_os_new_folder_name
from wafer.core.common.virtual_paths import build_virtual_path


def test_file_commands_register_paths(qtbot):
    FileCommands.register()
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    m = Menu.session(parent).menu(["file.copy_path", "file.paste"]).build()
    assert m is not None
    assert m.actions()


class _Ctx:
    def __init__(self, path=None, paths=None, source=None, sources=None):
        self._path = path
        self._paths = list(paths) if paths else None
        self._source = source if source is not None else path
        if sources is not None:
            self._sources = list(sources)
        elif paths is not None:
            self._sources = list(paths)
        elif path is not None:
            self._sources = [path]
        else:
            self._sources = None

    def get(self, key, default=None):
        if key == "path":
            return self._path
        if key == "paths":
            return self._paths
        if key == "source":
            return self._source
        if key == "sources":
            return self._sources
        return default

    def get_instance(self, name):
        return None


class _PathOnlyCtx:
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
        file_mod.ThumbnailConfirmDialog,
        "exec",
        lambda self: setattr(self, "result_text", "Cancel"),
    )
    file_mod.delete_files(_Ctx(path=str(p)))
    assert p.exists()


def test_file_commands_strict_source_required():
    logical = build_virtual_path("C:/data/archive.zip", "folder/image.png")

    assert file_mod._ctx_sources(_PathOnlyCtx()) == []
    assert file_mod._ctx_source(_PathOnlyCtx(path=logical)) is None


def test_file_commands_uses_explicit_source():
    assert file_mod._ctx_source(_Ctx(source="C:/data/archive.zip")) == "C:/data/archive.zip"
    assert file_mod._ctx_sources(_Ctx(source="C:/data/archive.zip")) == ["C:/data/archive.zip"]


def test_file_commands_reject_virtual_source():
    logical = build_virtual_path("C:/data/archive.zip", "folder/image.png")

    assert file_mod._ctx_source(_Ctx(source=logical)) is None
    assert file_mod._ctx_sources(_Ctx(sources=[logical])) == []


def test_delete_files_send2trash_failure_falls_back(tmp_path, monkeypatch):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        file_mod.ThumbnailConfirmDialog,
        "exec",
        lambda self: setattr(self, "result_text", "Delete"),
    )
    dummy = SimpleNamespace(send2trash=lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")))
    monkeypatch.setitem(sys.modules, "send2trash", dummy)
    file_mod.delete_files(_Ctx(path=str(p)))
    assert not p.exists()


def test_delete_files_calls_delete_to_trash(tmp_path, monkeypatch):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        file_mod.ThumbnailConfirmDialog,
        "exec",
        lambda self: setattr(self, "result_text", "Delete"),
    )
    from wafer.core.platform.file_operations import OperationResult

    called_with: list = []
    monkeypatch.setattr(
        file_mod,
        "delete_to_trash",
        lambda paths: (called_with.extend(paths), [OperationResult(action="delete", src=str(p), dst="", status="ok")])[1],
    )
    file_mod.delete_files(_Ctx(path=str(p)))
    assert str(p) in called_with


def test_show_in_explorer_ignores_missing_path():
    file_mod.show_in_explorer(_Ctx(path="Z:/__missing__"))


def test_make_new_folder_here_creates_folder(tmp_path):
    folder = file_mod.make_new_folder_here(_Ctx(path=str(tmp_path)))
    assert folder is not None
    assert (tmp_path / get_os_new_folder_name()).exists()


def test_make_new_folder_here_unique_names(tmp_path):
    name = get_os_new_folder_name()
    (tmp_path / name).mkdir()
    folder = file_mod.make_new_folder_here(_Ctx(path=str(tmp_path)))
    assert folder is not None
    assert (tmp_path / f"{name} (2)").exists()


def test_make_new_folder_here_with_file_path(tmp_path):
    file_path = tmp_path / "test.txt"
    file_path.write_text("x", encoding="utf-8")
    folder = file_mod.make_new_folder_here(_Ctx(path=str(file_path)))
    assert folder is not None
    assert (tmp_path / get_os_new_folder_name()).exists()


def test_rename_file_success(tmp_path, monkeypatch):
    f = tmp_path / "old.txt"
    f.write_text("hi", encoding="utf-8")
    from wafer.qt.widgets import dialogs as _dlg_mod

    monkeypatch.setattr(
        _dlg_mod.InputDialog,
        "get_text",
        staticmethod(lambda *a, **k: "new.txt"),
    )
    file_mod.rename_file(_Ctx(path=str(f)))
    assert not f.exists()
    assert (tmp_path / "new.txt").exists()


def test_rename_file_cancel(tmp_path, monkeypatch):
    f = tmp_path / "old.txt"
    f.write_text("hi", encoding="utf-8")
    from wafer.qt.widgets import dialogs as _dlg_mod

    monkeypatch.setattr(
        _dlg_mod.InputDialog,
        "get_text",
        staticmethod(lambda *a, **k: None),
    )
    file_mod.rename_file(_Ctx(path=str(f)))
    assert f.exists()


def test_rename_file_same_name(tmp_path, monkeypatch):
    f = tmp_path / "old.txt"
    f.write_text("hi", encoding="utf-8")
    from wafer.qt.widgets import dialogs as _dlg_mod

    monkeypatch.setattr(
        _dlg_mod.InputDialog,
        "get_text",
        staticmethod(lambda *a, **k: "old.txt"),
    )
    file_mod.rename_file(_Ctx(path=str(f)))
    assert f.exists()


def test_rename_file_conflict(tmp_path, monkeypatch):
    f = tmp_path / "old.txt"
    f.write_text("hi", encoding="utf-8")
    (tmp_path / "taken.txt").write_text("x", encoding="utf-8")
    from wafer.qt.widgets import dialogs as _dlg_mod

    monkeypatch.setattr(
        _dlg_mod.InputDialog,
        "get_text",
        staticmethod(lambda *a, **k: "taken.txt"),
    )
    from wafer.core.platform.file_operations import OperationResult

    monkeypatch.setattr(
        file_mod,
        "execute_paste_plans_with_ui",
        lambda **kw: [OperationResult(action="skip", src=str(f), dst="", status="skipped")],
    )
    file_mod.rename_file(_Ctx(path=str(f)))
    assert f.exists()


def test_rename_file_invalid_name(tmp_path, monkeypatch):
    f = tmp_path / "old.txt"
    f.write_text("hi", encoding="utf-8")
    from wafer.qt.widgets import dialogs as _dlg_mod

    monkeypatch.setattr(
        _dlg_mod.InputDialog,
        "get_text",
        staticmethod(lambda *a, **k: "bad<name>.txt"),
    )
    file_mod.rename_file(_Ctx(path=str(f)))
    assert f.exists()


def test_rename_file_no_path():
    file_mod.rename_file(_Ctx())


def test_make_new_folder_here_custom_name(tmp_path):
    folder = file_mod.make_new_folder_here(_Ctx(path=str(tmp_path)), folder_name="MyFolder")
    assert folder is not None
    assert (tmp_path / "MyFolder").exists()


def test_make_new_folder_here_returns_none_without_path():
    result = file_mod.make_new_folder_here(_Ctx(path=None))
    assert result is None


def test_make_new_folder_here_requires_source(tmp_path):
    result = file_mod.make_new_folder_here(_PathOnlyCtx(path=str(tmp_path)))
    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_paste_here_requires_source(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(file_mod, "paste_clipboard_files", lambda *a, **k: called.append((a, k)))

    file_mod.paste_here(_PathOnlyCtx(path=str(tmp_path)))

    assert called == []


def test_paste_here_rejects_virtual_source(tmp_path, monkeypatch):
    called = []
    logical = build_virtual_path(str(tmp_path / "archive.zip"), "folder/image.png")
    monkeypatch.setattr(file_mod, "paste_clipboard_files", lambda *a, **k: called.append((a, k)))

    file_mod.paste_here(_Ctx(source=logical))

    assert called == []


def test_make_new_folder_here_rejects_virtual_source(tmp_path):
    logical = build_virtual_path(str(tmp_path / "archive.zip"), "folder/image.png")

    assert file_mod.make_new_folder_here(_Ctx(source=logical)) is None
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def option_store(tmp_path):
    from wafer.qt.commands.command.state import CommandOptionStore

    previous_path = CommandOptionStore._default_path
    store = CommandOptionStore.configure(tmp_path / "opts.json")
    FileCommands.register()
    try:
        yield store
    finally:
        CommandOptionStore._default_path = previous_path
        store._reconfigure(previous_path if previous_path is not None else Path(os.devnull))


class _WindowCtx:
    def __init__(self, window):
        self.window = window

    def get(self, key, default=None):
        return default

    def get_instance(self, name):
        return self.window if name == "MainWindow" else None


def test_default_args_only_show_in_viewer(option_store):
    assert Command.get_args("file.open_path") == {"path": "", "select_folder": False, "scroll_grid": False, "show_viewer": True}


def test_open_path_is_in_the_file_menu():
    paths = [getattr(item, "path", None) for item in FileCommands.commands()]
    assert "file.open_path" in paths


def test_open_path_reveals_the_normalized_path():
    window = MagicMock()

    file_mod.open_path(_WindowCtx(window), path="f:\\p\\sub\\a.png", select_folder=True, scroll_grid=True, show_viewer=False)

    window.path_revealer.reveal.assert_called_once_with("F:/p/sub/a.png", select_folder=True, scroll_grid=True, show_viewer=False)


def test_open_path_without_path_asks_for_it(option_store, monkeypatch):
    asked = []
    monkeypatch.setattr(Command, "_show_options_for_required", staticmethod(lambda command_id, *a, **k: asked.append(command_id)))

    Command.invoke("file.open_path")

    assert asked == ["file.open_path"]


def test_open_path_forgets_the_path_but_remembers_the_toggles(option_store, monkeypatch):
    from wafer.qt.commands.command import option_dialog

    class FakeDialog:
        def __init__(self, cls, parent, execute_callback=None, auto_required=False, **kw):
            self.execute_callback = execute_callback

        def exec(self):
            self.execute_callback({"path": "F:/p/a.png", "select_folder": True, "scroll_grid": True, "show_viewer": False})
            return 1

    monkeypatch.setattr(option_dialog, "CommandOptionsDialog", FakeDialog)
    Command.invoke("file.open_path")

    assert Command.get_args("file.open_path") == {"path": "", "select_folder": True, "scroll_grid": True, "show_viewer": False}

    asked = []
    monkeypatch.setattr(Command, "_show_options_for_required", staticmethod(lambda command_id, *a, **k: asked.append(command_id)))
    Command.invoke("file.open_path")

    assert asked == ["file.open_path"]


def test_open_with_is_in_the_file_menu_and_picks_a_file():
    command = next(item for item in FileCommands.commands() if getattr(item, "path", None) == "file.open_with")
    (program,) = command.params
    assert program.name == "program"
    assert program.required
    assert program.widget_type == "file"


def test_open_with_sends_the_selected_sources(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(file_mod, "platform_open_with", lambda program, paths: calls.append((program, paths)) or True)
    a, b = str(tmp_path / "a.png"), str(tmp_path / "b.png")

    file_mod.open_with(_Ctx(path=a, paths=[a, b]), program="C:/apps/editor.exe")

    assert calls == [("C:/apps/editor.exe", [a, b])]


def test_open_with_tells_the_user_when_it_cannot_start(monkeypatch, tmp_path):
    warnings = []
    monkeypatch.setattr(file_mod, "platform_open_with", lambda program, paths: False)
    monkeypatch.setattr(file_mod.Notifier, "warning", staticmethod(lambda message: warnings.append(message)))

    file_mod.open_with(_Ctx(path=str(tmp_path / "a.png")), program="C:/apps/editor.exe")

    assert warnings == ["Could not open with editor.exe"]


def test_open_with_without_program_asks_for_it(option_store, monkeypatch):
    asked = []
    monkeypatch.setattr(Command, "_show_options_for_required", staticmethod(lambda command_id, *a, **k: asked.append(command_id)))

    Command.invoke("file.open_with")

    assert asked == ["file.open_with"]

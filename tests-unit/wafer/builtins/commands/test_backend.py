import pytest
from PySide6 import QtCore, QtWidgets

from wafer.app.webui.settings import HOST_ALL, HOST_LOCAL, LOOPBACK_HOST_NAMES, WebUISettings
from wafer.builtins.commands import backend
from wafer.builtins.commands.backend import BUILTIN_ROLE, AllowedHostsEditor, builtin_host_labels


class NoWindowCtx:
    def get_instance(self, name):
        return None


@pytest.fixture
def settings_path(tmp_path, monkeypatch):
    path = str(tmp_path / "webui_settings.ini")
    monkeypatch.setattr("wafer.app.webui.settings._path", lambda: path)
    return path


def rows(editor):
    return [(editor.list.item(i).text(), bool(editor.list.item(i).data(BUILTIN_ROLE))) for i in range(editor.list.count())]


def type_into_new_row(editor, text):
    editor.add_host()
    item = editor.list.currentItem()
    item.setText(text)
    editor._tidy_rows()
    return item


def run_dialog(monkeypatch, edit):
    shown = {}

    def fake_exec(dialog):
        editor = dialog.findChild(AllowedHostsEditor)
        shown["rows"] = rows(editor)
        edit(dialog, editor)
        save = next(b for b in dialog.findChildren(QtWidgets.QPushButton) if b.text() == "Save")
        save.click()
        return dialog.result()

    monkeypatch.setattr(QtWidgets.QDialog, "exec", fake_exec)
    backend.open_settings(NoWindowCtx())
    return shown


def test_builtin_hosts_follow_the_bind(qtbot):
    editor = AllowedHostsEditor(("nas.example.com",))
    qtbot.addWidget(editor)
    editor.set_builtin(builtin_host_labels(HOST_LOCAL))
    assert rows(editor) == [(name, True) for name in LOOPBACK_HOST_NAMES] + [("nas.example.com", False)]
    editor.set_builtin(builtin_host_labels(HOST_ALL))
    labels = [text for text, builtin in rows(editor) if builtin]
    assert labels[0] == "IP addresses" and "*.ts.net" in labels and "*.local" in labels
    assert rows(editor)[-1] == ("nas.example.com", False)


def test_builtin_rows_cannot_be_edited_or_removed(qtbot):
    editor = AllowedHostsEditor(())
    qtbot.addWidget(editor)
    editor.set_builtin(builtin_host_labels(HOST_ALL))
    builtin = editor.list.item(0)
    assert builtin.flags() == QtCore.Qt.ItemFlag.NoItemFlags
    editor.list.selectAll()
    editor.remove_selected()
    assert editor.list.count() == len(builtin_host_labels(HOST_ALL))
    assert editor.hosts() == ()


def test_rows_are_added_normalized_and_removed(qtbot):
    editor = AllowedHostsEditor(())
    qtbot.addWidget(editor)
    editor.set_builtin(builtin_host_labels(HOST_ALL))
    first = type_into_new_row(editor, "https://NAS.example.com:8443/")
    assert first.text() == "nas.example.com"
    type_into_new_row(editor, "a.example.org, *.home.example.net")
    assert editor.hosts() == ("nas.example.com", "a.example.org", "*.home.example.net")
    editor.list.clearSelection()
    first.setSelected(True)
    editor.remove_selected()
    assert editor.hosts() == ("a.example.org", "*.home.example.net")


def test_empty_rows_disappear_and_invalid_rows_are_flagged(qtbot):
    editor = AllowedHostsEditor(())
    qtbot.addWidget(editor)
    type_into_new_row(editor, "   ")
    assert editor.list.count() == 0
    bad = type_into_new_row(editor, "*.com")
    assert bad.text() == "*.com" and "not saved" in bad.toolTip()
    assert editor.hosts() == ()


def test_settings_dialog_saves_rows(qtbot, settings_path, monkeypatch):
    def edit(dialog, editor):
        dialog.findChild(QtWidgets.QComboBox).setCurrentIndex(1)
        type_into_new_row(editor, "NAS.example.com")
        type_into_new_row(editor, "*.home.example.net")

    run_dialog(monkeypatch, edit)
    settings = WebUISettings()
    assert settings.host() == HOST_ALL
    assert settings.allowed_hosts() == ("nas.example.com", "*.home.example.net")


def test_settings_dialog_shows_builtin_and_saved_rows(qtbot, settings_path, monkeypatch):
    WebUISettings().save(HOST_LOCAL, 8787, ("nas.example.com",))
    shown = run_dialog(monkeypatch, lambda dialog, editor: None)
    assert shown["rows"] == [(name, True) for name in LOOPBACK_HOST_NAMES] + [("nas.example.com", False)]
    assert WebUISettings().allowed_hosts() == ("nas.example.com",)


def test_list_shows_every_row_without_scrolling(qtbot):
    editor = AllowedHostsEditor(("nas.example.com", "*.home.example.net"))
    qtbot.addWidget(editor)
    editor.set_builtin(builtin_host_labels(HOST_ALL))
    editor.show()
    qtbot.waitUntil(editor.isVisible)
    assert editor.list.verticalScrollBar().maximum() == 0
    type_into_new_row(editor, "a.example.org")
    qtbot.waitUntil(lambda: editor.list.verticalScrollBar().maximum() == 0)
    editor.close()


def test_editing_rows_does_not_log_invalid_rows_again(qtbot, monkeypatch):
    logged = []
    monkeypatch.setattr("wafer.app.webui.settings.AppLogger.warning", lambda message, **kwargs: logged.append(message))
    editor = AllowedHostsEditor(())
    qtbot.addWidget(editor)
    type_into_new_row(editor, "bad_host!")
    type_into_new_row(editor, "a.example.org")
    type_into_new_row(editor, "b.example.org")
    assert editor.hosts() == ("a.example.org", "b.example.org")
    assert logged == []

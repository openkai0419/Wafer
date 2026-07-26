import pytest

from PySide6 import QtCore, QtWidgets

from wafer.plugin.key_filter import KeyFilter, MODE_BLACKLIST, MODE_WHITELIST

MODULE = "extensions.exiftool.panel"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    ini = tmp_path / "viewer_plugins.ini"
    monkeypatch.setattr("wafer.plugin.config._ini_path", lambda: str(ini))
    monkeypatch.setattr(KeyFilter, "_broadcast_reload", staticmethod(lambda: None))
    KeyFilter._cache = None
    KeyFilter._subscribers = []
    yield
    KeyFilter._cache = None
    KeyFilter._subscribers = []


def _make_widget(qtbot):
    from extensions.exiftool.panel import ExifSettingsWidget

    w = ExifSettingsWidget()
    qtbot.addWidget(w)
    w._meta = {"Make": "Canon", "Model": "R5"}
    w._current_path = "/a.jpg"
    w._rebuild_table()
    w._rebuild_pending_table()
    w._content_splitter.setVisible(True)
    w._update_drop_label()
    return w


def _row_for(w, key):
    for row in range(w._table.rowCount()):
        if w._table.item(row, 0).data(QtCore.Qt.UserRole) == key:
            return row
    raise AssertionError(f"row not found: {key}")


class TestPendingEdits:
    def test_toggle_accumulates_without_applying(self, qtbot, monkeypatch):
        w = _make_widget(qtbot)
        spy = []
        monkeypatch.setattr(KeyFilter, "set_keys", staticmethod(lambda *a, **k: spy.append(a)))
        row = _row_for(w, "Make")
        w._table.item(row, 0).setCheckState(QtCore.Qt.Unchecked)
        assert w._pending == {"Make": False}
        assert spy == []
        assert w._save_btn.isEnabled()

    def test_toggle_back_to_saved_clears_pending(self, qtbot):
        w = _make_widget(qtbot)
        row = _row_for(w, "Make")
        w._table.item(row, 0).setCheckState(QtCore.Qt.Unchecked)
        w._table.item(_row_for(w, "Make"), 0).setCheckState(QtCore.Qt.Checked)
        assert w._pending == {}
        assert not w._save_btn.isEnabled()

    def test_effective_enabled_reflects_pending(self, qtbot):
        w = _make_widget(qtbot)
        w._pending = {"Make": False}
        assert w._effective_enabled("Make") is False
        assert w._effective_enabled("Model") is True


class TestPendingTable:
    def test_shown_when_image_loaded(self, qtbot):
        w = _make_widget(qtbot)
        assert w._pending_group.isHidden() is False
        assert w._pending_table.rowCount() == 0
        assert w._pending_group.title() == "Edited keys (0)"

    def test_uses_splitter_layout(self, qtbot):
        w = _make_widget(qtbot)
        assert w._content_splitter.count() == 2
        assert w._details_splitter.count() == 2
        assert w._content_splitter.orientation() == QtCore.Qt.Vertical
        assert w._details_splitter.orientation() == QtCore.Qt.Horizontal

    def test_shows_edited_keys(self, qtbot):
        w = _make_widget(qtbot)
        row = _row_for(w, "Make")
        w._table.item(row, 0).setCheckState(QtCore.Qt.Unchecked)
        assert w._pending_table.rowCount() == 1
        assert w._pending_table.item(0, 0).text() == "Make"
        assert w._pending_group.title() == "Edited keys (1)"

    def test_persists_across_image_load(self, qtbot):
        w = _make_widget(qtbot)
        row = _row_for(w, "Make")
        w._table.item(row, 0).setCheckState(QtCore.Qt.Unchecked)
        w._meta = {"GPS": "1,2", "Lens": "50mm"}
        w._rebuild_table()
        assert "Make" not in [w._table.item(r, 0).data(QtCore.Qt.UserRole) for r in range(w._table.rowCount())]
        assert w._pending_table.item(0, 0).text() == "Make"
        assert w._pending == {"Make": False}
        assert "1 edited" in w._drop_label.text()

    def test_remove_pending_reverts_single_key(self, qtbot):
        w = _make_widget(qtbot)
        w._pending = {"Make": False, "Model": False}
        w._rebuild_pending_table()
        w._remove_pending("Make")
        assert w._pending == {"Model": False}
        assert w._pending_table.rowCount() == 1
        assert KeyFilter.is_enabled("exiftool", "Make") is True


class TestSaveRevert:
    def test_revert_clears_pending(self, qtbot):
        w = _make_widget(qtbot)
        row = _row_for(w, "Make")
        w._table.item(row, 0).setCheckState(QtCore.Qt.Unchecked)
        w._on_revert()
        assert w._pending == {}
        assert KeyFilter.is_enabled("exiftool", "Make") is True

    def test_save_applies_pending(self, qtbot, monkeypatch):
        w = _make_widget(qtbot)

        class _Dlg:
            def __init__(self, *a, **k):
                pass

            def exec(self):
                return QtWidgets.QDialog.Accepted

            def delete_data(self):
                return False

            def recollect(self):
                return False

        monkeypatch.setattr(f"{MODULE}.FilterSaveConfirmDialog", _Dlg)
        monkeypatch.setattr(f"{MODULE}.list_setting_db_names", lambda: [])
        w._pending = {"Make": False}
        w._on_save()
        assert w._pending == {}
        assert KeyFilter.get("exiftool") == (MODE_BLACKLIST, frozenset({"Make"}))

    def test_save_cancel_keeps_pending(self, qtbot, monkeypatch):
        w = _make_widget(qtbot)

        class _Dlg:
            def __init__(self, *a, **k):
                pass

            def exec(self):
                return QtWidgets.QDialog.Rejected

            def delete_data(self):
                return False

            def recollect(self):
                return False

        monkeypatch.setattr(f"{MODULE}.FilterSaveConfirmDialog", _Dlg)
        w._pending = {"Make": False}
        w._on_save()
        assert w._pending == {"Make": False}
        assert KeyFilter.is_enabled("exiftool", "Make") is True


def _accept_dlg(delete=True, recollect=False):
    class _Dlg:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return QtWidgets.QDialog.Accepted

        def delete_data(self):
            return delete

        def recollect(self):
            return recollect

    return _Dlg


class TestSaveDeleteKeys:
    def _capture(self, monkeypatch, delete=True):
        sent = []
        monkeypatch.setattr(f"{MODULE}.FilterSaveConfirmDialog", _accept_dlg(delete=delete))
        monkeypatch.setattr(f"{MODULE}.list_setting_db_names", lambda: ["db1"])
        monkeypatch.setattr(
            f"{MODULE}.Recollect",
            type("R", (), {"purge": staticmethod(lambda *, db_scope, collector, keys, delete, re_collect: sent.append(list(keys)))}),
        )
        return sent

    def test_deletes_only_disabled_pending(self, qtbot, monkeypatch):
        w = _make_widget(qtbot)
        sent = self._capture(monkeypatch)
        w._pending = {"Make": False, "Model": True}
        w._on_save()
        assert sent == [["exiftool.Make"]]

    def test_whitelist_disabled_key_is_deleted(self, qtbot, monkeypatch):
        KeyFilter.set_keys("exiftool", MODE_WHITELIST, {"Make", "Model"})
        w = _make_widget(qtbot)
        sent = self._capture(monkeypatch)
        w._pending = {"Make": False}
        w._on_save()
        assert sent == [["exiftool.Make"]]

    def test_no_delete_keys_when_delete_unchecked(self, qtbot, monkeypatch):
        w = _make_widget(qtbot)
        sent = self._capture(monkeypatch, delete=False)
        w._pending = {"Make": False}
        w._on_save()
        assert sent == []

import pytest
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

from PySide6 import QtWidgets, QtCore

from wafer.core.qt.dispatcher import Dispatcher, CancelSlot


MODULE = "wafer.builtins.database_manager.data_tab"

SAMPLE_ROWS = [
    ("db1", "exif", 100, 50, "Collector", "Active", True),
    ("db1", "wd14", 200, 80, "Collector", "Disabled", True),
    ("db2", "exif", 300, 120, "Collector", "Active", True),
]

MIXED_ROWS = [
    ("db1", "exif", 100, 50, "Collector", "Active", True),
    ("db1", "nai", 30, 10, "Parser", "Active", True),
    ("db2", "exif", 300, 120, "Collector", "Active", True),
]


class _SyncDispatcher(Dispatcher):
    def __init__(self):
        self._signals = type("S", (), {"_to_main": type("Sig", (), {"connect": lambda *a: None, "emit": lambda self, fn: fn()})()})()
        self._pool = None

    def post(self, fn, priority=5, cancel=None):
        fn()

    def invoke(self, fn):
        fn()


@pytest.fixture
def sync_dispatcher():
    return _SyncDispatcher()


@pytest.fixture
def _patch_data_tab(tmp_path):
    with (
        patch(f"{MODULE}.list_setting_db_names", return_value=[]),
        patch(f"{MODULE}._build_rows", return_value=[]),
        patch(f"{MODULE}.themed_icon", return_value=QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_BrowserReload)),
    ):
        yield


def _make_tab(qtbot, sync_dispatcher, rows=None):
    if rows is None:
        rows = []
    with (
        patch(f"{MODULE}.list_setting_db_names", return_value=["db1"]),
        patch(f"{MODULE}._build_rows", return_value=rows),
        patch(f"{MODULE}.themed_icon", return_value=QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_BrowserReload)),
        patch("wafer.app.viewer.ipc_bridge.ViewerIpcBridge.instance", return_value=None),
    ):
        from wafer.builtins.database_manager.data_tab import DataTab

        tab = DataTab(sync_dispatcher)
        qtbot.addWidget(tab)
        return tab


class TestDataTabInit:
    def test_creates_with_empty_rows(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, [])
        assert tab._collector_table.table.rowCount() == 0
        assert tab._parser_table.table.rowCount() == 0
        assert tab._initial_loaded is True

    def test_primary_action_uses_apply_label(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, [])
        assert tab._save_btn.text() == "Apply"

    def test_creates_with_sample_rows(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        assert tab._collector_table.table.rowCount() == 3
        assert tab._parser_table.table.rowCount() == 0
        assert tab._initial_loaded is True

    def test_creates_with_mixed_rows(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, MIXED_ROWS)
        assert tab._collector_table.table.rowCount() == 2
        assert tab._parser_table.table.rowCount() == 1

    def test_has_two_cancel_slots(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, [])
        assert isinstance(tab._load_cancel, CancelSlot)
        assert isinstance(tab._poll_cancel, CancelSlot)
        assert tab._load_cancel is not tab._poll_cancel


class TestApplyRows:
    def test_populates_collector_table(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        t = tab._collector_table.table
        assert t.item(0, 0).text() == "db1"
        assert t.item(0, 1).text() == "exif"
        assert t.item(0, 2).text() == "100"
        assert t.item(0, 3).text() == "50"
        assert t.item(0, 4).text() == "Active"

    def test_populates_parser_table(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, MIXED_ROWS)
        t = tab._parser_table.table
        assert t.item(0, 0).text() == "db1"
        assert t.item(0, 1).text() == "nai"
        assert t.item(0, 2).text() == "30"
        assert t.item(0, 3).text() == "10"
        assert t.item(0, 4).text() == "Active"

    def test_deletable_row_has_checkbox(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        del_container = tab._collector_table.table.cellWidget(0, 5)
        rec_container = tab._collector_table.table.cellWidget(0, 6)
        assert del_container is not None
        assert rec_container is not None
        assert del_container.findChild(QtWidgets.QCheckBox) is not None
        assert rec_container.findChild(QtWidgets.QCheckBox) is not None

    def test_recollect_disabled_for_non_active_row(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        active_rec = tab._collector_table.table.cellWidget(0, 6).findChild(QtWidgets.QCheckBox)
        disabled_rec = tab._collector_table.table.cellWidget(1, 6).findChild(QtWidgets.QCheckBox)
        disabled_del = tab._collector_table.table.cellWidget(1, 5).findChild(QtWidgets.QCheckBox)
        assert active_rec.isEnabled()
        assert not disabled_rec.isEnabled()
        assert disabled_del.isEnabled()

    def test_non_deletable_row_has_no_checkbox(self, qtbot, sync_dispatcher):
        rows = [("db1", "test", 10, 5, "", "", False)]
        tab = _make_tab(qtbot, sync_dispatcher, rows)
        assert tab._collector_table.table.cellWidget(0, 5) is None
        assert tab._collector_table.table.cellWidget(0, 6) is None

    def test_parser_row_has_recollect_checkbox(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, MIXED_ROWS)
        rec_container = tab._parser_table.table.cellWidget(0, 6)
        assert rec_container is not None
        assert rec_container.findChild(QtWidgets.QCheckBox) is not None

    def test_reapply_clears_checkbox_on_non_deletable_row(self, qtbot, sync_dispatcher):
        rows_with_prefix = [
            ("db1", "exif", 100, 50, "Collector", "Active", True),
        ]
        tab = _make_tab(qtbot, sync_dispatcher, rows_with_prefix)
        assert tab._collector_table.table.cellWidget(0, 5) is not None

        from wafer.builtins.database_manager.data_tab import _split_rows

        rows_without_prefix = [
            ("db1", "", 100, 50, "", "", False),
        ]
        c_rows, _ = _split_rows(rows_without_prefix)
        tab._collector_table.apply_rows(c_rows)
        assert tab._collector_table.table.cellWidget(0, 5) is None


class TestOnLoaded:
    def test_sets_initial_loaded(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, [])
        assert tab._initial_loaded is True


class TestShowHideEvent:
    def test_show_with_dirty_flag_triggers_poll(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._dirty = True
        new_rows = [("db1", "exif", 999, 999, "Collector", "Active", True)]
        with patch(f"{MODULE}.list_setting_db_names", return_value=["db1"]), patch(f"{MODULE}._build_rows", return_value=new_rows):
            tab.show()
        assert tab._dirty is False

    def test_show_without_dirty_does_not_poll(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._dirty = False
        assert tab._collector_table.table.rowCount() == 3
        tab.show()
        assert tab._collector_table.table.rowCount() == 3


class TestRefresh:
    def test_refresh_reloads_data(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        assert tab._collector_table.table.rowCount() == 3
        new_rows = [("db1", "exif", 150, 60, "Collector", "Active", True)]
        with patch(f"{MODULE}.list_setting_db_names", return_value=["db1"]), patch(f"{MODULE}._build_rows", return_value=new_rows):
            tab.refresh()
        assert tab._collector_table.table.rowCount() == 1
        assert tab._collector_table.table.item(0, 2).text() == "150"


class TestPoll:
    def test_poll_uses_poll_cancel(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        old_load_token = tab._load_cancel._token
        with patch(f"{MODULE}.list_setting_db_names", return_value=["db1"]), patch(f"{MODULE}._build_rows", return_value=SAMPLE_ROWS):
            tab._poll()
        assert tab._load_cancel._token is old_load_token


class TestMergeRows:
    def test_merge_updates_counts_without_full_rebuild(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        updated = [
            ("db1", "exif", 150, 60, "Collector", "Active", True),
            ("db1", "wd14", 250, 90, "Collector", "Disabled", True),
            ("db2", "exif", 350, 130, "Collector", "Active", True),
        ]
        tab._merge_rows(updated)
        assert tab._collector_table.table.item(0, 2).text() == "150"
        assert tab._collector_table.table.item(1, 2).text() == "250"
        assert tab._raw_rows == updated

    def test_merge_with_new_prefix_triggers_full_apply(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        changed = [
            ("db1", "exif", 100, 50, "Collector", "Active", True),
            ("db1", "new_prefix", 10, 5, "Parser", "Active", True),
        ]
        tab._merge_rows(changed)
        assert tab._collector_table.table.rowCount() == 1
        assert tab._parser_table.table.rowCount() == 1

    def test_merge_mixed_rows(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, MIXED_ROWS)
        updated = [
            ("db1", "exif", 200, 70, "Collector", "Active", True),
            ("db1", "nai", 50, 20, "Parser", "Active", True),
            ("db2", "exif", 400, 150, "Collector", "Active", True),
        ]
        tab._merge_rows(updated)
        assert tab._collector_table.table.item(0, 2).text() == "200"
        assert tab._parser_table.table.item(0, 2).text() == "50"


class TestStateResync:
    def test_refresh_resets_summary_and_button(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._collector_table.table.cellWidget(0, 5).findChild(QtWidgets.QCheckBox).setChecked(True)
        assert tab._save_btn.isEnabled()
        empty_rows = [("db1", "", 0, 0, "", "", False)]
        with patch(f"{MODULE}.list_setting_db_names", return_value=["db1"]), patch(f"{MODULE}._build_rows", return_value=empty_rows):
            tab.refresh()
        assert "Delete: 0" in tab._summary_label.text()
        assert "Recollect: 0" in tab._summary_label.text()
        assert not tab._save_btn.isEnabled()
        assert tab._collector_table.get_actions() == []

    def test_merge_disables_and_unchecks_recollect_on_deactivate(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._collector_table.table.cellWidget(0, 6).findChild(QtWidgets.QCheckBox).setChecked(True)
        assert "Recollect: 1" in tab._summary_label.text()
        deactivated = [
            ("db1", "exif", 100, 50, "Collector", "Disabled", True),
            ("db1", "wd14", 200, 80, "Collector", "Disabled", True),
            ("db2", "exif", 300, 120, "Collector", "Active", True),
        ]
        tab._merge_rows(deactivated)
        rec_cb = tab._collector_table.table.cellWidget(0, 6).findChild(QtWidgets.QCheckBox)
        assert not rec_cb.isEnabled()
        assert not rec_cb.isChecked()
        assert "Recollect: 0" in tab._summary_label.text()
        assert not tab._save_btn.isEnabled()

    def test_merge_enables_recollect_on_activate(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        disabled_rec = tab._collector_table.table.cellWidget(1, 6).findChild(QtWidgets.QCheckBox)
        assert not disabled_rec.isEnabled()
        activated = [
            ("db1", "exif", 100, 50, "Collector", "Active", True),
            ("db1", "wd14", 200, 80, "Collector", "Active", True),
            ("db2", "exif", 300, 120, "Collector", "Active", True),
        ]
        tab._merge_rows(activated)
        rec_cb = tab._collector_table.table.cellWidget(1, 6).findChild(QtWidgets.QCheckBox)
        assert rec_cb.isEnabled()


class TestSummary:
    def test_summary_updates_on_delete_check(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._collector_table.table.cellWidget(0, 5).findChild(QtWidgets.QCheckBox).setChecked(True)
        assert "Delete: 1" in tab._summary_label.text()
        assert tab._save_btn.isEnabled()

    def test_summary_updates_on_recollect_check(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._collector_table.table.cellWidget(0, 6).findChild(QtWidgets.QCheckBox).setChecked(True)
        assert "Recollect: 1" in tab._summary_label.text()
        assert tab._save_btn.isEnabled()

    def test_save_disabled_when_nothing_checked(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        assert not tab._save_btn.isEnabled()

    def test_counts_across_tables(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, MIXED_ROWS)
        tab._collector_table.table.cellWidget(0, 5).findChild(QtWidgets.QCheckBox).setChecked(True)
        tab._parser_table.table.cellWidget(0, 6).findChild(QtWidgets.QCheckBox).setChecked(True)
        assert "Delete: 1" in tab._summary_label.text()
        assert "Recollect: 1" in tab._summary_label.text()


class TestGetActions:
    def test_delete_only(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._collector_table.table.cellWidget(0, 5).findChild(QtWidgets.QCheckBox).setChecked(True)
        assert tab._collector_table.get_actions() == [("db1", "exif", True, False)]

    def test_recollect_only(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._collector_table.table.cellWidget(0, 6).findChild(QtWidgets.QCheckBox).setChecked(True)
        assert tab._collector_table.get_actions() == [("db1", "exif", False, True)]

    def test_delete_and_recollect(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._collector_table.table.cellWidget(0, 5).findChild(QtWidgets.QCheckBox).setChecked(True)
        tab._collector_table.table.cellWidget(0, 6).findChild(QtWidgets.QCheckBox).setChecked(True)
        assert tab._collector_table.get_actions() == [("db1", "exif", True, True)]

    def test_parser_recollect_action(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, MIXED_ROWS)
        tab._parser_table.table.cellWidget(0, 6).findChild(QtWidgets.QCheckBox).setChecked(True)
        assert tab._parser_table.get_actions() == [("db1", "nai", False, True)]

    def test_unchecked_rows_excluded(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        assert tab._collector_table.get_actions() == []


class TestSaveRevert:
    def test_save_emits_actions_and_keeps_checks(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._collector_table.table.cellWidget(0, 5).findChild(QtWidgets.QCheckBox).setChecked(True)
        tab._collector_table.table.cellWidget(2, 6).findChild(QtWidgets.QCheckBox).setChecked(True)
        received = []
        tab.apply_requested.connect(received.append)
        with patch(f"{MODULE}._ApplyConfirmDialog") as dlg_cls:
            dlg_cls.return_value.exec.return_value = QtWidgets.QDialog.Accepted
            tab._on_save()
        assert len(received) == 1
        assert ("db1", "exif", True, False) in received[0]
        assert ("db2", "exif", False, True) in received[0]
        assert tab._collector_table.get_actions() != []

    def test_save_cancelled_does_not_emit(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._collector_table.table.cellWidget(0, 5).findChild(QtWidgets.QCheckBox).setChecked(True)
        received = []
        tab.apply_requested.connect(received.append)
        with patch(f"{MODULE}._ApplyConfirmDialog") as dlg_cls:
            dlg_cls.return_value.exec.return_value = QtWidgets.QDialog.Rejected
            tab._on_save()
        assert received == []
        assert tab._collector_table.get_actions() == [("db1", "exif", True, False)]

    def test_save_nothing_checked_no_emit(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        received = []
        tab.apply_requested.connect(received.append)
        tab._on_save()
        assert received == []

    def test_clear_checks_resets_all(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._collector_table.table.cellWidget(0, 5).findChild(QtWidgets.QCheckBox).setChecked(True)
        tab._collector_table.table.cellWidget(0, 6).findChild(QtWidgets.QCheckBox).setChecked(True)
        tab.clear_checks()
        assert tab._collector_table.get_actions() == []
        assert not tab._save_btn.isEnabled()

    def test_revert_clears_checks(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._collector_table.table.cellWidget(0, 5).findChild(QtWidgets.QCheckBox).setChecked(True)
        tab._collector_table.table.cellWidget(0, 6).findChild(QtWidgets.QCheckBox).setChecked(True)
        tab._on_revert()
        assert tab._collector_table.get_actions() == []
        assert not tab._save_btn.isEnabled()


class TestRefreshButton:
    def test_refresh_button_exists(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, [])
        assert tab._refresh_btn is not None
        assert tab._refresh_btn.toolTip() == "Refresh"

    def test_refresh_button_triggers_reload(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        new_rows = [("db1", "exif", 999, 999, "Collector", "Active", True)]
        with patch(f"{MODULE}.list_setting_db_names", return_value=["db1"]), patch(f"{MODULE}._build_rows", return_value=new_rows):
            tab._refresh_btn.click()
        assert tab._collector_table.table.rowCount() == 1
        assert tab._collector_table.table.item(0, 2).text() == "999"

    def test_refresh_button_re_enabled_after_load(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        assert tab._refresh_btn.isEnabled()
        with patch(f"{MODULE}.list_setting_db_names", return_value=["db1"]), patch(f"{MODULE}._build_rows", return_value=SAMPLE_ROWS):
            tab.refresh()
        assert tab._refresh_btn.isEnabled()
        assert tab._refresh_btn.toolTip() == "Refresh"


class TestRefreshCancelsPoll:
    def test_refresh_cancels_poll_token(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        with patch(f"{MODULE}.list_setting_db_names", return_value=["db1"]), patch(f"{MODULE}._build_rows", return_value=SAMPLE_ROWS):
            tab._poll()
        poll_token = tab._poll_cancel._token
        assert poll_token is not None
        with patch(f"{MODULE}.list_setting_db_names", return_value=["db1"]), patch(f"{MODULE}._build_rows", return_value=SAMPLE_ROWS):
            tab.refresh()
        assert poll_token.is_cancelled()

    def test_refresh_stops_debounce_timer(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        tab._debounce_timer.start()
        assert tab._debounce_timer.isActive()
        with patch(f"{MODULE}.list_setting_db_names", return_value=["db1"]), patch(f"{MODULE}._build_rows", return_value=SAMPLE_ROWS):
            tab.refresh()
        assert not tab._debounce_timer.isActive()

    def test_refresh_reloads_data_after_debounce(self, qtbot, sync_dispatcher):
        tab = _make_tab(qtbot, sync_dispatcher, SAMPLE_ROWS)
        new_rows = [("db1", "exif", 999, 999, "Collector", "Active", True)]
        with patch(f"{MODULE}.list_setting_db_names", return_value=["db1"]), patch(f"{MODULE}._build_rows", return_value=new_rows):
            tab.refresh()
        assert tab._collector_table.table.item(0, 2).text() == "999"


class TestSplitRows:
    def test_split_collectors_only(self):
        from wafer.builtins.database_manager.data_tab import _split_rows

        c, d = _split_rows(SAMPLE_ROWS)
        assert len(c) == 3
        assert len(d) == 0

    def test_split_mixed(self):
        from wafer.builtins.database_manager.data_tab import _split_rows

        c, d = _split_rows(MIXED_ROWS)
        assert len(c) == 2
        assert len(d) == 1
        assert d[0][1] == "nai"

    def test_unknown_type_goes_to_collectors(self):
        from wafer.builtins.database_manager.data_tab import _split_rows

        rows = [("db1", "unknown", 10, 5, "", "", True)]
        c, d = _split_rows(rows)
        assert len(c) == 1
        assert len(d) == 0


class TestQueryPrefixSummary:
    def test_reads_prefix_data_from_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, source TEXT, name TEXT, file_hash TEXT, aspect REAL)")
        conn.execute("CREATE TABLE IF NOT EXISTS meta_info (path TEXT, key TEXT, value TEXT, PRIMARY KEY (path, key))")
        conn.execute("CREATE TABLE IF NOT EXISTS tags (file_hash TEXT, key TEXT, value TEXT, PRIMARY KEY (file_hash, key))")
        conn.execute("INSERT INTO meta_info VALUES ('a.jpg', 'exif.width', '100')")
        conn.execute("INSERT INTO meta_info VALUES ('a.jpg', 'exif.height', '200')")
        conn.execute("INSERT INTO tags VALUES ('hash1', 'wd14.cat', '0.9')")
        conn.commit()
        conn.close()

        from wafer.builtins.database_manager.data_tab import _query_prefix_summary

        result = _query_prefix_summary(db_path)
        result_dict = {r[0]: (r[1], r[2]) for r in result}
        assert result_dict["exif"] == (2, 0)
        assert result_dict["wd14"] == (0, 1)

    def test_readonly_does_not_block_writer(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS meta_info (path TEXT, key TEXT, value TEXT, PRIMARY KEY (path, key))")
        conn.execute("CREATE TABLE IF NOT EXISTS tags (file_hash TEXT, key TEXT, value TEXT, PRIMARY KEY (file_hash, key))")
        conn.commit()

        from wafer.builtins.database_manager.data_tab import _query_prefix_summary

        result = _query_prefix_summary(db_path)
        assert result == []
        conn.execute("INSERT INTO meta_info VALUES ('b.jpg', 'img.size', '500')")
        conn.commit()
        conn.close()

        result = _query_prefix_summary(db_path)
        assert len(result) == 1

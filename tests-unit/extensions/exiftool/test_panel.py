from unittest.mock import patch, MagicMock

import pytest
from PySide6 import QtWidgets, QtCore

from extensions.exiftool.settings import MODE_BLACKLIST, MODE_WHITELIST

MODULE = "extensions.exiftool.panel"


@pytest.fixture()
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _make_key_browser(qapp, mode, filter_keys, key_data=None):
    from extensions.exiftool.panel import _KeyBrowserTab
    from wafer.core.qt.dispatcher import CancelSlot

    mock_dispatcher = MagicMock()
    with patch(f"{MODULE}._query_all_keys_merged", return_value=[]), \
         patch(f"{MODULE}.dpix", side_effect=lambda x: x):
        tab = _KeyBrowserTab(mode, filter_keys, mock_dispatcher, CancelSlot())
    if key_data is not None:
        tab._key_data = key_data
    return tab


def _make_sample_preview(qapp, mode, filter_keys):
    from extensions.exiftool.panel import _SamplePreviewTab
    from wafer.core.qt.dispatcher import CancelSlot

    mock_dispatcher = MagicMock()
    with patch(f"{MODULE}.dpix", side_effect=lambda x: x):
        tab = _SamplePreviewTab(mode, filter_keys, mock_dispatcher, CancelSlot())
    return tab


class TestCheckHeaderInversion:
    def test_blacklist_header_is_block(self, qapp):
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set())
        assert tab._check_header() == "Block"

    def test_whitelist_header_is_use(self, qapp):
        tab = _make_key_browser(qapp, MODE_WHITELIST, set())
        assert tab._check_header() == "Use"

    def test_sample_preview_blacklist_header_is_block(self, qapp):
        tab = _make_sample_preview(qapp, MODE_BLACKLIST, set())
        assert tab._check_header() == "Block"

    def test_sample_preview_whitelist_header_is_use(self, qapp):
        tab = _make_sample_preview(qapp, MODE_WHITELIST, set())
        assert tab._check_header() == "Use"


class TestMakeLeafItemCheckState:
    def test_key_in_filter_keys_is_checked(self, qapp):
        tab = _make_key_browser(qapp, MODE_BLACKLIST, {"alpha"})
        item = tab._make_leaf_item("alpha", 10, "alpha")
        assert item.checkState(0) == QtCore.Qt.Checked

    def test_key_not_in_filter_keys_is_unchecked(self, qapp):
        tab = _make_key_browser(qapp, MODE_BLACKLIST, {"alpha"})
        item = tab._make_leaf_item("beta", 5, "beta")
        assert item.checkState(0) == QtCore.Qt.Unchecked


class TestCollectFilterKeys:
    def test_collects_checked_items(self, qapp):
        keys = {"alpha", "gamma"}
        key_data = [("alpha", 10), ("beta", 5), ("gamma", 3)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, keys, key_data=key_data)
        tab._build_tree()
        result = tab.collect_filter_keys()
        assert result == {"alpha", "gamma"}

    def test_empty_when_nothing_checked(self, qapp):
        key_data = [("alpha", 10), ("beta", 5)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        tab._build_tree()
        result = tab.collect_filter_keys()
        assert result == set()

    def test_all_collected_when_all_checked(self, qapp):
        keys = {"alpha", "beta"}
        key_data = [("alpha", 10), ("beta", 5)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, keys, key_data=key_data)
        tab._build_tree()
        result = tab.collect_filter_keys()
        assert result == {"alpha", "beta"}


class TestCheckAllToggle:
    def test_check_all_when_none_checked(self, qapp):
        key_data = [("a", 1), ("b", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        tab._on_check_all()
        assert tab._filter_keys == {"a", "b"}

    def test_uncheck_all_when_all_checked(self, qapp):
        key_data = [("a", 1), ("b", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, {"a", "b"}, key_data=key_data)
        tab._on_check_all()
        assert tab._filter_keys == set()

    def test_check_all_when_partially_checked(self, qapp):
        key_data = [("a", 1), ("b", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, {"a"}, key_data=key_data)
        tab._on_check_all()
        assert tab._filter_keys == {"a", "b"}

    def test_check_all_respects_visible_filtered_keys(self, qapp):
        key_data = [("alpha", 1), ("beta", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        tab._build_tree()
        tab._search.setText("alp")
        tab._on_check_all()
        assert tab._filter_keys == {"alpha"}

    def test_uncheck_all_respects_visible_filtered_keys(self, qapp):
        key_data = [("alpha", 1), ("beta", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, {"alpha", "beta"}, key_data=key_data)
        tab._build_tree()
        tab._search.setText("alp")
        tab._on_check_all()
        assert tab._filter_keys == {"beta"}


class TestUpdateCheckAllLabel:
    def test_label_uncheck_all_when_all_checked(self, qapp):
        key_data = [("a", 1), ("b", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, {"a", "b"}, key_data=key_data)
        tab._update_check_all_label()
        assert tab._check_all_btn.text() == "Uncheck All"

    def test_label_check_all_when_none_checked(self, qapp):
        key_data = [("a", 1), ("b", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        tab._update_check_all_label()
        assert tab._check_all_btn.text() == "Check All"

    def test_toggle_updates_label(self, qapp):
        key_data = [("a", 1), ("b", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        tab._on_check_all()
        assert tab._check_all_btn.text() == "Uncheck All"
        tab._on_check_all()
        assert tab._check_all_btn.text() == "Check All"

    def test_label_uses_visible_filtered_keys(self, qapp):
        key_data = [("alpha", 1), ("beta", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, {"alpha"}, key_data=key_data)
        tab._build_tree()
        tab._search.setText("alp")
        tab._update_check_all_label()
        assert tab._check_all_btn.text() == "Uncheck All"


class TestKeyBrowserFilterKeysChangedSignal:
    def test_check_all_emits_signal(self, qapp):
        key_data = [("a", 1), ("b", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        received = []
        tab.filter_keys_changed.connect(lambda keys: received.append(keys))
        tab._on_check_all()
        assert len(received) == 1
        assert received[0] == {"a", "b"}

    def test_uncheck_all_emits_signal(self, qapp):
        key_data = [("a", 1), ("b", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, {"a", "b"}, key_data=key_data)
        received = []
        tab.filter_keys_changed.connect(lambda keys: received.append(keys))
        tab._on_check_all()
        assert len(received) == 1
        assert received[0] == set()

    def test_item_click_check_emits_signal(self, qapp):
        key_data = [("a", 1), ("b", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        tab._build_tree()
        item_a = _find_leaf_by_key(tab._tree, "a")
        tab._pre_click_selection = [item_a]
        item_a.setCheckState(0, QtCore.Qt.Checked)
        received = []
        tab.filter_keys_changed.connect(lambda keys: received.append(keys))
        tab._on_item_clicked(item_a, 0)
        assert len(received) == 1
        assert "a" in received[0]

    def test_item_click_non_check_column_no_signal(self, qapp):
        key_data = [("a", 1)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        tab._build_tree()
        item_a = _find_leaf_by_key(tab._tree, "a")
        received = []
        tab.filter_keys_changed.connect(lambda keys: received.append(keys))
        tab._cancel.renew()
        tab._on_item_clicked(item_a, 1)
        assert len(received) == 0


class TestBrowserToPreviewPropagation:
    def test_check_all_propagates_to_sample_preview(self, qapp):
        widget = _make_exiftool_settings_widget(qapp)
        kb = widget._key_browser
        sp = widget._sample_preview
        kb._key_data = [("a", 1), ("b", 2)]
        sp._meta = {"a": "v1", "b": "v2"}
        sp._filter_keys = set()
        kb._on_check_all()
        assert sp._filter_keys == {"a", "b"}

    def test_uncheck_all_propagates_to_sample_preview(self, qapp):
        widget = _make_exiftool_settings_widget(qapp)
        kb = widget._key_browser
        sp = widget._sample_preview
        kb._key_data = [("a", 1), ("b", 2)]
        kb._filter_keys = {"a", "b"}
        sp._meta = {"a": "v1", "b": "v2"}
        sp._filter_keys = {"a", "b"}
        kb._on_check_all()
        assert sp._filter_keys == set()


class TestSamplePreviewCellChanged:
    def test_check_adds_to_filter_keys(self, qapp):
        tab = _make_sample_preview(qapp, MODE_BLACKLIST, set())
        tab._table.blockSignals(True)
        tab._table.setRowCount(1)
        item = QtWidgets.QTableWidgetItem()
        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
        item.setCheckState(QtCore.Qt.Checked)
        item.setData(QtCore.Qt.UserRole, "test_key")
        tab._table.setItem(0, 0, item)
        tab._table.blockSignals(False)
        tab._meta = {"test_key": "val"}
        with patch.object(tab, "_rebuild_table"), \
             patch.object(tab, "_update_drop_label"):
            tab._on_cell_changed(0, 0)
        assert "test_key" in tab._filter_keys

    def test_uncheck_removes_from_filter_keys(self, qapp):
        tab = _make_sample_preview(qapp, MODE_BLACKLIST, {"test_key"})
        tab._table.blockSignals(True)
        tab._table.setRowCount(1)
        item = QtWidgets.QTableWidgetItem()
        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
        item.setCheckState(QtCore.Qt.Unchecked)
        item.setData(QtCore.Qt.UserRole, "test_key")
        tab._table.setItem(0, 0, item)
        tab._table.blockSignals(False)
        tab._meta = {"test_key": "val"}
        with patch.object(tab, "_rebuild_table"), \
             patch.object(tab, "_update_drop_label"):
            tab._on_cell_changed(0, 0)
        assert "test_key" not in tab._filter_keys


class TestSaveConfirmDialog:
    def test_dialog_label_mentions_all_databases(self, qapp):
        from extensions.exiftool.panel import _SaveConfirmDialog

        with patch(f"{MODULE}.dpix", side_effect=lambda x: x):
            dlg = _SaveConfirmDialog()
        labels = dlg.findChildren(QtWidgets.QLabel)
        texts = [lb.text() for lb in labels]
        assert any("all databases" in t.lower() for t in texts)

    def test_dialog_label_mentions_modified(self, qapp):
        from extensions.exiftool.panel import _SaveConfirmDialog

        with patch(f"{MODULE}.dpix", side_effect=lambda x: x):
            dlg = _SaveConfirmDialog()
        labels = dlg.findChildren(QtWidgets.QLabel)
        texts = [lb.text() for lb in labels]
        assert any("modified" in t.lower() for t in texts)


def _make_exiftool_settings_widget(qapp):
    from extensions.exiftool.panel import ExifSettingsWidget

    mock_bridge = MagicMock()
    with patch("extensions.exiftool.settings.read_filter_config", return_value=(MODE_BLACKLIST, set())), \
         patch(f"{MODULE}.list_setting_db_names", return_value=[]), \
         patch(f"{MODULE}.dpix", side_effect=lambda x: x), \
         patch(f"{MODULE}.Dispatcher"), \
         patch(f"{MODULE}.CancelSlot"), \
         patch("wafer.app.viewer.ipc_bridge.ViewerIpcBridge.instance", return_value=mock_bridge):
        widget = ExifSettingsWidget()
    return widget


class TestSaveButtonText:
    def test_save_button_text_all_dbs(self, qapp):
        widget = _make_exiftool_settings_widget(qapp)
        buttons = widget.findChildren(QtWidgets.QPushButton)
        save_texts = [b.text() for b in buttons if b.text() == "Save"]
        assert len(save_texts) == 1


class TestGroupedKeysCheckState:
    def test_group_checked_when_all_children_in_keys(self, qapp):
        keys = {"group/a", "group/b"}
        key_data = [("group/a", 3), ("group/b", 5)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, keys, key_data=key_data)
        tab._build_tree()
        root = tab._tree.topLevelItem(0)
        assert root.checkState(0) == QtCore.Qt.Checked

    def test_group_unchecked_when_no_children_in_keys(self, qapp):
        key_data = [("group/a", 3), ("group/b", 5)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        tab._build_tree()
        root = tab._tree.topLevelItem(0)
        assert root.checkState(0) == QtCore.Qt.Unchecked

    def test_group_partial_when_some_children_in_keys(self, qapp):
        keys = {"group/a"}
        key_data = [("group/a", 3), ("group/b", 5)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, keys, key_data=key_data)
        tab._build_tree()
        root = tab._tree.topLevelItem(0)
        assert root.checkState(0) == QtCore.Qt.PartiallyChecked


def _find_leaf_by_key(tree, full_key):
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        if top.childCount() == 0:
            if top.data(1, QtCore.Qt.UserRole) == full_key:
                return top
        else:
            for j in range(top.childCount()):
                child = top.child(j)
                if child.data(1, QtCore.Qt.UserRole) == full_key:
                    return child
    return None


class TestSyncSelectedChecks:
    def test_toggle_applies_to_all_selected_leaves(self, qapp):
        key_data = [("a", 1), ("b", 2), ("c", 3)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        tab._build_tree()
        item_a = _find_leaf_by_key(tab._tree, "a")
        item_b = _find_leaf_by_key(tab._tree, "b")
        item_c = _find_leaf_by_key(tab._tree, "c")
        tab._pre_click_selection = [item_a, item_b, item_c]
        item_a.setCheckState(0, QtCore.Qt.Checked)
        tab._sync_selected_checks(item_a)
        assert item_b.checkState(0) == QtCore.Qt.Checked
        assert item_c.checkState(0) == QtCore.Qt.Checked

    def test_unselected_items_not_affected(self, qapp):
        key_data = [("a", 1), ("b", 2), ("c", 3)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        tab._build_tree()
        item_a = _find_leaf_by_key(tab._tree, "a")
        item_b = _find_leaf_by_key(tab._tree, "b")
        item_c = _find_leaf_by_key(tab._tree, "c")
        tab._pre_click_selection = [item_a, item_b]
        item_a.setCheckState(0, QtCore.Qt.Checked)
        tab._sync_selected_checks(item_a)
        assert item_b.checkState(0) == QtCore.Qt.Checked
        assert item_c.checkState(0) == QtCore.Qt.Unchecked


class TestOnItemClickedFilterKeysSync:
    def test_single_check_updates_filter_keys(self, qapp):
        key_data = [("a", 1), ("b", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        tab._build_tree()
        item_a = _find_leaf_by_key(tab._tree, "a")
        tab._pre_click_selection = [item_a]
        item_a.setCheckState(0, QtCore.Qt.Checked)
        tab._on_item_clicked(item_a, 0)
        assert "a" in tab._filter_keys

    def test_multi_select_click_updates_filter_keys(self, qapp):
        key_data = [("a", 1), ("b", 2), ("c", 3)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        tab._build_tree()
        item_a = _find_leaf_by_key(tab._tree, "a")
        item_b = _find_leaf_by_key(tab._tree, "b")
        tab._pre_click_selection = [item_a, item_b]
        item_a.setCheckState(0, QtCore.Qt.Checked)
        tab._on_item_clicked(item_a, 0)
        assert tab._filter_keys == {"a", "b"}


class TestBuildTreeFilterKeysWithZeroCount:
    def test_filter_keys_not_in_db_shown_with_zero(self, qapp):
        key_data = [("a", 10)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, {"a", "orphan"}, key_data=key_data)
        tab._build_tree()
        orphan_item = _find_leaf_by_key(tab._tree, "orphan")
        assert orphan_item is not None
        assert orphan_item.text(2) == "0"
        assert orphan_item.checkState(0) == QtCore.Qt.Checked

    def test_only_filter_keys_no_db_data(self, qapp):
        tab = _make_key_browser(qapp, MODE_BLACKLIST, {"x", "y"}, key_data=[])
        tab._build_tree()
        item_x = _find_leaf_by_key(tab._tree, "x")
        item_y = _find_leaf_by_key(tab._tree, "y")
        assert item_x is not None
        assert item_x.text(2) == "0"
        assert item_y is not None
        assert item_y.text(2) == "0"


class TestDbUpdateNotification:
    def test_on_db_updated_starts_timer_when_visible(self, qapp):
        widget = _make_exiftool_settings_widget(qapp)
        widget.show()
        qapp.processEvents()
        assert widget.isVisible()
        widget._on_db_updated("test.db")
        assert widget._debounce_timer.isActive()
        widget.close()

    def test_on_db_updated_sets_dirty_when_hidden(self, qapp):
        widget = _make_exiftool_settings_widget(qapp)
        assert not widget.isVisible()
        assert not widget._dirty
        widget._on_db_updated("test.db")
        assert widget._dirty
        assert not widget._debounce_timer.isActive()

    def test_show_event_triggers_refresh_when_dirty(self, qapp):
        widget = _make_exiftool_settings_widget(qapp)
        widget._dirty = True
        with patch.object(widget, "_refresh_key_browser") as mock_refresh:
            widget.show()
            qapp.processEvents()
            mock_refresh.assert_called_once()
        assert not widget._dirty
        widget.close()

    def test_hide_event_stops_timer(self, qapp):
        widget = _make_exiftool_settings_widget(qapp)
        widget.show()
        qapp.processEvents()
        widget._debounce_timer.start()
        assert widget._debounce_timer.isActive()
        widget.hide()
        qapp.processEvents()
        assert not widget._debounce_timer.isActive()
        widget.close()


class TestRestoreSelection:
    def test_selection_preserved_after_build_tree(self, qapp):
        key_data = [("a", 1), ("b", 2), ("c", 3)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        tab._build_tree()
        item_a = _find_leaf_by_key(tab._tree, "a")
        item_b = _find_leaf_by_key(tab._tree, "b")
        item_a.setSelected(True)
        item_b.setSelected(True)
        tab._build_tree()
        new_a = _find_leaf_by_key(tab._tree, "a")
        new_b = _find_leaf_by_key(tab._tree, "b")
        new_c = _find_leaf_by_key(tab._tree, "c")
        assert new_a.isSelected()
        assert new_b.isSelected()
        assert not new_c.isSelected()


class TestAllKnownKeys:
    def test_returns_db_keys_only(self, qapp):
        key_data = [("a", 1), ("b", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=key_data)
        assert tab.all_known_keys() == {"a", "b"}

    def test_returns_union_of_db_and_filter_keys(self, qapp):
        key_data = [("a", 1), ("b", 2)]
        tab = _make_key_browser(qapp, MODE_BLACKLIST, {"b", "c"}, key_data=key_data)
        assert tab.all_known_keys() == {"a", "b", "c"}

    def test_empty_when_no_data_no_filter(self, qapp):
        tab = _make_key_browser(qapp, MODE_BLACKLIST, set(), key_data=[])
        assert tab.all_known_keys() == set()


class TestQueryAllKeysMerged:
    def test_merges_keys_across_dbs(self, tmp_path):
        import sqlite3
        for name, rows in [
            ("db1", [("f1", "exiftool.width", "100"), ("f2", "exiftool.width", "200"), ("f1", "exiftool.height", "50")]),
            ("db2", [("f3", "exiftool.width", "300"), ("f3", "exiftool.model", "X")]),
        ]:
            p = tmp_path / f"{name}.sqlite"
            conn = sqlite3.connect(str(p))
            conn.execute("CREATE TABLE meta_info (path TEXT, key TEXT, value TEXT)")
            for r in rows:
                conn.execute("INSERT INTO meta_info VALUES (?, ?, ?)", r)
            conn.commit()
            conn.close()

        with patch(f"{MODULE}.list_setting_db_names", return_value=["db1", "db2"]), \
             patch(f"{MODULE}.data_db_path", side_effect=lambda n: str(tmp_path / f"{n}.sqlite")):
            from extensions.exiftool.panel import _query_all_keys_merged
            result = _query_all_keys_merged()

        result_dict = dict(result)
        assert result_dict["width"] == 3
        assert result_dict["height"] == 1
        assert result_dict["model"] == 1

    def test_empty_when_no_dbs(self):
        with patch(f"{MODULE}.list_setting_db_names", return_value=[]):
            from extensions.exiftool.panel import _query_all_keys_merged
            assert _query_all_keys_merged() == []

    def test_sorted_by_key_name(self, tmp_path):
        import sqlite3
        p = tmp_path / "db.sqlite"
        conn = sqlite3.connect(str(p))
        conn.execute("CREATE TABLE meta_info (path TEXT, key TEXT, value TEXT)")
        conn.execute("INSERT INTO meta_info VALUES ('f', 'exiftool.zebra', '1')")
        conn.execute("INSERT INTO meta_info VALUES ('f', 'exiftool.alpha', '2')")
        conn.commit()
        conn.close()

        with patch(f"{MODULE}.list_setting_db_names", return_value=["db"]), \
             patch(f"{MODULE}.data_db_path", return_value=str(p)):
            from extensions.exiftool.panel import _query_all_keys_merged
            result = _query_all_keys_merged()
        assert [k for k, _ in result] == ["alpha", "zebra"]


class TestQuerySampleValuesAll:
    def test_collects_from_multiple_dbs(self, tmp_path):
        import sqlite3
        for name, rows in [("db1", [("f1", "exiftool.w", "10")]), ("db2", [("f2", "exiftool.w", "20")])]:
            p = tmp_path / f"{name}.sqlite"
            conn = sqlite3.connect(str(p))
            conn.execute("CREATE TABLE meta_info (path TEXT, key TEXT, value TEXT)")
            for r in rows:
                conn.execute("INSERT INTO meta_info VALUES (?, ?, ?)", r)
            conn.commit()
            conn.close()

        with patch(f"{MODULE}.list_setting_db_names", return_value=["db1", "db2"]), \
             patch(f"{MODULE}.data_db_path", side_effect=lambda n: str(tmp_path / f"{n}.sqlite")):
            from extensions.exiftool.panel import _query_sample_values_all
            result = _query_sample_values_all("exiftool.w", limit=10)

        assert len(result) == 2
        assert result[0] == ("db1", "f1", "10")
        assert result[1] == ("db2", "f2", "20")

    def test_respects_limit(self, tmp_path):
        import sqlite3
        p = tmp_path / "db.sqlite"
        conn = sqlite3.connect(str(p))
        conn.execute("CREATE TABLE meta_info (path TEXT, key TEXT, value TEXT)")
        for i in range(20):
            conn.execute(f"INSERT INTO meta_info VALUES ('f{i}', 'exiftool.k', 'v{i}')")
        conn.commit()
        conn.close()

        with patch(f"{MODULE}.list_setting_db_names", return_value=["db"]), \
             patch(f"{MODULE}.data_db_path", return_value=str(p)):
            from extensions.exiftool.panel import _query_sample_values_all
            result = _query_sample_values_all("exiftool.k", limit=5)

        assert len(result) == 5

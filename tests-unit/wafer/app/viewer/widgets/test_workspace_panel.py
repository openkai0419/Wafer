import py_compile

from PySide6 import QtCore, QtWidgets


def test_compile():
    py_compile.compile("wafer/app/viewer/widgets/workspace_toolbar.py")


class TestPresetItem:
    def test_apply_emits_mode_from_provider(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _PresetItem

        item = _PresetItem("query", "p1", "MyPreset", mode_provider=lambda: "append")
        qtbot.addWidget(item)
        captured = []
        item.apply_requested.connect(lambda kind, pid, mode: captured.append((kind, pid, mode)))
        item._on_apply_click()
        assert captured == [("query", "p1", "append")]

    def test_apply_defaults_to_replace_without_provider(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _PresetItem

        item = _PresetItem("ui", "p2", "X")
        qtbot.addWidget(item)
        captured = []
        item.apply_requested.connect(lambda kind, pid, mode: captured.append(mode))
        item._on_apply_click()
        assert captured == ["replace"]

    def test_text_area_click_emits_apply(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _PresetItem

        item = _PresetItem("ui", "p2", "X", "2026-04-27T10:00:00+00:00")
        qtbot.addWidget(item)
        item.show()
        captured = []
        item.apply_requested.connect(lambda kind, pid, mode: captured.append((kind, pid, mode)))
        qtbot.mouseClick(item._text_area, QtCore.Qt.LeftButton, pos=item._text_area.rect().center())
        assert captured == [("ui", "p2", "replace")]

    def test_text_area_hover_and_date_are_part_of_click_target(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _PresetItem

        item = _PresetItem("ui", "p2", "X", "2026-04-27T10:00:00+00:00")
        qtbot.addWidget(item)
        assert item._text_area.cursor().shape() == QtCore.Qt.PointingHandCursor
        assert "hover" in item._text_area.styleSheet()
        assert item._label.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        assert item._updated_label.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

    def test_overwrite_emits_kind_and_id(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _PresetItem

        item = _PresetItem("ui", "p2", "X")
        qtbot.addWidget(item)
        captured = []
        item.overwrite_requested.connect(lambda kind, pid: captured.append((kind, pid)))
        item.overwrite_requested.emit(item.kind, item.preset_id)
        assert captured == [("ui", "p2")]

    def test_overwrite_uses_save_icon(self, qtbot):
        from unittest.mock import patch

        from wafer.app.viewer.widgets import workspace_toolbar
        from wafer.core.qt.icon_engine import themed_icon

        keys = []
        with patch.object(workspace_toolbar, "themed_icon", side_effect=lambda key, *a, **kw: keys.append(key) or themed_icon(key, *a, **kw)):
            item = workspace_toolbar._PresetItem("ui", "p2", "X")
        qtbot.addWidget(item)
        assert "save" in keys


class TestColumn:
    def test_query_mode_returns_combo_data(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column

        col = _Column("query", "Filter")
        qtbot.addWidget(col)
        assert col.query_mode() == "replace"
        col._mode_combo.setCurrentIndex(1)
        assert col.query_mode() == "append"

    def test_query_mode_non_query_returns_replace(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column

        col = _Column("ui", "UI")
        qtbot.addWidget(col)
        assert col.query_mode() == "replace"

    def test_restore_sort_only_for_query(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column

        ui_col = _Column("ui", "UI")
        qtbot.addWidget(ui_col)
        assert ui_col.restore_sort() is False

        q_col = _Column("query", "Filter")
        qtbot.addWidget(q_col)
        assert q_col.restore_sort() is True
        q_col._restore_sort_cb.setChecked(False)
        assert q_col.restore_sort() is False

    def test_restore_window_state_only_for_ui(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column

        path_col = _Column("path", "Path")
        qtbot.addWidget(path_col)
        assert path_col.restore_window_state() is False

        ui_col = _Column("ui", "UI")
        qtbot.addWidget(ui_col)
        assert ui_col.restore_window_state() is False
        ui_col._restore_window_cb.setChecked(True)
        assert ui_col.restore_window_state() is True

    def test_populate_injects_mode_provider_for_query_column(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column, _PresetItem

        col = _Column("query", "Filter")
        qtbot.addWidget(col)
        col._mode_combo.setCurrentIndex(1)  # append
        col.populate([("p1", "A", "")])
        item = col.findChild(_PresetItem)
        assert item is not None
        assert item._mode_provider is not None
        assert item._mode_provider() == "append"

    def test_populate_no_mode_provider_for_non_query(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column, _PresetItem

        col = _Column("ui", "UI")
        qtbot.addWidget(col)
        col.populate([("p1", "A", "#fff")])
        item = col.findChild(_PresetItem)
        assert item._mode_provider is None
        assert not hasattr(item, "_dot")

    def test_populate_replaces_previous_items(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column, _PresetItem

        col = _Column("ui", "UI")
        qtbot.addWidget(col)
        col.populate([("p1", "A", "")])
        col.populate([("p2", "B", ""), ("p3", "C", "")])
        ids = {col._list_layout.itemAt(i).widget().preset_id
               for i in range(col._list_layout.count())
               if isinstance(col._list_layout.itemAt(i).widget(), _PresetItem)}
        assert ids == {"p2", "p3"}

    def test_populate_empty_shows_placeholder(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column, _PresetItem

        col = _Column("ui", "UI")
        qtbot.addWidget(col)
        col.populate([])
        assert col.findChild(_PresetItem) is None
        labels = [w for w in col.findChildren(QtWidgets.QLabel) if w.text() and "(" in w.text()]
        assert any("empty" in l.text().lower() or "(" in l.text() for l in labels)

    def test_save_signal_emits_kind(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column

        col = _Column("path", "Path")
        qtbot.addWidget(col)
        captured = []
        col.save_requested.connect(captured.append)
        col._on_save()
        assert captured == ["path"]

    def test_apply_signal_propagates(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column, _PresetItem

        col = _Column("query", "Filter")
        qtbot.addWidget(col)
        col.populate([("p1", "A", "")])
        captured = []
        col.apply_requested.connect(lambda k, pid, m: captured.append((k, pid, m)))
        item = col.findChild(_PresetItem)
        item._on_apply_click()
        assert captured == [("query", "p1", "replace")]

    def test_overwrite_signal_propagates(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column, _PresetItem

        col = _Column("ui", "UI")
        qtbot.addWidget(col)
        col.populate([("p1", "A", "", "2026-04-27T10:00:00+00:00")])
        captured = []
        col.overwrite_requested.connect(lambda k, pid: captured.append((k, pid)))
        item = col.findChild(_PresetItem)
        item.overwrite_requested.emit(item.kind, item.preset_id)
        assert captured == [("ui", "p1")]

    def test_column_scrolls_only_preset_items(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column

        col = _Column("query", "Filter")
        qtbot.addWidget(col)
        col.populate([("p1", "A", "")])
        scrolls = col.findChildren(QtWidgets.QScrollArea)
        assert scrolls == [col._list_scroll]
        assert col._save_btn not in col._list_scroll.findChildren(QtWidgets.QPushButton)
        assert col._mode_combo not in col._list_scroll.findChildren(QtWidgets.QComboBox)

    def test_apply_settings_are_in_column_content(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column

        ui_col = _Column("ui", "UI")
        qtbot.addWidget(ui_col)
        assert ui_col._restore_window_cb in ui_col.findChildren(QtWidgets.QCheckBox)

        q_col = _Column("query", "Filter")
        qtbot.addWidget(q_col)
        assert q_col._mode_combo in q_col.findChildren(QtWidgets.QComboBox)
        assert q_col._restore_sort_cb in q_col.findChildren(QtWidgets.QCheckBox)

    def test_preset_list_height_is_shared(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column

        columns = [_Column("ui", "UI"), _Column("path", "Path"), _Column("query", "Filter")]
        for col in columns:
            qtbot.addWidget(col)
        heights = {col._list_scroll.minimumHeight() for col in columns}
        assert len(heights) == 1
        assert all(col._list_scroll.minimumHeight() == col._list_scroll.maximumHeight() for col in columns)

    def test_long_preset_name_does_not_expand_content_width(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _Column, _PresetItem

        col = _Column("path", "Path")
        qtbot.addWidget(col)
        col.populate([("p1", "A" * 500, "")])
        item = col.findChild(_PresetItem)
        assert item._label.minimumWidth() == 0
        assert item._label.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Ignored
        assert col.minimumSizeHint().width() < 220


class TestSectionButton:
    def test_button_switches_chevron_state(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _SectionButton

        btn = _SectionButton("ui", "UI")
        qtbot.addWidget(btn)
        closed_key = btn.icon().cacheKey()
        assert btn.expanded is False

        btn.set_expanded(True)
        assert btn.expanded is True
        assert btn.icon().cacheKey() != closed_key

        btn.set_expanded(False)
        assert btn.expanded is False


class TestWorkspaceToolbarWidget:
    def test_toolbar_contains_four_compact_buttons(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store):
            panel = workspace_widget.WorkspaceToolbarWidget()
        qtbot.addWidget(panel)
        assert set(panel._section_buttons) == {"ui", "path", "query", "recent"}
        assert [panel.layout().itemAt(i).widget().key for i in range(panel.layout().count())] == ["recent", "ui", "path", "query"]
        assert panel._section_buttons["recent"].text() == ""
        assert panel._section_buttons["recent"].toolTip() == "Recent"
        assert panel._section_buttons["recent"]._icon_key == "history"
        assert panel.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Expanding
        assert panel._section_buttons["recent"].sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Fixed
        for key in ("ui", "path", "query"):
            assert panel._section_buttons[key].sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Expanding

    def test_only_preset_section_buttons_stretch_horizontally(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store):
            panel = workspace_widget.WorkspaceToolbarWidget()
        qtbot.addWidget(panel)

        layout = panel.layout()
        assert layout.stretch(0) == 0
        assert [layout.stretch(i) for i in range(1, 4)] == [1, 1, 1]

    def test_recent_restore_uses_history_icon(self, qtbot):
        from unittest.mock import patch

        from wafer.app.viewer.widgets import workspace_toolbar
        from wafer.core.qt.icon_engine import themed_icon
        from wafer.core.workspace import WindowSlot

        keys = []
        with patch.object(workspace_toolbar, "themed_icon", side_effect=lambda key, *a, **kw: keys.append(key) or themed_icon(key, *a, **kw)):
            item = workspace_toolbar._RecentSlotItem(WindowSlot(slot_id="s1", path={"database_name": "db"}))
        qtbot.addWidget(item)
        assert "history" in keys

    def test_recent_delete_uses_trash_icon_and_emits_slot_id(self, qtbot):
        from unittest.mock import patch

        from wafer.app.viewer.widgets import workspace_toolbar
        from wafer.core.qt.icon_engine import themed_icon
        from wafer.core.workspace import WindowSlot

        keys = []
        with patch.object(workspace_toolbar, "themed_icon", side_effect=lambda key, *a, **kw: keys.append(key) or themed_icon(key, *a, **kw)):
            item = workspace_toolbar._RecentSlotItem(WindowSlot(slot_id="s1", path={"database_name": "db"}))
        qtbot.addWidget(item)
        captured = []
        item.delete_requested.connect(captured.append)
        delete_button = next(btn for btn in item.findChildren(QtWidgets.QToolButton) if btn.toolTip() == "Delete")
        qtbot.mouseClick(delete_button, QtCore.Qt.LeftButton)
        assert "trash" in keys
        assert captured == ["s1"]

    def test_recent_rename_uses_pencil_icon_and_emits_slot_id(self, qtbot):
        from unittest.mock import patch

        from wafer.app.viewer.widgets import workspace_toolbar
        from wafer.core.qt.icon_engine import themed_icon
        from wafer.core.workspace import WindowSlot

        keys = []
        with patch.object(workspace_toolbar, "themed_icon", side_effect=lambda key, *a, **kw: keys.append(key) or themed_icon(key, *a, **kw)):
            item = workspace_toolbar._RecentSlotItem(WindowSlot(slot_id="s1", path={"database_name": "db"}))
        qtbot.addWidget(item)
        captured = []
        item.rename_requested.connect(captured.append)
        rename_button = next(btn for btn in item.findChildren(QtWidgets.QToolButton) if btn.toolTip() == "Rename")
        qtbot.mouseClick(rename_button, QtCore.Qt.LeftButton)
        assert "pencil" in keys
        assert captured == ["s1"]

    def test_recent_current_slot_has_marker_and_enabled_restore(self, qtbot):
        from wafer.app.viewer.widgets import workspace_toolbar
        from wafer.core.workspace import WindowSlot

        item = workspace_toolbar._RecentSlotItem(WindowSlot(slot_id="s1", path={"database_name": "db"}), is_current=True)
        qtbot.addWidget(item)
        assert item._current_marker.property("current") is True
        assert item._restore_button.isEnabled() is True
        assert item._restore_button.toolTip() == "Restore"

    def test_recent_slot_name_is_displayed_over_summary(self, qtbot):
        from wafer.app.viewer.widgets import workspace_toolbar
        from wafer.core.workspace import WindowSlot

        item = workspace_toolbar._RecentSlotItem(WindowSlot(slot_id="s1", name="Work", path={"database_name": "db"}))
        qtbot.addWidget(item)
        assert item._title_label.full_text() == "Work"
        assert "db" in item._subtitle_label.full_text()

    def test_popup_size_is_compact(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _SectionPopup

        from wafer.utils.formatting import dpix

        popup = _SectionPopup("ui")
        qtbot.addWidget(popup)
        assert popup.minimumWidth() <= dpix(280)
        assert popup.height() <= dpix(420)

    def test_recent_content_height_follows_item_count(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _RecentSectionContent
        from wafer.core.workspace import WindowSlot

        recent = _RecentSectionContent()
        qtbot.addWidget(recent)
        recent.populate([])
        empty_height = recent.content_height_hint().height()
        recent.populate([
            WindowSlot(slot_id="s1", path={"database_name": "db"}),
            WindowSlot(slot_id="s2", path={"database_name": "db"}),
            WindowSlot(slot_id="s3", path={"database_name": "db"}),
        ])
        assert recent.content_height_hint().height() > empty_height

    def test_recent_content_propagates_delete_request(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _RecentSectionContent, _RecentSlotItem
        from wafer.core.workspace import WindowSlot

        recent = _RecentSectionContent()
        qtbot.addWidget(recent)
        recent.populate([WindowSlot(slot_id="s1", path={"database_name": "db"})])
        captured = []
        recent.delete_requested.connect(captured.append)
        item = recent.findChild(_RecentSlotItem)
        item.delete_requested.emit("s1")
        assert captured == ["s1"]

    def test_recent_content_propagates_rename_request(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _RecentSectionContent, _RecentSlotItem
        from wafer.core.workspace import WindowSlot

        recent = _RecentSectionContent()
        qtbot.addWidget(recent)
        recent.populate([WindowSlot(slot_id="s1", path={"database_name": "db"})])
        captured = []
        recent.rename_requested.connect(captured.append)
        item = recent.findChild(_RecentSlotItem)
        item.rename_requested.emit("s1")
        assert captured == ["s1"]

    def test_recent_content_marks_current_slot(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _RecentSectionContent, _RecentSlotItem
        from wafer.core.workspace import WindowSlot

        recent = _RecentSectionContent()
        qtbot.addWidget(recent)
        recent.populate([
            WindowSlot(slot_id="s1", path={"database_name": "db"}),
            WindowSlot(slot_id="s2", path={"database_name": "db"}),
        ], current_slot_id="s2")
        items = {item.slot.slot_id: item for item in recent.findChildren(_RecentSlotItem)}
        assert items["s1"].is_current is False
        assert items["s2"].is_current is True

    def test_recent_long_title_does_not_expand_content_width(self, qtbot):
        from wafer.app.viewer.widgets.workspace_toolbar import _RecentSectionContent
        from wafer.core.workspace import WindowSlot

        recent = _RecentSectionContent()
        qtbot.addWidget(recent)
        recent.populate([WindowSlot(slot_id="s1", path={"database_name": "D" * 500})])
        labels = [label for label in recent.findChildren(QtWidgets.QLabel) if label.toolTip()]
        assert labels
        assert labels[0].minimumWidth() == 0
        assert labels[0].sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Ignored
        assert recent.minimumSizeHint().width() < 260

    def test_initial_popups_are_closed(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store):
            panel = workspace_widget.WorkspaceToolbarWidget()
        qtbot.addWidget(panel)
        assert panel._active_section is None
        assert all(not btn.expanded for btn in panel._section_buttons.values())
        assert all(not popup.isVisible() for popup in panel._section_popups.values())

    def test_recent_refresh_includes_active_slots(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store):
            panel = workspace_widget.WorkspaceToolbarWidget()
        qtbot.addWidget(panel)
        qtbot.waitUntil(lambda: store.list_recent_slots.called, timeout=2000)
        store.list_recent_slots.assert_called_with(limit=8, include_active=True)

    def test_delete_recent_slot_confirms_and_invokes_command(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget
        from wafer.core.workspace import WindowSlot

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        store.get_slot.return_value = WindowSlot(slot_id="s1", path={"database_name": "db"})
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store), \
             patch.object(workspace_widget.ConfirmDialog, "ask", return_value="Delete") as ask, \
             patch.object(workspace_widget.Command, "invoke") as invoke:
            panel = workspace_widget.WorkspaceToolbarWidget()
            qtbot.addWidget(panel)
            panel._on_delete_slot("s1")

        ask.assert_called_once()
        invoke.assert_called_once_with("ws.delete_slot", slot_id="s1")

    def test_rename_recent_slot_invokes_command(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store), \
             patch.object(workspace_widget.Command, "invoke") as invoke:
            panel = workspace_widget.WorkspaceToolbarWidget()
            qtbot.addWidget(panel)
            panel._on_rename_slot("s1")

        invoke.assert_called_once_with("ws.rename_slot", slot_id="s1")

    def test_restore_current_recent_slot_invokes_command(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store), \
             patch.object(workspace_widget.Command, "invoke") as invoke:
            panel = workspace_widget.WorkspaceToolbarWidget()
            panel.slot_id = "s1"
            qtbot.addWidget(panel)
            panel._on_restore_slot("s1")

        invoke.assert_called_once_with("ws.restore_slot", slot_id="s1")

    def test_opening_one_popup_closes_previous(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store):
            panel = workspace_widget.WorkspaceToolbarWidget()
        qtbot.addWidget(panel)
        panel.show()

        panel._on_section_button_clicked("ui")
        assert panel._active_section == "ui"
        assert panel._section_buttons["ui"].expanded is True
        assert panel._section_popups["ui"].isVisible()

        panel._on_section_button_clicked("path")
        assert panel._active_section == "path"
        assert panel._section_buttons["ui"].expanded is False
        assert panel._section_buttons["path"].expanded is True
        assert not panel._section_popups["ui"].isVisible()
        assert panel._section_popups["path"].isVisible()

    def test_clicking_active_button_closes_popup(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store):
            panel = workspace_widget.WorkspaceToolbarWidget()
        qtbot.addWidget(panel)
        panel.show()

        panel._on_section_button_clicked("query")
        assert panel._section_popups["query"].isVisible()
        panel._on_section_button_clicked("query")
        assert panel._active_section is None
        assert panel._section_buttons["query"].expanded is False
        assert not panel._section_popups["query"].isVisible()

    def test_popup_hide_resets_button_state(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store):
            panel = workspace_widget.WorkspaceToolbarWidget()
        qtbot.addWidget(panel)
        panel.show()

        panel._on_section_button_clicked("recent")
        assert panel._section_buttons["recent"].expanded is True
        panel._section_popups["recent"].hide()
        assert panel._active_section is None
        assert panel._section_buttons["recent"].expanded is False

    def test_public_show_popup_opens_requested_section(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store):
            panel = workspace_widget.WorkspaceToolbarWidget()
        qtbot.addWidget(panel)
        panel.show()

        panel.show_filter_popup()
        assert panel._active_section == "query"
        assert panel._section_buttons["query"].expanded is True
        assert panel._section_popups["query"].isVisible()


class TestRefreshMtimeCache:
    def test_refresh_skips_snapshot_when_mtime_unchanged(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        store.get_store_mtime.return_value = 100.0
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store):
            panel = workspace_widget.WorkspaceToolbarWidget()
            qtbot.addWidget(panel)
            qtbot.waitUntil(lambda: store.snapshot.called, timeout=2000)
            store.snapshot.reset_mock()
            store.list_recent_slots.reset_mock()
            panel.refresh()
            qtbot.wait(50)
            assert not store.snapshot.called
            assert not store.list_recent_slots.called

    def test_refresh_force_reloads_even_when_mtime_unchanged(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        store.get_store_mtime.return_value = 100.0
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store):
            panel = workspace_widget.WorkspaceToolbarWidget()
            qtbot.addWidget(panel)
            qtbot.waitUntil(lambda: store.snapshot.call_count >= 1, timeout=2000)
            panel.refresh(force=True)
            qtbot.waitUntil(lambda: store.snapshot.call_count >= 2, timeout=2000)

    def test_refresh_reloads_when_mtime_changes(self, qtbot):
        from unittest.mock import MagicMock, patch

        from wafer.app.viewer.widgets import workspace_toolbar as workspace_widget

        store = MagicMock()
        store.snapshot.return_value = ([], [], [])
        store.list_recent_slots.return_value = []
        store.get_store_mtime.return_value = 100.0
        with patch.object(workspace_widget.WorkspaceStore, "instance", return_value=store):
            panel = workspace_widget.WorkspaceToolbarWidget()
            qtbot.addWidget(panel)
            qtbot.waitUntil(lambda: store.snapshot.call_count >= 1, timeout=2000)
            store.get_store_mtime.return_value = 200.0
            panel.refresh()
            qtbot.waitUntil(lambda: store.snapshot.call_count >= 2, timeout=2000)


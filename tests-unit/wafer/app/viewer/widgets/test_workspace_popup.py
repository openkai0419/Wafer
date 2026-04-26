import py_compile

import pytest


def test_compile():
    py_compile.compile("wafer/app/viewer/widgets/workspace_popup.py")


class TestPresetItem:
    def test_apply_emits_mode_from_provider(self, qtbot):
        from wafer.app.viewer.widgets.workspace_popup import _PresetItem

        item = _PresetItem("query", "p1", "MyPreset", mode_provider=lambda: "append")
        qtbot.addWidget(item)
        captured = []
        item.apply_requested.connect(lambda kind, pid, mode: captured.append((kind, pid, mode)))
        item._on_apply_click()
        assert captured == [("query", "p1", "append")]

    def test_apply_defaults_to_replace_without_provider(self, qtbot):
        from wafer.app.viewer.widgets.workspace_popup import _PresetItem

        item = _PresetItem("ui", "p2", "X")
        qtbot.addWidget(item)
        captured = []
        item.apply_requested.connect(lambda kind, pid, mode: captured.append(mode))
        item._on_apply_click()
        assert captured == ["replace"]


class TestColumn:
    def test_query_mode_returns_combo_data(self, qtbot):
        from wafer.app.viewer.widgets.workspace_popup import _Column

        col = _Column("query", "Filter")
        qtbot.addWidget(col)
        assert col.query_mode() == "replace"
        col._mode_combo.setCurrentIndex(1)
        assert col.query_mode() == "append"

    def test_query_mode_non_query_returns_replace(self, qtbot):
        from wafer.app.viewer.widgets.workspace_popup import _Column

        col = _Column("ui", "UI")
        qtbot.addWidget(col)
        assert col.query_mode() == "replace"

    def test_include_sort_only_for_query(self, qtbot):
        from wafer.app.viewer.widgets.workspace_popup import _Column

        ui_col = _Column("ui", "UI")
        qtbot.addWidget(ui_col)
        assert ui_col.include_sort() is False

        q_col = _Column("query", "Filter")
        qtbot.addWidget(q_col)
        assert q_col.include_sort() is False
        q_col._include_sort_cb.setChecked(True)
        assert q_col.include_sort() is True

    def test_populate_injects_mode_provider_for_query_column(self, qtbot):
        from wafer.app.viewer.widgets.workspace_popup import _Column, _PresetItem

        col = _Column("query", "Filter")
        qtbot.addWidget(col)
        col._mode_combo.setCurrentIndex(1)  # append
        col.populate([("p1", "A", "")])
        item = col.findChild(_PresetItem)
        assert item is not None
        assert item._mode_provider is not None
        assert item._mode_provider() == "append"

    def test_populate_no_mode_provider_for_non_query(self, qtbot):
        from wafer.app.viewer.widgets.workspace_popup import _Column, _PresetItem

        col = _Column("ui", "UI")
        qtbot.addWidget(col)
        col.populate([("p1", "A", "#fff")])
        item = col.findChild(_PresetItem)
        assert item._mode_provider is None

    def test_populate_replaces_previous_items(self, qtbot):
        from wafer.app.viewer.widgets.workspace_popup import _Column, _PresetItem

        col = _Column("ui", "UI")
        qtbot.addWidget(col)
        col.populate([("p1", "A", "")])
        col.populate([("p2", "B", ""), ("p3", "C", "")])
        ids = {col._list_layout.itemAt(i).widget().preset_id
               for i in range(col._list_layout.count())
               if isinstance(col._list_layout.itemAt(i).widget(), _PresetItem)}
        assert ids == {"p2", "p3"}

    def test_populate_empty_shows_placeholder(self, qtbot):
        from PySide6 import QtWidgets

        from wafer.app.viewer.widgets.workspace_popup import _Column, _PresetItem

        col = _Column("ui", "UI")
        qtbot.addWidget(col)
        col.populate([])
        assert col.findChild(_PresetItem) is None
        labels = [w for w in col.findChildren(QtWidgets.QLabel) if w.text() and "(" in w.text()]
        assert any("empty" in l.text().lower() or "(" in l.text() for l in labels)

    def test_save_signal_emits_kind(self, qtbot):
        from wafer.app.viewer.widgets.workspace_popup import _Column

        col = _Column("path", "Path")
        qtbot.addWidget(col)
        captured = []
        col.save_requested.connect(captured.append)
        col._on_save()
        assert captured == ["path"]

    def test_apply_signal_propagates(self, qtbot):
        from wafer.app.viewer.widgets.workspace_popup import _Column, _PresetItem

        col = _Column("query", "Filter")
        qtbot.addWidget(col)
        col.populate([("p1", "A", "")])
        captured = []
        col.apply_requested.connect(lambda k, pid, m: captured.append((k, pid, m)))
        item = col.findChild(_PresetItem)
        item._on_apply_click()
        assert captured == [("query", "p1", "replace")]

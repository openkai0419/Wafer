import json

from PySide6 import QtWidgets

from extensions.text_generation.comfyui_panel import (
    ComfyUiWorkflowPanelPlugin,
    WorkflowDragExport,
)
from wafer.plugin import BaseKeyValuePanelPlugin
from wafer.ui.panel.meta_viewer import CollapsibleCard
from wafer.ui.panel.searchable_meta_widget import SearchableMetaWidget

WORKFLOW = {"nodes": [{"id": 3, "type": "KSampler"}], "links": []}


class TestComfyUiWorkflowPanelPlugin:
    def setup_method(self):
        self.plugin = ComfyUiWorkflowPanelPlugin()

    def test_inherits_base(self):
        assert isinstance(self.plugin, BaseKeyValuePanelPlugin)

    def test_prefix_and_scope(self):
        assert self.plugin.PREFIX == "comfyui"
        assert self.plugin.DATA_SCOPE == "meta_info"

    def test_create_card_builds_composite(self, qtbot):
        card = self.plugin.create_card(scope="meta_info")
        qtbot.addWidget(card)
        assert isinstance(card, CollapsibleCard)
        assert isinstance(self.plugin._body, SearchableMetaWidget)
        assert isinstance(self.plugin._export, WorkflowDragExport)

    def test_update_data_excludes_workflow_from_body(self, qtbot):
        card = self.plugin.create_card(scope="meta_info")
        qtbot.addWidget(card)
        data = {"KSampler#0/seed": "42", "workflow": json.dumps(WORKFLOW)}
        self.plugin.update_data(dict(data), file_hash="abc")
        assert not self.plugin._export.isHidden()
        assert "workflow" not in self.plugin._body._data

    def test_update_data_hides_export_without_workflow(self, qtbot):
        card = self.plugin.create_card(scope="meta_info")
        qtbot.addWidget(card)
        self.plugin.update_data({"KSampler#0/seed": "42"}, file_hash="abc")
        assert self.plugin._export.isHidden()


class TestWorkflowDragExport:
    def test_write_temp_produces_valid_json(self, qtbot, monkeypatch, tmp_path):
        import extensions.text_generation.comfyui_panel as mod

        def fake_temp(rel):
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            return str(path)

        monkeypatch.setattr(mod, "resolve_temp_path", fake_temp)
        widget = WorkflowDragExport()
        qtbot.addWidget(widget)
        widget.set_workflow(json.dumps(WORKFLOW), "abc")
        target = widget._write_temp()
        assert target is not None
        assert json.loads(open(target, encoding="utf-8").read()) == WORKFLOW

    def test_write_temp_none_without_workflow(self, qtbot):
        widget = WorkflowDragExport()
        qtbot.addWidget(widget)
        assert widget._write_temp() is None

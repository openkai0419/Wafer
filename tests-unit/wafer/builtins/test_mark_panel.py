from wafer.builtins.mark.panel import MarkTagPanelPlugin
from wafer.plugin.tag_panel.base import BaseTagPanelPlugin


def test_mark_is_tag_panel_subclass():
    assert issubclass(MarkTagPanelPlugin, BaseTagPanelPlugin)
    assert MarkTagPanelPlugin.PREFIX == "mark"
    assert MarkTagPanelPlugin.NAME == "mark_panel"


def test_mark_create_card_and_update(qtbot):
    plugin = MarkTagPanelPlugin()
    card = plugin.create_card()
    qtbot.addWidget(card)
    plugin.update_data({"1": "1", "2": "1"}, {}, "/p", "h", "db")
    assert plugin._row is not None
    assert plugin._row._active_ids == ["1", "2"]

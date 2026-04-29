from wafer.builtins.mark.panel import MarkTagPanelPlugin
from wafer.plugin.meta_panel.base import BaseMetaPanelPlugin


def test_mark_is_meta_panel_subclass():
    assert issubclass(MarkTagPanelPlugin, BaseMetaPanelPlugin)
    assert MarkTagPanelPlugin.PREFIX == "mark"
    assert MarkTagPanelPlugin.NAME == "mark_panel"


def test_mark_create_card_and_update(qtbot):
    plugin = MarkTagPanelPlugin()
    card = plugin.create_card()
    qtbot.addWidget(card)
    plugin.update_data({"1": "1", "2": "1"}, {}, "/p", "db")
    assert plugin._row is not None
    assert plugin._row._active == {"1", "2"}
    assert plugin._row._current_path == "/p"

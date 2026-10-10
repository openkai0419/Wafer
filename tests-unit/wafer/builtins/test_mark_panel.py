from wafer.builtins.mark.panel import MarkTagPanelPlugin


def test_mark_create_card_and_update(qtbot):
    plugin = MarkTagPanelPlugin()
    card = plugin.create_card()
    qtbot.addWidget(card)
    plugin.update_data({"1": "1", "2": "1"}, {}, "/p", "h", "db", scope="tag")
    assert plugin._row is not None
    assert plugin._row._active == {"1", "2"}
    assert plugin._row._current_path == "/p"
    assert plugin._row._scope == "tag"

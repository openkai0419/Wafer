from extensions.mapping.panel import MappingPlugin
from extensions.mapping.widget import MappingWidget


def test_plugin_identity():
    assert MappingPlugin.NAME == "mapping"
    assert MappingPlugin.DISPLAY_NAME == "Mapping"


def test_created_widget_restores_saved_state(qtbot):
    MappingPlugin.saved_state = {"grouping": False}
    plugin = MappingPlugin()
    widget = plugin.create_widget()
    qtbot.addWidget(widget)
    assert isinstance(widget, MappingWidget)
    assert widget.grouping is False
    state = plugin.save_ui_state()
    assert state["grouping"] is False
    plugin.restore_ui_state({"grouping": True})
    assert widget.grouping is True
    MappingPlugin.saved_state = {}
    widget.close()

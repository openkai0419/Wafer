from extensions.mapping.panel import MappingPlugin
from extensions.mapping.view_settings import ViewSettings
from extensions.mapping.widget import MappingWidget


def test_plugin_identity():
    assert MappingPlugin.NAME == "mapping"
    assert MappingPlugin.DISPLAY_NAME == "Mapping"


def test_created_widget_restores_saved_state(qtbot):
    MappingPlugin.saved_state = {"view": {"labels": False}}
    plugin = MappingPlugin()
    widget = plugin.create_widget()
    qtbot.addWidget(widget)
    assert isinstance(widget, MappingWidget)
    settings = ViewSettings.instance()
    assert settings.labels_shown is False and not widget.toolbar.label_check.isChecked()
    state = plugin.save_ui_state()
    assert state["view"]["labels"] is False
    plugin.restore_ui_state({"view": {"labels": True}})
    assert settings.labels_shown is True and widget.toolbar.label_check.isChecked()
    MappingPlugin.saved_state = {}
    widget.close()

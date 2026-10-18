from extensions.mapping.panel import MappingPlugin
from extensions.mapping.view_settings import ViewSettings
from extensions.mapping.widget import MappingWidget


def test_plugin_identity():
    assert MappingPlugin.NAME == "mapping"
    assert MappingPlugin.DISPLAY_NAME == "Mapping"


def test_plugin_restores_the_shared_view_settings_before_the_widget_exists(qtbot):
    plugin = MappingPlugin()
    plugin.restore_ui_state({"view": {"labels": False}})
    settings = ViewSettings.instance()
    assert settings.labels_shown is False and "view" not in MappingPlugin.saved_state
    widget = plugin.create_widget()
    qtbot.addWidget(widget)
    assert isinstance(widget, MappingWidget)
    assert not widget.toolbar.label_check.isChecked()
    assert plugin.save_ui_state()["view"]["labels"] is False
    plugin.restore_ui_state({"view": {"labels": True}})
    assert settings.labels_shown is True and widget.toolbar.label_check.isChecked()
    MappingPlugin.saved_state = {}
    widget.close()


def test_plugin_saves_the_current_view_settings():
    MappingPlugin.saved_state = {}
    ViewSettings.instance().set_image_scale(2.0)
    assert MappingPlugin().save_ui_state()["view"]["image_scale"] == 2.0


def test_loading_unchanged_view_settings_does_not_notify():
    settings = ViewSettings.instance()
    events = []
    settings.changed.connect(events.append)
    settings.load(settings.to_dict())
    assert events == []
    settings.load({"params": {"label_terms": 5}})
    settings.load({"params": {"label_terms": 5}, "labels": False})
    assert events == [frozenset({"label_terms"}), frozenset({"labels"})]

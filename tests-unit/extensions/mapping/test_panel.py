from PySide6 import QtCore

from extensions.mapping.panel import MappingPanel, MappingPlugin
from extensions.mapping.view_settings import ViewSettings
from extensions.mapping.widget import MappingWidget


def test_plugin_identity():
    assert MappingPlugin.NAME == "mapping"
    assert MappingPlugin.DISPLAY_NAME == "Mapping"


def test_plugin_restores_the_shared_view_settings_before_the_widget_exists(qtbot):
    plugin = MappingPlugin()
    plugin.restore_ui_state({"view": {"params": {"point_size": 6}}})
    settings = ViewSettings.instance()
    assert settings.params.point_size == 6 and "view" not in MappingPlugin.saved_state
    widget = plugin.create_widget()
    qtbot.addWidget(widget)
    assert isinstance(widget, MappingPanel)
    assert widget.map_tab.toolbar.tuning.params().point_size == 6 == widget.settings_tab.toolbar.tuning.params().point_size
    assert plugin.save_ui_state()["view"]["params"]["point_size"] == 6
    MappingPlugin.saved_state = {}
    widget.close()


def test_shared_view_settings_keep_only_the_gear_values():
    assert set(ViewSettings.instance().to_dict()) == {"params", "image_scale"}


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
    settings.load({"params": {"label_terms": 5}, "image_scale": 2.0})
    assert events == [frozenset({"label_terms"}), frozenset({"image_scale"})]


def test_mapping_is_one_panel_with_a_map_and_a_settings_tab(qtbot):
    panel = MappingPlugin().create_widget()
    qtbot.addWidget(panel)
    assert isinstance(panel, MappingPanel)
    assert [panel.tabs.tabText(i) for i in range(panel.tabs.count())] == ["Map", "Settings"]
    assert panel.current_map() is panel.map_tab and isinstance(panel.map_tab, MappingWidget)
    panel.show_settings()
    assert panel.current_map() is panel.settings_tab
    MappingPlugin.saved_state = {}


def test_panel_state_keeps_the_tab_and_both_tabs(qtbot):
    panel = MappingPanel()
    qtbot.addWidget(panel)
    panel.show_settings()
    panel.settings_tab.tab.set_labels_shown(False)
    panel.map_tab.tab.set_selection_mode("group")
    state = panel.save_state()
    other = MappingPanel()
    qtbot.addWidget(other)
    other.restore_state(state)
    assert other.tabs.currentIndex() == 1 and not other.settings_tab.tab.labels_shown
    assert other.map_tab.tab.selection_mode == "group" and other.settings_tab.tab.selection_mode == "single"


def test_switching_tabs_hides_the_hover(qtbot):
    panel = MappingPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.map_tab.host.show_hover("c:/1.png", QtCore.QPoint(300, 300))
    assert panel.map_tab.host.preview.isVisible()
    panel.show_settings()
    assert not panel.map_tab.host.preview.isVisible()
    panel.close()

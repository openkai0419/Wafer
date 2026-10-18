from __future__ import annotations

from typing import Any

from PySide6 import QtWidgets

from wafer.core.lang.manager import t
from wafer.core.logs import AppLogger
from wafer.plugin import BasePanelPlugin
from wafer.qt.commands.binding.instance_registry import InstanceRegistry

from .space_panel import MappingSpaceWidget
from .view_settings import ViewSettings
from .widget import MappingWidget

VIEW_STATE_KEY = "view"
MAP_TAB, SETTINGS_TAB = 0, 1


class MappingPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        InstanceRegistry.instance().register("MappingPanel", self)
        self.tabs = QtWidgets.QTabWidget()
        self.map_tab = MappingWidget()
        self.settings_tab = MappingSpaceWidget()
        self.tabs.addTab(self.map_tab, t("Map"))
        self.tabs.addTab(self.settings_tab, t("Settings"))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)

    @classmethod
    def instance(cls) -> MappingPanel | None:
        return InstanceRegistry.instance().get_one("MappingPanel")

    def show_map(self) -> None:
        self.tabs.setCurrentIndex(MAP_TAB)

    def show_settings(self) -> None:
        self.tabs.setCurrentIndex(SETTINGS_TAB)

    def current_map(self) -> MappingWidget | MappingSpaceWidget:
        return self.settings_tab if self.tabs.currentIndex() == SETTINGS_TAB else self.map_tab

    def save_state(self) -> dict[str, Any]:
        return {"map": self.map_tab.save_state(), "settings": self.settings_tab.save_state(), "tab": self.tabs.currentIndex()}

    def restore_state(self, state: dict[str, Any]) -> None:
        for key, tab in (("map", self.map_tab), ("settings", self.settings_tab)):
            if isinstance(state.get(key), dict):
                tab.restore_state(state[key])
        if state.get("tab") in (MAP_TAB, SETTINGS_TAB):
            self.tabs.setCurrentIndex(state["tab"])


class MappingPlugin(BasePanelPlugin):
    NAME = "mapping"
    DISPLAY_NAME = "Mapping"
    PRIORITY = 0
    DEFAULT_ENABLED = True
    STANDALONE_AVAILABLE = True
    STANDALONE_SIZE = (1100, 700)
    saved_state: dict[str, Any] = {}

    def save_ui_state(self) -> dict[str, Any]:
        panel = MappingPanel.instance()
        if panel is not None:
            try:
                MappingPlugin.saved_state = panel.save_state()
            except RuntimeError as e:
                AppLogger.warning("[Mapping] Saving panel state failed", exc=e)
        return {**MappingPlugin.saved_state, VIEW_STATE_KEY: ViewSettings.instance().to_dict()}

    def restore_ui_state(self, state: dict[str, Any]) -> None:
        MappingPlugin.saved_state = dict(state or {})
        view = MappingPlugin.saved_state.pop(VIEW_STATE_KEY, None)
        if isinstance(view, dict):
            ViewSettings.instance().load(view)
        panel = MappingPanel.instance()
        if panel is not None:
            panel.restore_state(MappingPlugin.saved_state)

    def create_widget(self):
        panel = MappingPanel()
        panel.restore_state(MappingPlugin.saved_state)
        return panel

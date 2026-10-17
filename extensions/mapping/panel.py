from __future__ import annotations

from typing import Any

from wafer.core.logs import AppLogger
from wafer.plugin import BasePanelPlugin

from .view_settings import ViewSettings
from .widget import MappingWidget

VIEW_STATE_KEY = "view"


class MappingPlugin(BasePanelPlugin):
    NAME = "mapping"
    DISPLAY_NAME = "Mapping"
    PRIORITY = 0
    DEFAULT_ENABLED = True
    STANDALONE_AVAILABLE = True
    STANDALONE_SIZE = (1100, 700)
    saved_state: dict[str, Any] = {}

    def save_ui_state(self) -> dict[str, Any]:
        widget = MappingWidget.instance()
        if widget is not None:
            try:
                MappingPlugin.saved_state = widget.save_state()
            except RuntimeError as e:
                AppLogger.warning("[Mapping] Saving panel state failed", exc=e)
        return {**MappingPlugin.saved_state, VIEW_STATE_KEY: ViewSettings.instance().to_dict()}

    def restore_ui_state(self, state: dict[str, Any]) -> None:
        MappingPlugin.saved_state = dict(state or {})
        view = MappingPlugin.saved_state.pop(VIEW_STATE_KEY, None)
        if isinstance(view, dict):
            ViewSettings.instance().load(view)
        widget = MappingWidget.instance()
        if widget is not None:
            widget.restore_state(MappingPlugin.saved_state)

    def create_widget(self):
        widget = MappingWidget()
        widget.restore_state(MappingPlugin.saved_state)
        return widget

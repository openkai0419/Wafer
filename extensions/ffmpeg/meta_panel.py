from __future__ import annotations

from PySide6 import QtWidgets

from wafer.plugin import BaseMetaPanelPlugin
from wafer.ui.panel.meta_viewer import CollapsibleCard
from wafer.ui.panel.searchable_meta_widget import SearchableMetaWidget


class FFmpegMetaPanelPlugin(BaseMetaPanelPlugin):
    NAME = "ffmpeg_meta_panel"
    PREFIX = "ffmpeg"
    DEFAULT_ENABLED = True
    PRIORITY = 50

    def __init__(self):
        self._card: CollapsibleCard | None = None
        self._widget: SearchableMetaWidget | None = None

    def create_card(self, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QWidget:
        self._card = CollapsibleCard(self.PREFIX, self.PREFIX, parent)
        self._widget = SearchableMetaWidget(self._card)
        self._card.set_content_widget(self._widget)
        return self._card

    def update_data(self, data: dict) -> None:
        if self._widget is not None:
            self._widget.set_data(data)
        if self._card is not None:
            self._card.update_title_count(len(data))

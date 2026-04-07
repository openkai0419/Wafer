from __future__ import annotations

from abc import ABC, abstractmethod

from PySide6 import QtWidgets

from ..registry import PluginBase


class BasePanelPlugin(PluginBase, ABC):
    DISPLAY_NAME: str = ""
    CLOSABLE: bool = True

    @abstractmethod
    def create_widget(self) -> QtWidgets.QWidget: ...

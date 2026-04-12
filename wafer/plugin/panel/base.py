from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from PySide6 import QtWidgets

from ..registry import PluginBase


class BasePanelPlugin(PluginBase, ABC):
    DISPLAY_NAME: str = ""
    CLOSABLE: bool = True
    SOURCE: str = "Plugin"

    @abstractmethod
    def create_widget(self) -> QtWidgets.QWidget: ...

    def save_state(self) -> dict[str, Any]:
        return {}

    def restore_state(self, state: dict[str, Any]) -> None:
        pass

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, TYPE_CHECKING

from PySide6 import QtWidgets

from ..registry import PluginBase

if TYPE_CHECKING:
    from ..config import PluginConfig


class BasePanelPlugin(PluginBase, ABC):
    DISPLAY_NAME: str = ""
    CLOSABLE: bool = True
    SOURCE: str = "Plugin"

    plugin_config: ClassVar[PluginConfig | None] = None

    @abstractmethod
    def create_widget(self) -> QtWidgets.QWidget: ...

    def startup(self) -> None:
        pass

    def save_ui_state(self) -> dict[str, Any]:
        return {}

    def restore_ui_state(self, state: dict[str, Any]) -> None:
        pass

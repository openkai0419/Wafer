from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from PySide6 import QtWidgets

from ..registry import PluginBase


class BaseKeyValuePanelPlugin(PluginBase, ABC):
    PREFIX: str = ""
    DATA_SCOPE: str = "*"

    @abstractmethod
    def create_card(self, parent: QtWidgets.QWidget | None = None, *, scope: str = "meta_info") -> QtWidgets.QWidget: ...

    @abstractmethod
    def update_data(
        self,
        data: dict,
        locks: dict[str, bool] | None = None,
        path: str = "",
        file_hash: str = "",
        db: str = "",
        *,
        scope: str = "meta_info",
    ) -> None: ...

    def save_ui_state(self) -> dict[str, Any]:
        return {}

    def restore_ui_state(self, state: dict[str, Any]) -> None:
        pass

    def shutdown(self) -> None:
        return None

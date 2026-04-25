from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from PySide6 import QtWidgets

from ..registry import PluginBase


class BaseTagPanelPlugin(PluginBase, ABC):
    PREFIX: str = ""

    @abstractmethod
    def create_card(self, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QWidget: ...

    @abstractmethod
    def update_data(
        self,
        tags: dict[str, str],
        locks: dict[str, bool],
        path: str,
        file_hash: str,
        db: str,
    ) -> None: ...

    def save_state(self) -> dict[str, Any]:
        return {}

    def restore_state(self, state: dict[str, Any]) -> None:
        pass

from __future__ import annotations

from abc import ABC, abstractmethod

from PySide6 import QtWidgets

from ..registry import PluginBase


class BaseMetaPanelPlugin(PluginBase, ABC):
    PREFIX: str = ""

    @abstractmethod
    def create_card(self, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QWidget: ...

    @abstractmethod
    def update_data(self, data: dict) -> None: ...

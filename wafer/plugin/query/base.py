from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from PySide6 import QtCore

if TYPE_CHECKING:
    from PySide6 import QtWidgets


class KeyStore(QtCore.QObject):
    updated = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[tuple[str, int]] = []

    @property
    def data(self) -> list[tuple[str, int]]:
        return self._data

    def set_data(self, results: list[tuple[str, int]]):
        self._data = results
        self.updated.emit(results)


class BaseFilterPlugin(ABC):
    NAME: str = ''
    DISPLAY_NAME: str = ''
    PRIORITY: int = 0
    SCOPE: str = 'row'

    @classmethod
    @abstractmethod
    def build_path_query(cls, params: dict, normalize_path) -> tuple[str | None, list]:
        ...

    @classmethod
    def post_filter(cls, params: dict, rows: list) -> list:
        return rows

    @classmethod
    def required_columns(cls) -> tuple[str, ...]:
        return ()

    @classmethod
    def create_widget(cls, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QWidget | None:
        return None

    @classmethod
    def read_params(cls, widget: QtWidgets.QWidget) -> dict:
        return {}

    @classmethod
    def write_params(cls, widget: QtWidgets.QWidget, params: dict) -> None:
        pass

    @classmethod
    def bind_key_store(cls, widget: QtWidgets.QWidget, key_store: KeyStore) -> None:
        pass


class BaseSortPlugin(ABC):
    NAME: str = ''
    PRIORITY: int = 0
    SQL_COLUMN: str | None = None

    @classmethod
    def sort_rows(cls, rows: list, ascending: bool) -> list:
        raise NotImplementedError

    @classmethod
    def required_columns(cls) -> tuple[str, ...]:
        return ()

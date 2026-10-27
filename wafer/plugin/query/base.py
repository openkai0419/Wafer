from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..registry import PluginBase

if TYPE_CHECKING:
    from PySide6 import QtWidgets

    from .widgets import KeyStore


class PathScope:
    CTE_NAME = "_scope"

    def __init__(self, sql: str | None = None, params: list | None = None):
        self.sql = sql
        self.params = list(params or [])

    @property
    def restricted(self) -> bool:
        return self.sql is not None

    def condition(self, path_expr: str) -> str:
        if not self.restricted:
            return "1"
        return f"{path_expr} IN (SELECT path FROM {self.CTE_NAME})"


class BaseFilterPlugin(PluginBase, ABC):
    DISPLAY_NAME: str = ""
    QUERY_SCOPE: str = "row"
    INTERNAL_FILTER: bool = False

    @classmethod
    @abstractmethod
    def build_path_query(cls, params: dict, normalize_path, scope: PathScope) -> tuple[str | None, list]: ...

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
    def inheritable_params(cls, params: dict) -> dict:
        return {}

    @classmethod
    def bind_key_store(cls, widget: QtWidgets.QWidget, key_store: KeyStore) -> None:
        bind = getattr(widget, "bind_key_store", None)
        if callable(bind):
            bind(key_store)


class BaseSortPlugin(PluginBase, ABC):
    META_KEY: str | None = None
    SORT_COLUMN: str | None = None

    @classmethod
    def sort_rows(cls, rows: list, ascending: bool) -> list:
        raise NotImplementedError

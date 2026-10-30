from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..registry import PluginBase

if TYPE_CHECKING:
    from PySide6 import QtWidgets

    from .widgets import KeyStore


class BaseFilterPlugin(PluginBase, ABC):
    DISPLAY_NAME: str = ""
    QUERY_SCOPE: str = "row"
    INTERNAL_FILTER: bool = False

    @classmethod
    @abstractmethod
    def build_path_query(cls, params: dict, normalize_path) -> tuple[str | None, list]: ...

    @classmethod
    def build_path_condition(cls, params: dict, normalize_path, column: str = "path") -> tuple[str | None, list]:
        sql, bind = cls.build_path_query(params, normalize_path)
        if sql is None:
            return None, []
        return f"{column} IN ({sql})", list(bind)

    @classmethod
    def post_filter(cls, params: dict, rows: list) -> list:
        return rows

    @classmethod
    def has_post_filter(cls) -> bool:
        return cls.post_filter.__func__ is not BaseFilterPlugin.post_filter.__func__

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

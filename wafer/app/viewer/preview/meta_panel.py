from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6 import QtCore, QtWidgets

from ....utils.formatting import dpix
from ....core.state import StateStore
from .meta_viewer import MetaRowWidget, CollapsibleSection

_FIXED_SECTIONS = [
    ("source", "Source"),
    ("file", "File"),
    ("tag", "Tag"),
]


class MetaViewerWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sections: dict[str, CollapsibleSection] = {}
        self._collapse_state: dict[str, bool] = {}
        self._meta_panel_plugins: dict[str, Any] | None = None

        self._inner = QtWidgets.QWidget()
        self._inner.setObjectName("metaViewerInner")
        self._inner.setStyleSheet("QWidget#metaViewerInner { background: transparent; }")
        self._layout = QtWidgets.QVBoxLayout(self._inner)
        self._layout.setContentsMargins(0, dpix(5), dpix(4), dpix(5))
        self._layout.setSpacing(dpix(8))
        self._layout.addStretch(1)

        self._area = QtWidgets.QScrollArea(self)
        self._area.setWidgetResizable(True)
        self._area.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._area.setWidget(self._inner)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._area)

        store = StateStore.instance()
        store.register("meta_viewer_collapse", self._save_collapse_state, self._restore_collapse_state)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(dpix(760), super().sizeHint().height())

    def set_data(self, meta: dict[str, Any]):
        prefixed: dict[str, dict] = meta.get("prefixed", {})
        section_order = [key for key, _ in _FIXED_SECTIONS] + sorted(prefixed.keys())

        existing_keys = list(self._sections.keys())
        if existing_keys == section_order:
            self._update_existing(meta, prefixed)
            return

        self._rebuild(meta, prefixed, section_order)

    def _resolve_meta_panel_plugins(self) -> dict[str, Any]:
        if self._meta_panel_plugins is not None:
            return self._meta_panel_plugins
        try:
            from ....plugin.meta_panel.handler import meta_panel_registry

            plugins: dict[str, Any] = {}
            for plugin_cls in meta_panel_registry.list_all():
                inst = meta_panel_registry.instance(plugin_cls.NAME)
                if inst is not None:
                    plugins[inst.PREFIX] = inst
            self._meta_panel_plugins = plugins
        except Exception:
            self._meta_panel_plugins = {}
        return self._meta_panel_plugins

    def _rebuild(self, meta: dict, prefixed: dict[str, dict], section_order: list[str]):
        for sec in self._sections.values():
            self._layout.removeWidget(sec)
            sec.setParent(None)
            sec.deleteLater()
        self._sections.clear()

        plugins = self._resolve_meta_panel_plugins()

        rich_text_keys = {"collected by"}

        for key in section_order:
            title = self._section_title(key)
            section = CollapsibleSection(title, key, parent=self._inner)

            data = self._data_for_key(meta, prefixed, key)
            content = self._create_content_widget(key, data, plugins, rich_text_keys, section)
            section.set_content_widget(content)
            section.update_title_count(len(data) if isinstance(data, Mapping) else 0)

            expanded = self._collapse_state.get(key, True)
            section.set_expanded(expanded)
            section.toggled.connect(self._on_section_toggled)

            self._sections[key] = section
            self._layout.insertWidget(self._layout.count() - 1, section)

    def _update_existing(self, meta: dict, prefixed: dict[str, dict]):
        rich_text_keys = {"collected by"}
        plugins = self._resolve_meta_panel_plugins()

        for key, section in self._sections.items():
            data = self._data_for_key(meta, prefixed, key)
            content = section.content_widget()

            if key in plugins:
                plugins[key].update_data(data)
            elif isinstance(content, MetaRowWidget):
                content.update_data(data)
            else:
                new_content = self._create_content_widget(key, data, plugins, rich_text_keys, section)
                section.set_content_widget(new_content)

            section.update_title_count(len(data) if isinstance(data, Mapping) else 0)

    def _create_content_widget(
        self,
        key: str,
        data: dict,
        plugins: dict[str, Any],
        rich_text_keys: set[str],
        parent: QtWidgets.QWidget,
    ) -> QtWidgets.QWidget:
        if key in plugins:
            plugin = plugins[key]
            widget = plugin.create_widget(parent)
            plugin.update_data(data)
            return widget

        return MetaRowWidget(
            0,
            data,
            rich_text_keys=rich_text_keys if key == "source" else None,
            compact=True,
            parent=parent,
        )

    def _data_for_key(self, meta: dict, prefixed: dict[str, dict], key: str) -> dict:
        if key in ("source", "file", "tag"):
            return meta.get(key, {})
        return prefixed.get(key, {})

    def _section_title(self, key: str) -> str:
        for k, title in _FIXED_SECTIONS:
            if k == key:
                return title
        return key.capitalize()

    def _on_section_toggled(self, key: str, expanded: bool):
        self._collapse_state[key] = expanded

    def _save_collapse_state(self) -> dict[str, Any]:
        return {"collapsed": {k: v for k, v in self._collapse_state.items() if not v}}

    def _restore_collapse_state(self, state: dict[str, Any]):
        collapsed = state.get("collapsed", {})
        self._collapse_state = {k: v for k, v in collapsed.items()}
        for key, section in self._sections.items():
            expanded = self._collapse_state.get(key, True)
            section.set_expanded(expanded)

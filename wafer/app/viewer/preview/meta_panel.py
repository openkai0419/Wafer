from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6 import QtCore, QtWidgets

from ....utils.formatting import dpix
from ....utils.logs import AppLogger
from ....core.state import StateStore
from ....core.color.theme import ThemeManager
from ....core.lang.manager import t
from ....ui.panel.meta_viewer import MetaRowWidget, CollapsibleCard
from .editable_tag_card import EditableTagCard

_FIXED_SECTION_KEYS = ("source", "file", "tag")


class MetaViewerWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sections: dict[str, CollapsibleCard | QtWidgets.QWidget] = {}
        self._collapse_state: dict[str, bool] = {}
        self._meta_panel_plugins: dict[str, Any] | None = None

        self._inner = QtWidgets.QWidget()
        self._inner.setObjectName("metaViewerInner")
        self._inner.setStyleSheet("QWidget#metaViewerInner { background: transparent; }")
        self._layout = QtWidgets.QVBoxLayout(self._inner)
        self._layout.setContentsMargins(0, dpix(5), dpix(4), dpix(5))
        self._layout.setSpacing(dpix(4))

        self._placeholder = QtWidgets.QLabel()
        self._placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self._update_placeholder_style()
        self._layout.addWidget(self._placeholder)

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

        ThemeManager.instance().on_theme_changed.connect(lambda _: self._update_placeholder_style())

    def _update_placeholder_style(self):
        p = ThemeManager.instance().palette
        fs = dpix(13)
        self._placeholder.setText(t("No metadata"))
        self._placeholder.setStyleSheet(f"QLabel {{ color: {p.text_muted}; font-size: {fs}px; }}")

    def clear(self):
        for sec in self._sections.values():
            sec.hide()
        self._placeholder.show()

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(dpix(760), super().sizeHint().height())

    def set_data(self, meta: dict[str, Any]):
        self._placeholder.hide()
        for sec in self._sections.values():
            sec.show()
        prefixed: dict[str, dict] = meta.get("prefixed", {})
        section_order = list(_FIXED_SECTION_KEYS) + sorted(prefixed.keys())

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
        except Exception as e:
            AppLogger.warning(f"Meta panel plugin load failed: {e}", exc=e)
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
            data = self._data_for_key(meta, prefixed, key)

            if key == "tag":
                card = EditableTagCard(parent=self._inner)
                self._update_tag_card(card, meta)
            elif key in plugins:
                card = plugins[key].create_card(self._inner)
                plugins[key].update_data(data)
            else:
                card = CollapsibleCard(key, key, parent=self._inner)
                content = MetaRowWidget(
                    0,
                    data,
                    rich_text_keys=rich_text_keys if key == "source" else None,
                    compact=True,
                    parent=card,
                )
                card.set_content_widget(content)
                card.update_title_count(len(data) if isinstance(data, Mapping) else 0)

            expanded = self._collapse_state.get(key, True)
            if isinstance(card, CollapsibleCard):
                card.set_expanded(expanded)
                card.toggled_card.connect(self._on_section_toggled)

            self._sections[key] = card
            self._layout.insertWidget(self._layout.count() - 1, card)

    def _update_existing(self, meta: dict, prefixed: dict[str, dict]):
        rich_text_keys = {"collected by"}
        plugins = self._resolve_meta_panel_plugins()

        for key, card in self._sections.items():
            data = self._data_for_key(meta, prefixed, key)

            if key == "tag" and isinstance(card, EditableTagCard):
                self._update_tag_card(card, meta)
                continue
            if key in plugins:
                plugins[key].update_data(data)
            elif isinstance(card, CollapsibleCard):
                content = card.content_widget()
                if isinstance(content, MetaRowWidget):
                    content.update_data(data)
                else:
                    new_content = MetaRowWidget(
                        0,
                        data,
                        rich_text_keys=rich_text_keys if key == "source" else None,
                        compact=True,
                        parent=card,
                    )
                    card.set_content_widget(new_content)
                card.update_title_count(len(data) if isinstance(data, Mapping) else 0)

    def _data_for_key(self, meta: dict, prefixed: dict[str, dict], key: str) -> dict:
        if key in _FIXED_SECTION_KEYS:
            return meta.get(key, {})
        return prefixed.get(key, {})

    def _update_tag_card(self, card: EditableTagCard, meta: dict):
        tags = meta.get("tag", {}) or {}
        locks = meta.get("_tag_locks", {}) or {}
        path = meta.get("_path", "") or ""
        file_hash = meta.get("_file_hash", "") or ""
        db = meta.get("_db_name", "") or ""
        card.update_data(tags, locks, None, path, file_hash, db)

    def _on_section_toggled(self, key: str, expanded: bool):
        self._collapse_state[key] = expanded

    def _save_collapse_state(self) -> dict[str, Any]:
        return {"collapsed": {k: v for k, v in self._collapse_state.items() if not v}}

    def _restore_collapse_state(self, state: dict[str, Any]):
        collapsed = state.get("collapsed", {})
        self._collapse_state = {k: v for k, v in collapsed.items()}
        for key, card in self._sections.items():
            if isinstance(card, CollapsibleCard):
                expanded = self._collapse_state.get(key, True)
                card.set_expanded(expanded)

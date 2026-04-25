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
_TAG_PREFIX = "tag:"
_META_PREFIX = "meta:"


class MetaViewerWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sections: dict[str, CollapsibleCard | QtWidgets.QWidget] = {}
        self._collapse_state: dict[str, bool] = {}
        self._meta_panel_plugins: dict[str, Any] | None = None
        self._tag_panel_plugins: dict[str, Any] | None = None

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
        meta_prefixed: dict[str, dict] = meta.get("prefixed", {}) or {}
        tag_prefixed: dict[str, dict] = meta.get("tag_prefixed", {}) or {}

        section_order = list(_FIXED_SECTION_KEYS)
        section_order += [_TAG_PREFIX + p for p in self._ordered_prefixes(tag_prefixed, self._resolve_tag_panel_plugins())]
        section_order += [_META_PREFIX + p for p in self._ordered_prefixes(meta_prefixed, self._resolve_meta_panel_plugins())]

        existing_keys = list(self._sections.keys())
        if existing_keys == section_order:
            self._update_existing(meta, meta_prefixed, tag_prefixed)
            return

        self._rebuild(meta, meta_prefixed, tag_prefixed, section_order)

    def _ordered_prefixes(self, data: dict[str, dict], plugins: dict[str, Any]) -> list[str]:
        prefixes = set(data.keys())
        ordered = [p for p in plugins if p in prefixes]
        ordered += sorted(prefixes - set(ordered))
        return ordered

    def _resolve_plugins(self, attr: str, registry_loader) -> dict[str, Any]:
        cached = getattr(self, attr)
        if cached is not None:
            return cached
        try:
            registry = registry_loader()
            plugins: dict[str, Any] = {}
            for plugin_cls in registry.list_all():
                inst = registry.instance(plugin_cls.NAME)
                if inst is not None:
                    plugins[inst.PREFIX] = inst
            setattr(self, attr, plugins)
        except Exception as e:
            AppLogger.warning(f"Plugin load failed for {attr}: {e}", exc=e)
            setattr(self, attr, {})
        return getattr(self, attr)

    def _resolve_meta_panel_plugins(self) -> dict[str, Any]:
        def _load():
            from ....plugin.meta_panel.handler import meta_panel_registry

            return meta_panel_registry

        return self._resolve_plugins("_meta_panel_plugins", _load)

    def _resolve_tag_panel_plugins(self) -> dict[str, Any]:
        def _load():
            from ....plugin.tag_panel.handler import tag_panel_registry

            return tag_panel_registry

        return self._resolve_plugins("_tag_panel_plugins", _load)

    def _rebuild(self, meta: dict, meta_prefixed: dict[str, dict], tag_prefixed: dict[str, dict], section_order: list[str]):
        for sec in self._sections.values():
            self._layout.removeWidget(sec)
            sec.setParent(None)
            sec.deleteLater()
        self._sections.clear()

        meta_plugins = self._resolve_meta_panel_plugins()
        tag_plugins = self._resolve_tag_panel_plugins()
        rich_text_keys = {"collected by"}

        for key in section_order:
            if key == "tag":
                card = EditableTagCard(prefix="", parent=self._inner)
                self._update_tag_card(card, meta, prefix="")
            elif key.startswith(_TAG_PREFIX):
                prefix = key[len(_TAG_PREFIX) :]
                plugin = tag_plugins.get(prefix)
                if plugin is not None:
                    card = plugin.create_card(self._inner)
                    self._update_tag_plugin(plugin, meta, tag_prefixed, prefix)
                else:
                    card = EditableTagCard(prefix=prefix, parent=self._inner)
                    self._update_tag_card(card, meta, prefix=prefix, prefixed=tag_prefixed)
            elif key.startswith(_META_PREFIX):
                prefix = key[len(_META_PREFIX) :]
                data = meta_prefixed.get(prefix, {})
                plugin = meta_plugins.get(prefix)
                if plugin is not None:
                    card = plugin.create_card(self._inner)
                    plugin.update_data(data)
                else:
                    card = self._build_generic_card(prefix, data, rich_text_keys=None)
            else:
                data = meta.get(key, {})
                card = self._build_generic_card(key, data, rich_text_keys=rich_text_keys if key == "source" else None)

            expanded = self._collapse_state.get(key, True)
            if isinstance(card, CollapsibleCard):
                card.set_expanded(expanded)
                card.toggled_card.connect(self._on_section_toggled)

            self._sections[key] = card
            self._layout.insertWidget(self._layout.count() - 1, card)

    def _build_generic_card(self, key: str, data, *, rich_text_keys) -> CollapsibleCard:
        card = CollapsibleCard(key, key, parent=self._inner)
        content = MetaRowWidget(
            0,
            data,
            rich_text_keys=rich_text_keys,
            compact=True,
            parent=card,
        )
        card.set_content_widget(content)
        card.update_title_count(len(data) if isinstance(data, Mapping) else 0)
        return card

    def _update_existing(self, meta: dict, meta_prefixed: dict[str, dict], tag_prefixed: dict[str, dict]):
        rich_text_keys = {"collected by"}
        meta_plugins = self._resolve_meta_panel_plugins()
        tag_plugins = self._resolve_tag_panel_plugins()

        for key, card in self._sections.items():
            if key == "tag" and isinstance(card, EditableTagCard):
                self._update_tag_card(card, meta, prefix="")
                continue
            if key.startswith(_TAG_PREFIX):
                prefix = key[len(_TAG_PREFIX) :]
                plugin = tag_plugins.get(prefix)
                if plugin is not None:
                    self._update_tag_plugin(plugin, meta, tag_prefixed, prefix)
                elif isinstance(card, EditableTagCard):
                    self._update_tag_card(card, meta, prefix=prefix, prefixed=tag_prefixed)
                continue
            if key.startswith(_META_PREFIX):
                prefix = key[len(_META_PREFIX) :]
                data = meta_prefixed.get(prefix, {})
                plugin = meta_plugins.get(prefix)
                if plugin is not None:
                    plugin.update_data(data)
                else:
                    self._update_generic_card(card, data, rich_text_keys=None)
                continue
            data = meta.get(key, {})
            self._update_generic_card(card, data, rich_text_keys=rich_text_keys if key == "source" else None)

    def _update_generic_card(self, card, data, *, rich_text_keys):
        if not isinstance(card, CollapsibleCard):
            return
        content = card.content_widget()
        if isinstance(content, MetaRowWidget):
            content.update_data(data)
        else:
            new_content = MetaRowWidget(
                0,
                data,
                rich_text_keys=rich_text_keys,
                compact=True,
                parent=card,
            )
            card.set_content_widget(new_content)
        card.update_title_count(len(data) if isinstance(data, Mapping) else 0)

    def _update_tag_card(self, card: EditableTagCard, meta: dict, *, prefix: str, prefixed: dict[str, dict] | None = None):
        path = meta.get("_path", "") or ""
        file_hash = meta.get("_file_hash", "") or ""
        db = meta.get("_db_name", "") or ""
        if prefix:
            tags = (prefixed or {}).get(prefix, {}) or {}
            locks = (meta.get("tag_prefixed_locks", {}) or {}).get(prefix, {}) or {}
        else:
            tags = meta.get("tag", {}) or {}
            locks = meta.get("_tag_locks", {}) or {}
        card.update_data(tags, locks, None, path, file_hash, db)

    def _update_tag_plugin(self, plugin, meta: dict, tag_prefixed: dict[str, dict], prefix: str):
        tags = tag_prefixed.get(prefix, {}) or {}
        locks = (meta.get("tag_prefixed_locks", {}) or {}).get(prefix, {}) or {}
        path = meta.get("_path", "") or ""
        file_hash = meta.get("_file_hash", "") or ""
        db = meta.get("_db_name", "") or ""
        plugin.update_data(tags, locks, path, file_hash, db)

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

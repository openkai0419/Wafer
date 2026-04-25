from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6 import QtCore, QtWidgets

from ....utils.formatting import dpix
from ....utils.logs import AppLogger
from ....core.state import StateStore
from ....core.color.theme import ThemeManager
from ....core.qt.icon_engine import themed_icon
from ....core.lang.manager import t
from ....ui.panel.meta_viewer import MetaRowWidget, CollapsibleCard
from .editable_tag_card import EditableTagCard, AddTagDialog
from .tag_edit_service import TagEditService

_FIXED_SECTION_KEYS = ("source", "file")
_TAG_PREFIX = "tag:"
_META_PREFIX = "meta:"
_TAG_ROOT_KEY = "tag"


class MetaViewerWidget(QtWidgets.QWidget):
    reload_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sections: dict[str, CollapsibleCard | QtWidgets.QWidget] = {}
        self._collapse_state: dict[str, bool] = {}
        self._meta_panel_plugins: dict[str, Any] | None = None
        self._tag_panel_plugins: dict[str, Any] | None = None
        self._current_path: str = ""
        self._current_file_hash: str = ""
        self._current_db: str = ""

        self._inner = QtWidgets.QWidget()
        self._inner.setObjectName("metaViewerInner")
        self._inner.setStyleSheet("QWidget#metaViewerInner { background: transparent; }")
        self._layout = QtWidgets.QVBoxLayout(self._inner)
        self._layout.setContentsMargins(0, dpix(5), dpix(4), dpix(5))
        self._layout.setSpacing(dpix(4))

        self._header = self._build_header()
        self._layout.addWidget(self._header)
        self._header.setVisible(False)

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
        TagEditService.instance().commit_confirmed.connect(self._on_tag_commit_confirmed)

    def _on_tag_commit_confirmed(self, file_hash: str, _applied: dict, _deleted: list):
        if file_hash and file_hash == self._current_file_hash:
            self.reload_requested.emit()

    def _build_header(self) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget(self)
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, dpix(4), 0)
        lay.setSpacing(dpix(4))
        lay.addStretch(1)

        self._reload_btn = QtWidgets.QToolButton(bar)
        self._reload_btn.setIcon(themed_icon("refresh", margin=0.1))
        self._reload_btn.setAutoRaise(True)
        self._reload_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._reload_btn.setToolTip(t("Reload metadata"))
        self._reload_btn.clicked.connect(self.reload_requested.emit)

        self._add_tag_btn = QtWidgets.QToolButton(bar)
        self._add_tag_btn.setIcon(themed_icon("plus"))
        self._add_tag_btn.setAutoRaise(True)
        self._add_tag_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._add_tag_btn.setToolTip(t("Add new tag"))
        self._add_tag_btn.clicked.connect(self._on_add_tag_clicked)

        lay.addWidget(self._reload_btn)
        lay.addWidget(self._add_tag_btn)
        return bar

    def _update_placeholder_style(self):
        p = ThemeManager.instance().palette
        fs = dpix(13)
        self._placeholder.setText(t("No metadata"))
        self._placeholder.setStyleSheet(f"QLabel {{ color: {p.text_muted}; font-size: {fs}px; }}")

    def clear(self):
        for sec in self._sections.values():
            sec.hide()
        self._placeholder.show()
        self._header.setVisible(False)
        self._current_path = ""
        self._current_file_hash = ""
        self._current_db = ""

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(dpix(760), super().sizeHint().height())

    def set_data(self, meta: dict[str, Any]):
        self._placeholder.hide()
        self._header.setVisible(True)
        self._current_path = meta.get("_path", "") or ""
        self._current_file_hash = meta.get("_file_hash", "") or ""
        self._current_db = meta.get("_db_name", "") or ""
        for sec in self._sections.values():
            sec.show()
        meta_prefixed: dict[str, dict] = meta.get("prefixed", {}) or {}
        tag_prefixed: dict[str, dict] = meta.get("tag_prefixed", {}) or {}
        tag_root: dict = meta.get("tag", {}) or {}

        section_order = list(_FIXED_SECTION_KEYS)
        if tag_root:
            section_order.append(_TAG_ROOT_KEY)
        tag_prefixes = self._ordered_prefixes(tag_prefixed, self._resolve_tag_panel_plugins())
        section_order += [_TAG_PREFIX + p for p in tag_prefixes]
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

    def _on_add_tag_clicked(self):
        if not self._current_path or not self._current_db or not self._current_file_hash:
            AppLogger.warning(f"[MetaViewer] add tag aborted: missing context path={bool(self._current_path)} hash={bool(self._current_file_hash)} db={bool(self._current_db)}")
            return
        existing_keys = self._existing_full_keys()
        dlg = AddTagDialog(self, existing_keys)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        key, value = dlg.values()
        key = key.strip()
        if not key:
            return
        key = self._dedupe_full_key(key, existing_keys)
        rid = TagEditService.instance().submit(
            [self._current_path],
            [(key, value, False)],
            [],
            self._current_db,
            file_hash=self._current_file_hash,
        )
        if rid is None:
            return
        AppLogger.info(f"[MetaViewer] add tag submitted key={key}")

    def _existing_full_keys(self) -> set[str]:
        keys: set[str] = set()
        for card in self._sections.values():
            if not isinstance(card, EditableTagCard):
                continue
            keys.update(card.iter_full_keys())
        return keys

    @staticmethod
    def _dedupe_full_key(key: str, used: set[str]) -> str:
        if key not in used:
            return key
        i = 2
        while f"{key}_{i}" in used:
            i += 1
        return f"{key}_{i}"

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

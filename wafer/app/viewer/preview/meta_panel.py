from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6 import QtCore, QtWidgets

from ....utils.formatting import dpix
from ....utils.logs import AppLogger
from ....core.state import StateStore
from ....core.db.key_value import DATA_SCOPES, SCOPE_ALL, normalize_data_scope
from ....core.color.theme import ThemeManager
from ....core.qt.icon_engine import themed_icon
from ....core.lang.manager import t
from ....ui.panel.meta_viewer import (
    CollapsibleCard,
    MetaRowWidget,
    SECTION_MARKER_META_PREFIX,
    SECTION_MARKER_META_ROOT,
    SECTION_MARKER_TAG_PREFIX,
    SECTION_MARKER_TAG_ROOT,
)
from .searchable_meta_widget import ScopedSearchKvAddDialog, SearchableMetaWidget
from .tag_edit_service import TagEditService

_FIXED_SECTION_KEYS = ("file", "source")
_TAG_PREFIX = "tag:"
_META_PREFIX = "meta:"
_TAG_ROOT_KEY = "tag"
_META_ROOT_KEY = "meta"


class MetaViewerWidget(QtWidgets.QWidget):
    reload_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sections: dict[str, CollapsibleCard | QtWidgets.QWidget] = {}
        self._collapse_state: dict[str, bool] = {}
        self._key_value_panel_plugins: list[type] | None = None
        self._key_value_panel_classes: dict[str, type] = {}
        self._key_value_panel_instances: dict[tuple[str, str], Any] = {}
        self._key_value_panel_cards: dict[tuple[str, str], QtWidgets.QWidget] = {}
        self._pending_key_value_panel_states: dict[str, dict[str, dict[str, Any]]] = {}
        self._key_value_panel_state_names: set[str] = set()
        self._key_value_panel_shutdown = False
        self._section_plugins: dict[str, Any] = {}
        self._current_path: str = ""
        self._current_file_hash: str = ""
        self._current_db: str = ""
        self._current_tag_keys: set[str] = set()
        self._current_meta_keys: set[str] = set()

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
        self._register_key_value_panel_states(store)

        ThemeManager.instance().on_theme_changed.connect(lambda _: self._update_placeholder_style())
        TagEditService.instance().kv_commit_confirmed.connect(self._on_kv_commit_confirmed)
        self.destroyed.connect(lambda _obj=None: self._shutdown_key_value_panel_plugins())

    def _on_kv_commit_confirmed(self, scope: str, target_id: str, _applied: dict, _deleted: list):
        current_target = self._current_file_hash if scope == "tag" else self._current_path
        if target_id and target_id == current_target:
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

        self._add_btn = QtWidgets.QToolButton(bar)
        self._add_btn.setIcon(themed_icon("plus", margin=0.1))
        self._add_btn.setAutoRaise(True)
        self._add_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._add_btn.setToolTip(t("Add tag or metadata"))
        self._add_btn.clicked.connect(self._on_add_clicked)

        lay.addWidget(self._reload_btn)
        lay.addWidget(self._add_btn)
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
        self._current_tag_keys.clear()
        self._current_meta_keys.clear()

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
        meta_prefixed_locks: dict[str, dict] = meta.get("prefixed_locks", {}) or {}
        meta_root: dict = meta.get("meta", {}) or {}
        meta_root_locks: dict = meta.get("meta_locks", {}) or {}
        tag_prefixed: dict[str, dict] = meta.get("tag_prefixed", {}) or {}
        tag_root: dict = meta.get("tag", {}) or {}
        self._current_tag_keys = self._collect_full_keys(tag_root, tag_prefixed)
        self._current_meta_keys = self._collect_full_keys(meta_root, meta_prefixed)

        section_order = list(_FIXED_SECTION_KEYS)
        if tag_root:
            section_order.append(_TAG_ROOT_KEY)
        if meta_root:
            section_order.append(_META_ROOT_KEY)
        tag_prefixes = self._ordered_prefixes(tag_prefixed, "tag")
        section_order += [_TAG_PREFIX + p for p in tag_prefixes]
        section_order += [_META_PREFIX + p for p in self._ordered_prefixes(meta_prefixed, "meta_info")]

        existing_keys = list(self._sections.keys())
        if existing_keys == section_order:
            self._update_existing(meta, meta_root, meta_root_locks, meta_prefixed, meta_prefixed_locks, tag_prefixed)
            return

        self._rebuild(meta, meta_root, meta_root_locks, meta_prefixed, meta_prefixed_locks, tag_prefixed, section_order)

    @staticmethod
    def _collect_full_keys(root: dict, prefixed: dict[str, dict]) -> set[str]:
        keys = set(root or {})
        for prefix, data in (prefixed or {}).items():
            keys.update(f"{prefix}.{key}" for key in (data or {}))
        return keys

    def _on_add_clicked(self):
        if not self._current_path or not self._current_file_hash or not self._current_db:
            AppLogger.warning(f"[MetaViewer] add aborted: missing context path={bool(self._current_path)} file_hash={bool(self._current_file_hash)} db={bool(self._current_db)}")
            return
        self._open_global_add_dialog()

    def _open_global_add_dialog(self):
        existing_by_scope = {"tag": set(self._current_tag_keys), "meta_info": set(self._current_meta_keys)}
        dlg = ScopedSearchKvAddDialog(
            self,
            title=t("Add tag or metadata"),
            existing_keys_by_scope=existing_by_scope,
            duplicate_hint=t("Key already exists; will be auto-renamed on add."),
            scope_options=(
                ("tag", t("Tag (links to filehash)")),
                ("meta_info", t("Metadata (links to path)")),
            ),
            initial_scope="tag",
        )
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        scope = dlg.scope() or "tag"
        existing_keys = existing_by_scope.get(scope, set())
        key = self._dedupe_full_key(dlg.key(), existing_keys)
        if not key:
            return
        rid = TagEditService.instance().submit(
            [self._current_path],
            [(key, dlg.value(), dlg.locked())],
            [],
            self._current_db,
            scope=scope,
            file_hash=self._current_file_hash if scope == "tag" else None,
            target_id=self._current_path if scope == "meta_info" else None,
        )
        if rid is None:
            return
        AppLogger.info(f"[MetaViewer] add submitted scope={scope} key={key}")

    @staticmethod
    def _dedupe_full_key(key: str, used: set[str]) -> str:
        key = key.strip()
        if not key:
            return ""
        if key not in used:
            return key
        i = 2
        while f"{key}_{i}" in used:
            i += 1
        return f"{key}_{i}"

    def _ordered_prefixes(self, data: dict[str, dict], scope: str) -> list[str]:
        remaining = {prefix for prefix, values in data.items() if values}
        ordered: list[str] = []
        for plugin_cls in self._resolve_key_value_panel_plugins():
            if getattr(plugin_cls, "DATA_SCOPE", "*") not in (scope, "*"):
                continue
            prefix = getattr(plugin_cls, "PREFIX", "")
            if prefix not in remaining:
                continue
            ordered.append(prefix)
            remaining.remove(prefix)
        ordered.extend(sorted(remaining))
        return ordered

    def _resolve_key_value_panel_plugins(self) -> list[type]:
        cached = self._key_value_panel_plugins
        if cached is not None:
            return cached
        try:
            from ....plugin.key_value_panel.handler import key_value_panel_registry

            self._key_value_panel_plugins = list(key_value_panel_registry.list_all())
            self._key_value_panel_classes = {cls.NAME: cls for cls in self._key_value_panel_plugins}
        except Exception as e:
            AppLogger.warning(f"Plugin load failed for key/value panels: {e}", exc=e)
            self._key_value_panel_plugins = []
            self._key_value_panel_classes = {}
        return self._key_value_panel_plugins

    def _register_key_value_panel_states(self, store: StateStore):
        for plugin_cls in self._resolve_key_value_panel_plugins():
            name = plugin_cls.NAME
            if not name or name in self._key_value_panel_state_names:
                continue
            self._key_value_panel_state_names.add(name)
            store.register(
                f"key_value_panel_plugin.{name}",
                lambda name=name: self._save_key_value_panel_state(name),
                lambda state, name=name: self._restore_key_value_panel_state(name, state),
            )

    def _save_key_value_panel_state(self, plugin_name: str) -> dict[str, Any]:
        scopes = dict(self._pending_key_value_panel_states.get(plugin_name, {}))
        for (name, scope), plugin in self._key_value_panel_instances.items():
            if name != plugin_name:
                continue
            state = plugin.save_ui_state()
            if state:
                scopes[scope] = state
            else:
                scopes.pop(scope, None)
        return {"scopes": scopes} if scopes else {}

    def _restore_key_value_panel_state(self, plugin_name: str, state: dict[str, Any]):
        if not isinstance(state, dict):
            return
        scopes = state.get("scopes")
        if isinstance(scopes, dict):
            for scope, scope_state in scopes.items():
                self._restore_key_value_panel_scope_state(plugin_name, scope, scope_state)
            return
        plugin_cls = self._key_value_panel_classes.get(plugin_name)
        if plugin_cls is None:
            return
        for scope in self._scopes_for_key_value_panel(plugin_cls):
            self._restore_key_value_panel_scope_state(plugin_name, scope, state)

    def _restore_key_value_panel_scope_state(self, plugin_name: str, scope: str, state: Any):
        if not isinstance(state, dict):
            return
        try:
            scope = normalize_data_scope(scope)
        except ValueError:
            return
        key = (plugin_name, scope)
        plugin = self._key_value_panel_instances.get(key)
        if plugin is not None:
            plugin.restore_ui_state(state)
            return
        self._pending_key_value_panel_states.setdefault(plugin_name, {})[scope] = dict(state)

    def _scopes_for_key_value_panel(self, plugin_cls: type) -> tuple[str, ...]:
        data_scope = getattr(plugin_cls, "DATA_SCOPE", SCOPE_ALL)
        if data_scope == SCOPE_ALL:
            return DATA_SCOPES
        try:
            return (normalize_data_scope(data_scope),)
        except ValueError:
            return ()

    def _plugin_class_for(self, prefix: str, scope: str):
        for plugin_cls in self._resolve_key_value_panel_plugins():
            if getattr(plugin_cls, "PREFIX", "") != prefix:
                continue
            if getattr(plugin_cls, "DATA_SCOPE", "*") in (scope, "*"):
                return plugin_cls
        return None

    def _get_or_create_scope_plugin(self, plugin_cls: type, scope: str):
        scope = normalize_data_scope(scope)
        key = (plugin_cls.NAME, scope)
        plugin = self._key_value_panel_instances.get(key)
        if plugin is not None:
            return plugin
        plugin = plugin_cls()
        self._key_value_panel_instances[key] = plugin
        pending = self._pending_key_value_panel_states.get(plugin_cls.NAME, {}).pop(scope, None)
        if pending is not None:
            try:
                plugin.restore_ui_state(pending)
            except Exception as e:
                AppLogger.warning(f"Key/value panel state restore failed: {plugin_cls.NAME}/{scope}: {e}", exc=e)
        return plugin

    def _get_or_create_scope_card(self, plugin_cls: type, plugin, scope: str, marker_kind: str) -> QtWidgets.QWidget:
        scope = normalize_data_scope(scope)
        key = (plugin_cls.NAME, scope)
        card = self._key_value_panel_cards.get(key)
        if card is not None:
            self._set_section_marker(card, marker_kind)
            return card
        card = plugin.create_card(self._inner, scope=scope)
        self._key_value_panel_cards[key] = card
        self._set_section_marker(card, marker_kind)
        if isinstance(card, CollapsibleCard):
            card.toggled_card.connect(self._on_section_toggled)
        return card

    def _detach_sections_for_rebuild(self):
        plugin_sections = set(self._section_plugins)
        for key, sec in self._sections.items():
            self._layout.removeWidget(sec)
            if key in plugin_sections:
                sec.hide()
            else:
                sec.setParent(None)
                sec.deleteLater()
        self._sections.clear()
        self._section_plugins.clear()

    def _rebuild(
        self, meta: dict, meta_root: dict, meta_root_locks: dict, meta_prefixed: dict[str, dict], meta_prefixed_locks: dict[str, dict], tag_prefixed: dict[str, dict], section_order: list[str]
    ):
        self._detach_sections_for_rebuild()

        rich_text_keys = {"collected by"}

        for key in section_order:
            if key == "tag":
                card = self._build_search_kv_card("tag", "tag", prefix="", scope="tag", marker_kind=SECTION_MARKER_TAG_ROOT)
                self._set_section_marker(card, SECTION_MARKER_TAG_ROOT)
                self._update_tag_card(card, meta, prefix="")
            elif key.startswith(_TAG_PREFIX):
                prefix = key[len(_TAG_PREFIX) :]
                plugin_cls = self._plugin_class_for(prefix, "tag")
                if plugin_cls is not None:
                    plugin = self._get_or_create_scope_plugin(plugin_cls, "tag")
                    self._section_plugins[key] = plugin
                    card = self._get_or_create_scope_card(plugin_cls, plugin, "tag", SECTION_MARKER_TAG_PREFIX)
                    self._update_tag_plugin(plugin, meta, tag_prefixed, prefix)
                else:
                    card = self._build_search_kv_card(prefix, key, prefix=prefix, scope="tag", marker_kind=SECTION_MARKER_TAG_PREFIX)
                    self._set_section_marker(card, SECTION_MARKER_TAG_PREFIX)
                    self._update_tag_card(card, meta, prefix=prefix, prefixed=tag_prefixed)
            elif key == _META_ROOT_KEY:
                card = self._build_search_kv_card("meta", "meta", prefix="", scope="meta_info", marker_kind=SECTION_MARKER_META_ROOT)
                self._set_section_marker(card, SECTION_MARKER_META_ROOT)
                self._update_meta_card(card, meta, prefix="", data=meta_root, locks=meta_root_locks)
            elif key.startswith(_META_PREFIX):
                prefix = key[len(_META_PREFIX) :]
                plugin_cls = self._plugin_class_for(prefix, "meta_info")
                if plugin_cls is not None:
                    plugin = self._get_or_create_scope_plugin(plugin_cls, "meta_info")
                    self._section_plugins[key] = plugin
                    card = self._get_or_create_scope_card(plugin_cls, plugin, "meta_info", SECTION_MARKER_META_PREFIX)
                    self._update_meta_plugin(plugin, meta, meta_prefixed, meta_prefixed_locks, prefix)
                else:
                    card = self._build_search_kv_card(prefix, key, prefix=prefix, scope="meta_info", marker_kind=SECTION_MARKER_META_PREFIX)
                    self._set_section_marker(card, SECTION_MARKER_META_PREFIX)
                    self._update_meta_card(card, meta, prefix=prefix, prefixed=meta_prefixed, locks_by_prefix=meta_prefixed_locks)
            else:
                data = meta.get(key, {})
                card = self._build_generic_card(key, data, rich_text_keys=rich_text_keys if key == "source" else None)

            expanded = self._collapse_state.get(key, True)
            if isinstance(card, CollapsibleCard):
                card.set_expanded(expanded)

            self._sections[key] = card
            self._layout.insertWidget(self._layout.count() - 1, card)
            card.show()

    @staticmethod
    def _set_section_marker(card, marker_kind: str):
        if isinstance(card, CollapsibleCard):
            card.set_marker_kind(marker_kind)

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

    def _build_search_kv_card(self, title: str, section_id: str, *, prefix: str, scope: str, marker_kind: str) -> CollapsibleCard:
        card = CollapsibleCard(title, section_id, parent=self._inner)
        self._set_section_marker(card, marker_kind)
        widget = SearchableMetaWidget(card, scope=scope, prefix=prefix)
        widget.count_changed.connect(card.update_title_count)
        card.set_content_widget(widget)
        card.toggled_card.connect(self._on_section_toggled)
        return card

    def _update_existing(self, meta: dict, meta_root: dict, meta_root_locks: dict, meta_prefixed: dict[str, dict], meta_prefixed_locks: dict[str, dict], tag_prefixed: dict[str, dict]):
        rich_text_keys = {"collected by"}

        for key, card in self._sections.items():
            if key == "tag" and self._search_widget(card) is not None:
                self._update_tag_card(card, meta, prefix="")
                continue
            if key.startswith(_TAG_PREFIX):
                prefix = key[len(_TAG_PREFIX) :]
                plugin = self._section_plugins.get(key)
                if plugin is not None:
                    self._update_tag_plugin(plugin, meta, tag_prefixed, prefix)
                elif self._search_widget(card) is not None:
                    self._update_tag_card(card, meta, prefix=prefix, prefixed=tag_prefixed)
                continue
            if key == _META_ROOT_KEY and self._search_widget(card) is not None:
                self._update_meta_card(card, meta, prefix="", data=meta_root, locks=meta_root_locks)
                continue
            if key.startswith(_META_PREFIX):
                prefix = key[len(_META_PREFIX) :]
                plugin = self._section_plugins.get(key)
                if plugin is not None:
                    self._update_meta_plugin(plugin, meta, meta_prefixed, meta_prefixed_locks, prefix)
                elif self._search_widget(card) is not None:
                    self._update_meta_card(card, meta, prefix=prefix, prefixed=meta_prefixed, locks_by_prefix=meta_prefixed_locks)
                else:
                    self._update_generic_card(card, meta_prefixed.get(prefix, {}), rich_text_keys=None)
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

    def _search_widget(self, card) -> SearchableMetaWidget | None:
        if not isinstance(card, CollapsibleCard):
            return None
        widget = card.content_widget()
        return widget if isinstance(widget, SearchableMetaWidget) else None

    def _update_tag_card(self, card: CollapsibleCard, meta: dict, *, prefix: str, prefixed: dict[str, dict] | None = None):
        widget = self._search_widget(card)
        if widget is None:
            return
        path = meta.get("_path", "") or ""
        file_hash = meta.get("_file_hash", "") or ""
        db = meta.get("_db_name", "") or ""
        if prefix:
            tags = (prefixed or {}).get(prefix, {}) or {}
            locks = (meta.get("tag_prefixed_locks", {}) or {}).get(prefix, {}) or {}
        else:
            tags = meta.get("tag", {}) or {}
            locks = meta.get("_tag_locks", {}) or {}
        widget.set_context(tags, locks, path=path, file_hash=file_hash, db=db, scope="tag", prefix=prefix)
        card.update_title_count(len(tags))

    def _update_tag_plugin(self, plugin, meta: dict, tag_prefixed: dict[str, dict], prefix: str):
        tags = tag_prefixed.get(prefix, {}) or {}
        locks = (meta.get("tag_prefixed_locks", {}) or {}).get(prefix, {}) or {}
        path = meta.get("_path", "") or ""
        file_hash = meta.get("_file_hash", "") or ""
        db = meta.get("_db_name", "") or ""
        plugin.update_data(tags, locks, path, file_hash, db, scope="tag")

    def _update_meta_card(
        self,
        card: CollapsibleCard,
        meta: dict,
        *,
        prefix: str,
        prefixed: dict[str, dict] | None = None,
        locks_by_prefix: dict[str, dict] | None = None,
        data: dict | None = None,
        locks: dict | None = None,
    ):
        widget = self._search_widget(card)
        if widget is None:
            return
        path = meta.get("_path", "") or ""
        db = meta.get("_db_name", "") or ""
        data = data if data is not None else (prefixed or {}).get(prefix, {}) or {}
        locks = locks if locks is not None else (locks_by_prefix or {}).get(prefix, {}) or {}
        widget.set_context(data, locks, path=path, file_hash="", db=db, scope="meta_info", prefix=prefix)
        card.update_title_count(len(data))

    def _update_meta_plugin(self, plugin, meta: dict, meta_prefixed: dict[str, dict], meta_prefixed_locks: dict[str, dict], prefix: str):
        data = meta_prefixed.get(prefix, {}) or {}
        locks = meta_prefixed_locks.get(prefix, {}) or {}
        path = meta.get("_path", "") or ""
        file_hash = meta.get("_file_hash", "") or ""
        db = meta.get("_db_name", "") or ""
        plugin.update_data(data, locks=locks, path=path, file_hash=file_hash, db=db, scope="meta_info")

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

    def _shutdown_key_value_panel_plugins(self):
        if self._key_value_panel_shutdown:
            return
        self._key_value_panel_shutdown = True
        for plugin in list(self._key_value_panel_instances.values()):
            try:
                plugin.shutdown()
            except Exception as e:
                AppLogger.warning(f"Key/value panel shutdown failed: {getattr(plugin, 'NAME', type(plugin).__name__)}: {e}", exc=e)

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ...core.common.formatting import display_prefixed_key
from ...qt.common.dpi import dpix
from ...core.lang.manager import t
from ...qt.common.icon_engine import themed_icon
from ...qt.theme import ThemeManager
from ...core.store.state import StateStore
from ...qt.widgets.popup import PopupBase

_STATE_NAMESPACE = "filters/active_keys"


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


def _split_prefix(key: str) -> tuple[str, str]:
    dot = key.find(".")
    if dot > 0:
        return key[:dot], key[dot + 1 :]
    return "", key


class _ActiveKeyItem(QtWidgets.QWidget):
    toggled = QtCore.Signal()
    remove_clicked = QtCore.Signal(str)

    def __init__(self, key: str, count: int | None = None, checked: bool = False, parent=None):
        super().__init__(parent)
        self.key = key
        self._checked = checked
        self.setCursor(QtCore.Qt.PointingHandCursor)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(dpix(6), dpix(2), dpix(2), dpix(2))
        layout.setSpacing(dpix(4))

        self._check_icon = QtWidgets.QLabel()
        self._check_icon.setFixedWidth(dpix(14))
        layout.addWidget(self._check_icon)

        label_text = display_prefixed_key(key)
        if count is not None:
            label_text += f" ({count})"
        self.label = QtWidgets.QLabel(label_text)
        layout.addWidget(self.label, 1)

        self.remove_btn = QtWidgets.QToolButton()
        self.remove_btn.setIcon(themed_icon("cross"))
        self.remove_btn.setFixedSize(dpix(16), dpix(16))
        self.remove_btn.setAutoRaise(True)
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.key))
        layout.addWidget(self.remove_btn)

        self._apply_visual()

    def _apply_visual(self):
        p = ThemeManager.instance().palette
        if self._checked:
            self._check_icon.setPixmap(themed_icon("check").pixmap(QtCore.QSize(dpix(12), dpix(12))))
            self.label.setStyleSheet(f"color: {p.text_primary};")
        else:
            self._check_icon.setPixmap(QtGui.QPixmap())
            self.label.setStyleSheet(f"color: {p.text_muted};")

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            child = self.childAt(event.pos())
            if child is self.remove_btn:
                super().mousePressEvent(event)
                return
            self._checked = not self._checked
            self._apply_visual()
            self.toggled.emit()
        else:
            super().mousePressEvent(event)

    @property
    def checked(self) -> bool:
        return self._checked

    def set_checked(self, value: bool):
        if self._checked != value:
            self._checked = value
            self._apply_visual()

    def update_count(self, count: int | None):
        label_text = display_prefixed_key(self.key)
        if count is not None:
            label_text += f" ({count})"
        self.label.setText(label_text)


_CATALOG_KEY_ROLE = QtCore.Qt.UserRole + 1
_CATALOG_COUNT_ROLE = QtCore.Qt.UserRole + 2


class KeyCatalogTree(QtWidgets.QWidget):
    key_clicked = QtCore.Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.datas: list[tuple[str, int]] = []
        self.extras: list[tuple[str, str]] = []
        self.highlighted: set[str] = set()
        self.pending_expanded: set[str] | None = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(2))

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(t("Search keys..."))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        layout.addWidget(self.search)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(dpix(16))
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.tree.setFocusPolicy(QtCore.Qt.NoFocus)
        self.tree.setStyleSheet(f"QTreeWidget {{ background: {ThemeManager.instance().palette.bg_secondary}; }}")
        self.tree.itemClicked.connect(self.on_item_clicked)
        layout.addWidget(self.tree, 1)

    def set_catalog(self, datas: list[tuple[str, int]], extras: list[tuple[str, str]] = ()):
        self.datas = list(datas)
        self.extras = list(extras)
        self.rebuild()

    def set_highlighted(self, keys: set[str]):
        self.highlighted = set(keys)
        self.paint_items()

    def expanded_prefixes(self) -> set[str]:
        expanded = set()
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            node = root.child(i)
            if node.isExpanded() and node.data(0, _CATALOG_KEY_ROLE) is None:
                text = node.text(0)
                expanded.add(text.split("  (")[0] if "  (" in text else text)
        return expanded

    def set_expanded_prefixes(self, prefixes: set[str] | None):
        self.pending_expanded = None if prefixes is None else set(prefixes)
        if self.pending_expanded is not None and self.datas:
            self.rebuild()

    def reset_filter(self):
        self.search.setFocus()
        self.search.clear()

    def rebuild(self):
        expanded = self.expanded_prefixes()
        consume_pending = self.pending_expanded is not None and bool(self.datas)
        if self.pending_expanded is not None:
            expanded = set(self.pending_expanded)
        self.tree.clear()
        for key, label in self.extras:
            item = QtWidgets.QTreeWidgetItem(self.tree, [label])
            item.setData(0, _CATALOG_KEY_ROLE, key)
            item.setFlags(QtCore.Qt.ItemIsEnabled)
        groups: dict[str, list[tuple[str, str, int]]] = {}
        for key, count in self.datas:
            prefix, suffix = _split_prefix(key)
            groups.setdefault(prefix, []).append((key, suffix, count))

        self.add_group_items(None, groups.pop("", []))
        for prefix in sorted(groups.keys()):
            items = groups[prefix]
            group_node = QtWidgets.QTreeWidgetItem(self.tree, [f"{prefix}  ({len(items)})"])
            group_node.setFlags(QtCore.Qt.ItemIsEnabled)
            font = group_node.font(0)
            font.setBold(True)
            group_node.setFont(0, font)
            self.add_group_items(group_node, items)
            group_node.setExpanded(prefix in expanded)

        if consume_pending:
            self.pending_expanded = None
        self.paint_items()
        self.apply_filter(self.search.text())

    def add_group_items(self, parent_node, items: list[tuple[str, str, int]]):
        for key, suffix, count in items:
            if parent_node is not None:
                item = QtWidgets.QTreeWidgetItem(parent_node, [f"{suffix} ({count})"])
            else:
                item = QtWidgets.QTreeWidgetItem(self.tree, [f"{display_prefixed_key(key)} ({count})"])
            item.setData(0, _CATALOG_KEY_ROLE, key)
            item.setData(0, _CATALOG_COUNT_ROLE, count)
            item.setFlags(QtCore.Qt.ItemIsEnabled)

    def paint_items(self):
        p = ThemeManager.instance().palette
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            top_item = root.child(i)
            nodes = [top_item] if top_item.data(0, _CATALOG_KEY_ROLE) is not None else [top_item.child(j) for j in range(top_item.childCount())]
            for node in nodes:
                color = p.text_primary if node.data(0, _CATALOG_KEY_ROLE) in self.highlighted else p.text_muted
                node.setForeground(0, QtGui.QColor(color))

    def on_item_clicked(self, item: QtWidgets.QTreeWidgetItem, column: int):
        key = item.data(0, _CATALOG_KEY_ROLE)
        if key is not None:
            self.key_clicked.emit(key, item.data(0, _CATALOG_COUNT_ROLE))

    def apply_filter(self, text: str):
        text = text.strip().lower()
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            top_item = root.child(i)
            key = top_item.data(0, _CATALOG_KEY_ROLE)
            if key is not None:
                visible = not text or text in key.lower()
                top_item.setHidden(not visible)
            else:
                any_child_visible = False
                for j in range(top_item.childCount()):
                    child = top_item.child(j)
                    child_key = child.data(0, _CATALOG_KEY_ROLE) or ""
                    child_visible = not text or text in child_key.lower()
                    child.setHidden(not child_visible)
                    if child_visible:
                        any_child_visible = True
                top_item.setHidden(not any_child_visible)
                if any_child_visible and text:
                    top_item.setExpanded(True)


class KeyPickerPopup(PopupBase):
    picked = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        self.catalog = KeyCatalogTree()
        self.catalog.key_clicked.connect(self.on_key_clicked)
        layout.addWidget(self.catalog)
        p = ThemeManager.instance().palette
        self.setStyleSheet(f"KeyPickerPopup {{ background: {p.bg_primary}; border: {dpix(1)}px solid {p.border_default}; border-radius: {dpix(4)}px; }}")

    def set_catalog(self, datas: list[tuple[str, int]], *, extras: list[tuple[str, str]] = ()):
        self.catalog.set_catalog(datas, extras=list(extras))

    def set_used(self, keys: set[str]):
        self.catalog.set_highlighted(set(keys))

    def on_key_clicked(self, key: str, _count):
        self.hide()
        self.picked.emit(key)

    def open_below(self, anchor: QtWidgets.QWidget):
        self.catalog.reset_filter()
        self.show_below(anchor)

    def sizeHint(self):
        return QtCore.QSize(dpix(320), dpix(420))


class _KeySelectorPopup(PopupBase):
    _instance = None
    active_keys_changed = QtCore.Signal(set)
    check_toggled = QtCore.Signal()

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self._catalog_data: list[tuple[str, int]] = []
        self._active_items: dict[str, _ActiveKeyItem] = {}
        self._pending_active_keys: list[str] = []
        self._pending_splitter_sizes: list[int] | None = None
        self._suppress_signals = False
        self._current_combo = None
        self._build_ui()
        self._apply_theme()
        StateStore.instance().register(_STATE_NAMESPACE, self._save_state, self._restore_state)

    def _save_state(self) -> dict:
        state = {
            "keys": list(self._active_items.keys()),
            "expanded": sorted(self.catalog.expanded_prefixes()),
        }
        sizes = self._splitter.sizes()
        if any(sizes):
            state["splitter_sizes"] = sizes
        return state

    def _restore_state(self, state: dict):
        if not isinstance(state, dict):
            return
        keys = [k for k in (state.get("keys") or []) if isinstance(k, str)]
        expanded = state.get("expanded") or []
        if isinstance(expanded, (list, tuple, set)):
            self.catalog.set_expanded_prefixes({k for k in expanded if isinstance(k, str)})
        self._pending_splitter_sizes = self._valid_splitter_sizes(state.get("splitter_sizes"))
        self._apply_pending_splitter_sizes()
        self._pending_active_keys = keys
        if keys:
            self.ensure_active_keys(keys)

    def pending_active_keys(self) -> list[str]:
        return list(self._pending_active_keys)

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(dpix(6), dpix(6), dpix(6), dpix(6))
        root.setSpacing(dpix(4))

        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self._splitter.setChildrenCollapsible(False)

        self._active_group = QtWidgets.QGroupBox(t("Filter"))
        active_layout = QtWidgets.QVBoxLayout(self._active_group)
        active_layout.setContentsMargins(dpix(4), dpix(2), dpix(4), dpix(4))
        active_layout.setSpacing(0)

        self._active_scroll = QtWidgets.QScrollArea()
        self._active_scroll.setWidgetResizable(True)
        self._active_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._active_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        self._active_list_widget = QtWidgets.QWidget()
        self._active_list_layout = QtWidgets.QVBoxLayout(self._active_list_widget)
        self._active_list_layout.setContentsMargins(0, 0, 0, 0)
        self._active_list_layout.setSpacing(0)
        self._active_list_layout.addStretch()
        self._active_scroll.setWidget(self._active_list_widget)
        active_layout.addWidget(self._active_scroll, 1)

        self.catalog = KeyCatalogTree()
        self.catalog.key_clicked.connect(self._on_catalog_key_clicked)

        self._splitter.addWidget(self._active_group)
        self._splitter.addWidget(self.catalog)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 3)
        root.addWidget(self._splitter, 1)

    def _apply_theme(self):
        p = ThemeManager.instance().palette
        self.setStyleSheet(f"_KeySelectorPopup {{  background: {p.bg_primary};  border: {dpix(1)}px solid {p.border_default};  border-radius: {dpix(4)}px;}}")
        self._active_group.setStyleSheet(
            f"QGroupBox {{"
            f"  border: {dpix(1)}px solid {p.border_subtle};"
            f"  border-radius: {dpix(4)}px;"
            f"  margin-top: {dpix(10)}px;"
            f"  padding-top: {dpix(8)}px;"
            f"}}"
            f"QGroupBox::title {{"
            f"  subcontrol-origin: margin;"
            f"  left: {dpix(8)}px;"
            f"  padding: 0 {dpix(4)}px;"
            f"  color: {p.text_secondary};"
            f"}}"
        )

    def active_key_set(self) -> set[str]:
        return set(self._active_items.keys())

    def catalog_data(self) -> list[tuple[str, int]]:
        return list(self._catalog_data)

    def set_catalog(self, datas: list[tuple[str, int]]):
        self._catalog_data = list(datas)
        count_map = dict(datas)
        for key, item in self._active_items.items():
            item.update_count(count_map.get(key))
        self.catalog.set_catalog(datas)

    def _on_catalog_key_clicked(self, key: str, count):
        if key in self._active_items:
            self._remove_active_key(key)
            self._notify_active_keys_changed({key})
        else:
            self._add_active_key(key, count, checked=True)
            self._notify_active_keys_changed(set())
            self._on_check_toggled()

    def add_key_if_missing(self, key: str, count: int | None = None):
        if key in self._active_items:
            return False
        self._add_active_key(key, count)
        return True

    def ensure_active_keys(self, keys: list[str]):
        count_map = dict(self._catalog_data)
        for key in keys:
            if key not in self._active_items:
                self._add_active_key(key, count_map.get(key))

    def _add_active_key(self, key: str, count: int | None = None, checked: bool = False):
        if key in self._active_items:
            return
        widget = _ActiveKeyItem(key, count, checked=checked)
        widget.toggled.connect(self._on_check_toggled)
        widget.remove_clicked.connect(self._on_remove_key)
        insert_idx = self._active_list_layout.count() - 1
        self._active_list_layout.insertWidget(insert_idx, widget)
        self._active_items[key] = widget
        self.catalog.set_highlighted(set(self._active_items))

    def _valid_splitter_sizes(self, value) -> list[int] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        try:
            sizes = [int(v) for v in value]
        except (TypeError, ValueError):
            return None
        if any(v < 0 for v in sizes):
            return None
        return sizes

    def _apply_pending_splitter_sizes(self):
        if self._pending_splitter_sizes is None:
            return
        self._splitter.setSizes(self._pending_splitter_sizes)
        self._pending_splitter_sizes = None

    def _on_remove_key(self, key: str):
        self._remove_active_key(key)
        self._notify_active_keys_changed({key})

    def _remove_active_key(self, key: str):
        widget = self._active_items.pop(key, None)
        if widget:
            self._active_list_layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
            self.catalog.set_highlighted(set(self._active_items))

    def _on_check_toggled(self):
        if not self._suppress_signals:
            self.check_toggled.emit()

    def _notify_active_keys_changed(self, removed_keys: set[str]):
        self._pending_active_keys = list(self._active_items.keys())
        if not self._suppress_signals:
            self.active_keys_changed.emit(removed_keys)

    def open_for(self, combo):
        self._current_combo = combo
        checked = set(combo._checked_keys)
        self._suppress_signals = True
        for key, item in self._active_items.items():
            item.set_checked(key in checked)
        self._suppress_signals = False
        self.show_below(combo)

    def sync_checks_for(self, combo):
        if self._current_combo is combo and self.isVisible():
            checked = set(combo._checked_keys)
            self._suppress_signals = True
            for key, item in self._active_items.items():
                item.set_checked(key in checked)
            self._suppress_signals = False

    def sizeHint(self):
        return QtCore.QSize(dpix(320), dpix(420))

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_pending_splitter_sizes()
        self.catalog.reset_filter()


class CheckableCombo(QtWidgets.QToolButton):
    action_changed = QtCore.Signal()

    def __init__(self, items=None, parent=None):
        super().__init__(parent)
        self.default_key = "path"
        self._checked_keys: list[str] = [self.default_key]
        self._popup = _KeySelectorPopup.instance()
        self._popup.active_keys_changed.connect(self._on_active_keys_changed)
        self._popup.check_toggled.connect(self._on_check_toggled)
        self._update_label()
        self.clicked.connect(self._toggle_popup)
        if items:
            self._popup.set_catalog(items)
            self._popup.ensure_active_keys([self.default_key])

    def _update_label(self):
        self.setText(t(" Filter "))

    def _toggle_popup(self):
        if self._popup.isVisible() and self._popup._current_combo is self:
            self._popup.hide()
        else:
            self._popup.open_for(self)

    @QtCore.Slot(list)
    def remake(self, datas):
        self._popup.set_catalog(datas)
        saved = self._popup.pending_active_keys()
        if saved:
            saved = [k for k in saved if isinstance(k, str) and len(k) > 1]
        needed = list(dict.fromkeys((saved or []) + self._checked_keys + [self.default_key]))
        self._popup.ensure_active_keys(needed)
        active = self._popup.active_key_set()
        valid = [k for k in self._checked_keys if k in active]
        if not valid and self.default_key in active:
            valid = [self.default_key]
        self._checked_keys = valid
        self.action_changed.emit()

    def _on_check_toggled(self):
        if self._popup._current_combo is not self:
            return
        self._checked_keys = [key for key, item in self._popup._active_items.items() if item.checked]
        self.action_changed.emit()

    def _on_active_keys_changed(self, removed_keys: set[str]):
        if not removed_keys:
            return
        before = len(self._checked_keys)
        self._checked_keys = [k for k in self._checked_keys if k not in removed_keys]
        if len(self._checked_keys) != before:
            self.action_changed.emit()

    def checked_items(self) -> list[str]:
        active = self._popup.active_key_set()
        return [k for k in self._checked_keys if k in active]

    def set_checked(self, keys: list[str]):
        self._checked_keys = list(keys)
        count_map = dict(self._popup.catalog_data())
        for key in keys:
            self._popup.add_key_if_missing(key, count_map.get(key))
        self._popup.sync_checks_for(self)

    @property
    def active_keys(self) -> list[str]:
        return list(self._popup._active_items.keys())


class TextFilterWidget(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(2))

        self.option_button = QtWidgets.QToolButton()
        self.option_button.setIcon(themed_icon("gear_small"))
        self.option_button.setFixedSize(dpix(28), dpix(24))
        self.option_button.clicked.connect(self._toggle_option_popup)

        self.keys_combo = CheckableCombo()
        self.keys_combo.action_changed.connect(self.changed)

        self.search_bar = QtWidgets.QLineEdit()
        self.search_bar.setPlaceholderText(t("Enter search terms..."))
        self.search_bar.textChanged.connect(self.changed)

        layout.addWidget(self.keys_combo)
        layout.addWidget(self.option_button)
        layout.addWidget(self.search_bar, 1)

        self._option_popup = _TextFilterPopup(self)
        self._option_popup.changed.connect(self.changed)
        self._bound_key_store = None

    def bind_key_store(self, key_store):
        prev = self._bound_key_store
        if prev is not None:
            try:
                prev.updated.disconnect(self.keys_combo.remake)
            except (TypeError, RuntimeError):
                pass
        self._bound_key_store = key_store
        if key_store is None:
            return
        key_store.updated.connect(self.keys_combo.remake)
        if key_store.data:
            self.keys_combo.remake(key_store.data)

    def _toggle_option_popup(self):
        popup = self._option_popup
        if popup.isVisible():
            popup.hide()
        else:
            popup.show_below(self.option_button, align=QtCore.Qt.AlignRight)

    def _position_popup(self):
        self._option_popup.position_below(self.option_button, align=QtCore.Qt.AlignRight)

    def read_params(self) -> dict:
        settings = self._option_popup.get_settings()
        if self.keys_combo.active_keys:
            keys = self.keys_combo.checked_items()
        else:
            keys = None
        return {
            "keys": keys,
            "keywords": self.search_bar.text(),
            "query_mode": settings["query_mode"],
            "keyword_mode": settings["keyword_mode"],
            "keyword_separator": settings["keyword_separator"],
            "trim_keywords": settings["trim_keywords"],
        }

    def write_params(self, params: dict):
        if "keywords" in params:
            self.search_bar.blockSignals(True)
            self.search_bar.setText(params["keywords"])
            self.search_bar.blockSignals(False)
        if "keys" in params:
            keys = params["keys"]
            if isinstance(keys, list):
                self.keys_combo.set_checked(keys)
        self._option_popup.set_settings(params)

    def move_popup(self):
        if self._option_popup.isVisible():
            self._position_popup()


class _TextFilterPopup(PopupBase):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Text Filter Options"))
        self._build_ui()
        self._set_defaults()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        title = QtWidgets.QLabel(t("Text Filter Options"))
        title.setStyleSheet(f"font-weight: bold; padding-bottom: {dpix(4)}px;")
        layout.addWidget(title)

        self.query_type_combo = QtWidgets.QComboBox()
        self.query_type_combo.addItem("GLOB", "GLOB")
        self.query_type_combo.addItem("LIKE", "LIKE")
        self.query_type_combo.currentIndexChanged.connect(lambda: self.changed.emit())
        layout.addWidget(self.query_type_combo)

        self.keyword_group = QtWidgets.QButtonGroup(self)
        self.and_radio = QtWidgets.QRadioButton("AND")
        self.or_radio = QtWidgets.QRadioButton("OR")
        self.keyword_group.addButton(self.and_radio)
        self.keyword_group.addButton(self.or_radio)
        self.and_radio.toggled.connect(lambda: self.changed.emit())
        self.or_radio.toggled.connect(lambda: self.changed.emit())
        hlayout = QtWidgets.QHBoxLayout()
        hlayout.addWidget(self.and_radio)
        hlayout.addWidget(self.or_radio)
        layout.addLayout(hlayout)

        sep_layout = QtWidgets.QHBoxLayout()
        self.delimiter_input = QtWidgets.QLineEdit()
        self.delimiter_input.textChanged.connect(lambda: self.changed.emit())
        sep_layout.addWidget(QtWidgets.QLabel(t("Split by:")))
        sep_layout.addWidget(self.delimiter_input)
        layout.addLayout(sep_layout)

        self.trim_check = QtWidgets.QCheckBox(t("Trim spaces"))
        self.trim_check.toggled.connect(lambda: self.changed.emit())
        layout.addWidget(self.trim_check)

    def _set_defaults(self):
        self.query_type_combo.setCurrentIndex(0)
        self.and_radio.setChecked(True)
        self.delimiter_input.setText(",")
        self.trim_check.setChecked(True)

    def get_settings(self) -> dict:
        return {
            "query_mode": self.query_type_combo.currentData(),
            "keyword_mode": "AND" if self.and_radio.isChecked() else "OR",
            "keyword_separator": self.delimiter_input.text() or ",",
            "trim_keywords": self.trim_check.isChecked(),
        }

    def set_settings(self, params: dict):
        if "query_mode" in params:
            idx = self.query_type_combo.findData(params["query_mode"])
            if idx >= 0:
                self.query_type_combo.blockSignals(True)
                self.query_type_combo.setCurrentIndex(idx)
                self.query_type_combo.blockSignals(False)
        if "keyword_mode" in params:
            radio = self.and_radio if params["keyword_mode"] == "AND" else self.or_radio
            radio.blockSignals(True)
            radio.setChecked(True)
            radio.blockSignals(False)
        if "keyword_separator" in params:
            self.delimiter_input.blockSignals(True)
            self.delimiter_input.setText(params["keyword_separator"])
            self.delimiter_input.blockSignals(False)
        if "trim_keywords" in params:
            self.trim_check.blockSignals(True)
            self.trim_check.setChecked(params["trim_keywords"])
            self.trim_check.blockSignals(False)

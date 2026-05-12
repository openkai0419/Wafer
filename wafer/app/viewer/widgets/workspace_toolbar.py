from __future__ import annotations

from datetime import datetime
from pathlib import PurePath

from PySide6 import QtCore, QtWidgets

from ....core.color.theme import ThemeManager
from ....core.commands.bridge import Command
from ....core.lang.manager import t
from ....core.qt.icon_engine import themed_icon
from ....core.qt.dispatcher import Dispatcher
from ....core.qt.thread import utility_pool
from ....core.workspace import WindowSlot, WorkspaceStore
from ....ui.dialogs import ConfirmDialog
from ....ui.widgets.eliding import ElidingLabel
from ....ui.popups import PopupBase
from ....utils.formatting import dpix
from ....utils.logs import AppLogger

_KIND_UI = "ui"
_KIND_PATH = "path"
_KIND_QUERY = "query"
_KIND_RECENT = "recent"
_SECTION_POPUP_WIDTH = 220
_SECTION_POPUP_MAX_HEIGHT = 240
_PRESET_LIST_HEIGHT = 148
_POPUP_PADDING = 4
_CONTENT_PADDING = 4
_ROW_PADDING_H = 2
_ROW_PADDING_V = 2
_COMPACT_SPACING = 1
_ACTION_BUTTON_SIZE = 22


def _format_iso(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        AppLogger.warning(f"Invalid ISO datetime in workspace store: {value!r}")
        return value


def _slot_summary(slot: WindowSlot) -> str:
    path = slot.path if isinstance(slot.path, dict) else {}
    database = str(path.get("database_name") or t("No database"))
    selected = [str(p) for p in (path.get("selected") or []) if p]
    if not selected:
        return database
    first = PurePath(selected[0]).name or selected[0]
    if len(selected) == 1:
        return f"{database} / {first}"
    return f"{database} / {first} +{len(selected) - 1}"


def _slot_title(slot: WindowSlot) -> str:
    return str(getattr(slot, "name", "") or "").strip() or _slot_summary(slot)


def _slot_subtitle(slot: WindowSlot) -> str:
    updated = _format_iso(slot.updated_at)
    if str(getattr(slot, "name", "") or "").strip():
        summary = _slot_summary(slot)
        return f"{summary} / {updated}" if updated else summary
    return updated


def _slot_tooltip(slot: WindowSlot) -> str:
    parts = [_slot_title(slot)]
    summary = _slot_summary(slot)
    if summary != parts[0]:
        parts.append(summary)
    updated = _format_iso(slot.updated_at)
    if updated:
        parts.append(f"{t('Last updated')}: {updated}")
    parts.append(f"slot_id: {slot.slot_id}")
    return "\n".join(parts)


def _icon_button(icon_key: str, tooltip: str, parent=None) -> QtWidgets.QToolButton:
    btn = QtWidgets.QToolButton(parent)
    btn.setIcon(themed_icon(icon_key, margin=0.06))
    btn.setFixedSize(dpix(_ACTION_BUTTON_SIZE), dpix(_ACTION_BUTTON_SIZE))
    btn.setToolTip(tooltip)
    btn.setCursor(QtCore.Qt.PointingHandCursor)
    return btn


class _SectionButton(QtWidgets.QToolButton):
    def __init__(self, key: str, title: str, parent=None, icon_key: str | None = None, icon_only: bool = False):
        super().__init__(parent)
        self.key = key
        self.title = title
        self.expanded = False
        self._icon_key = icon_key
        self._icon_only = icon_only
        self.setText("" if icon_only else title)
        self.setToolTip(title if icon_only else "")
        self.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly if icon_only else QtCore.Qt.ToolButtonTextBesideIcon)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setIconSize(QtCore.QSize(dpix(15 if icon_only else 9), dpix(15 if icon_only else 9)))
        self.setAutoRaise(True)
        if icon_only:
            self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
            self.setFixedWidth(dpix(24))
        else:
            self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.set_expanded(False)
        self._apply_style()

    def set_expanded(self, expanded: bool):
        self.expanded = bool(expanded)
        icon_key = self._icon_key if self._icon_only else ("chevron_down" if self.expanded else "chevron_right")
        self.setIcon(themed_icon(icon_key or "empty"))
        self._apply_style()

    def _apply_style(self):
        p = ThemeManager.instance().palette
        bg = p.bg_hover if self.expanded else "transparent"
        padding = f"{dpix(2)}px" if self._icon_only else f"{dpix(1)}px {dpix(4)}px"
        self.setStyleSheet(
            f"QToolButton {{ background: {bg}; color: {p.text_primary}; border: 1px solid {p.border_subtle};"
            f" border-radius: {dpix(4)}px; padding: {padding}; font-size: {dpix(11)}px; }}"
            f"QToolButton:hover {{ background: {p.bg_hover}; }}"
            f"QToolButton:pressed {{ background: {p.bg_pressed}; }}"
        )


class _SectionPopup(PopupBase):
    closed = QtCore.Signal(str)

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setMinimumWidth(dpix(_SECTION_POPUP_WIDTH))
        self.resize(dpix(_SECTION_POPUP_WIDTH), dpix(40))

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        p = ThemeManager.instance().palette
        self._container = QtWidgets.QWidget()
        self._container.setObjectName("workspace_section_popup")
        self._container.setStyleSheet(f"#workspace_section_popup {{ background: {p.bg_primary}; border: 1px solid {p.border_subtle}; border-radius: {dpix(6)}px; }}")
        outer.addWidget(self._container)

        self._layout = QtWidgets.QVBoxLayout(self._container)
        self._layout.setContentsMargins(dpix(_POPUP_PADDING), dpix(_POPUP_PADDING), dpix(_POPUP_PADDING), dpix(_POPUP_PADDING))
        self._layout.setSpacing(0)
        self._content_widget: QtWidgets.QWidget | None = None

    def set_content_widget(self, widget: QtWidgets.QWidget):
        if self._content_widget is not None:
            self._layout.removeWidget(self._content_widget)
        self._content_widget = widget
        self._layout.addWidget(widget)

    def content_widget(self) -> QtWidgets.QWidget | None:
        return self._content_widget

    def popup_size_hint(self) -> QtCore.QSize:
        content = self._content_widget
        if content is not None and hasattr(content, "content_height_hint"):
            content_size = content.content_height_hint()
        else:
            content_size = content.sizeHint() if content is not None else QtCore.QSize()
        margins = self._layout.contentsMargins()
        content_min_width = content.minimumSizeHint().width() if content is not None else 0
        return QtCore.QSize(
            max(content_min_width + margins.left() + margins.right(), dpix(_SECTION_POPUP_WIDTH)),
            max(content_size.height() + margins.top() + margins.bottom(), dpix(40)),
        )

    def show_below(self, widget: QtWidgets.QWidget):
        super().show_below(widget, max_height=dpix(_SECTION_POPUP_MAX_HEIGHT))

    def _emit_closed(self):
        self.closed.emit(self.key)


class _PresetTextArea(QtWidgets.QFrame):
    clicked = QtCore.Signal()

    def __init__(self, name: str, updated_at: str, parent=None):
        super().__init__(parent)
        self.setObjectName("workspace_preset_text_area")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMinimumWidth(0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.setAttribute(QtCore.Qt.WA_Hover, True)
        self._build_ui(name, updated_at)

    def _build_ui(self, name: str, updated_at: str):
        p = ThemeManager.instance().palette
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(_ROW_PADDING_H), dpix(_ROW_PADDING_V), dpix(_ROW_PADDING_H), dpix(_ROW_PADDING_V))
        layout.setSpacing(0)

        self.name_label = ElidingLabel(name)
        self.name_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.name_label.setStyleSheet(f"color: {p.text_primary}; font-size: {dpix(12)}px;")
        layout.addWidget(self.name_label)

        updated = _format_iso(updated_at)
        self.updated_label = QtWidgets.QLabel(updated)
        self.updated_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.updated_label.setStyleSheet(f"color: {p.text_muted}; font-size: {dpix(10)}px;")
        if updated:
            self.updated_label.setToolTip(f"{t('Last updated')}: {updated}")
        layout.addWidget(self.updated_label)

        self.setStyleSheet(f"QFrame#workspace_preset_text_area {{ background: transparent; border-radius: {dpix(3)}px; }}QFrame#workspace_preset_text_area:hover {{ background: {p.bg_hover}; }}")

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _PresetItem(QtWidgets.QWidget):
    apply_requested = QtCore.Signal(str, str, str)
    overwrite_requested = QtCore.Signal(str, str)
    rename_requested = QtCore.Signal(str, str)
    delete_requested = QtCore.Signal(str, str)

    def __init__(self, kind: str, preset_id: str, name: str, updated_at: str = "", mode_provider=None, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.preset_id = preset_id
        self.name = name
        self.updated_at = updated_at
        self._mode_provider = mode_provider
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(dpix(_ROW_PADDING_H), dpix(_ROW_PADDING_V), dpix(_ROW_PADDING_H), dpix(_ROW_PADDING_V))
        layout.setSpacing(dpix(_COMPACT_SPACING))

        self._text_area = _PresetTextArea(self.name, self.updated_at, parent=self)
        self._text_area.clicked.connect(self._on_apply_click)
        self._label = self._text_area.name_label
        self._updated_label = self._text_area.updated_label
        layout.addWidget(self._text_area, 1)

        ow = self._icon_button("save", t("Overwrite"))
        ow.clicked.connect(lambda: self.overwrite_requested.emit(self.kind, self.preset_id))
        layout.addWidget(ow)

        rn = self._icon_button("pencil", t("Rename"))
        rn.clicked.connect(lambda: self.rename_requested.emit(self.kind, self.preset_id))
        layout.addWidget(rn)

        dl = self._icon_button("trash", t("Delete"))
        dl.clicked.connect(lambda: self.delete_requested.emit(self.kind, self.preset_id))
        layout.addWidget(dl)

    def _icon_button(self, icon_key: str, tooltip: str) -> QtWidgets.QToolButton:
        return _icon_button(icon_key, tooltip, self)

    def _on_apply_click(self):
        mode = self._mode_provider() if self._mode_provider else "replace"
        self.apply_requested.emit(self.kind, self.preset_id, mode)


class _Column(QtWidgets.QWidget):
    save_requested = QtCore.Signal(str)
    apply_requested = QtCore.Signal(str, str, str)
    overwrite_requested = QtCore.Signal(str, str)
    rename_requested = QtCore.Signal(str, str)
    delete_requested = QtCore.Signal(str, str)

    def __init__(self, kind: str, title: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.title = title
        self._build_ui()

    def _build_ui(self):
        p = ThemeManager.instance().palette
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(dpix(_CONTENT_PADDING), dpix(_CONTENT_PADDING), dpix(_CONTENT_PADDING), dpix(_CONTENT_PADDING))
        outer.setSpacing(dpix(_COMPACT_SPACING))

        self._save_btn = QtWidgets.QPushButton(t("Save current"))
        self._save_btn.setIcon(themed_icon("plus"))
        self._save_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._save_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {p.text_accent}; border: 1px dashed {p.border_default};"
            f"  border-radius: {dpix(4)}px; padding: {dpix(3)}px; font-size: {dpix(12)}px; }}"
            f"QPushButton:hover {{ background: {p.bg_hover}; }}"
        )
        self._save_btn.clicked.connect(self._on_save)
        outer.addWidget(self._save_btn)

        self._list_scroll = QtWidgets.QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._list_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._list_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._list_scroll.setFixedHeight(dpix(_PRESET_LIST_HEIGHT))
        self._list_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; } QScrollArea > QWidget > QWidget { background: transparent; }")
        self._list_widget = QtWidgets.QWidget()
        self._list_layout = QtWidgets.QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_scroll.setWidget(self._list_widget)
        outer.addWidget(self._list_scroll)

        self._settings_widget = self._build_settings_widget()
        if self._settings_widget is not None:
            outer.addWidget(self._settings_widget)

    def _build_settings_widget(self) -> QtWidgets.QWidget | None:
        p = ThemeManager.instance().palette
        if self.kind == _KIND_UI:
            widget = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(widget)
            layout.setContentsMargins(dpix(_CONTENT_PADDING), dpix(_ROW_PADDING_V), dpix(_CONTENT_PADDING), 0)
            layout.setSpacing(0)
            self._restore_window_cb = QtWidgets.QCheckBox(t("Restore Window pos"))
            self._restore_window_cb.setChecked(False)
            layout.addWidget(self._restore_window_cb)
            return widget
        if self.kind != _KIND_QUERY:
            return None
        widget = QtWidgets.QWidget()
        widget.setStyleSheet(f"QWidget {{ color: {p.text_primary}; }} QLabel {{ color: {p.text_primary}; font-size: {dpix(11)}px; }}")
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(dpix(_CONTENT_PADDING), dpix(_ROW_PADDING_V), dpix(_CONTENT_PADDING), 0)
        layout.setSpacing(dpix(_COMPACT_SPACING))
        self._restore_sort_cb = QtWidgets.QCheckBox(t("Restore Sort"))
        self._restore_sort_cb.setChecked(True)
        layout.addWidget(self._restore_sort_cb)
        self._mode_combo = QtWidgets.QComboBox()
        self._mode_combo.addItem(t("Replace"), "replace")
        self._mode_combo.addItem(t("Append"), "append")
        layout.addWidget(self._mode_combo)
        return widget

    def query_mode(self) -> str:
        if self.kind != _KIND_QUERY:
            return "replace"
        return self._mode_combo.currentData()

    def restore_sort(self) -> bool:
        return self.kind == _KIND_QUERY and self._restore_sort_cb.isChecked()

    def restore_window_state(self) -> bool:
        return self.kind == _KIND_UI and self._restore_window_cb.isChecked()

    def populate(self, items: list[tuple]):
        while self._list_layout.count():
            it = self._list_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        mode_provider = self.query_mode if self.kind == _KIND_QUERY else None
        for item in items:
            preset_id = item[0]
            name = item[1]
            updated_at = item[3] if len(item) > 3 else (item[2] if len(item) > 2 and not str(item[2]).startswith("#") else "")
            row = _PresetItem(self.kind, preset_id, name, updated_at, mode_provider=mode_provider, parent=self._list_widget)
            row.apply_requested.connect(self.apply_requested.emit)
            row.overwrite_requested.connect(self.overwrite_requested.emit)
            row.rename_requested.connect(self.rename_requested.emit)
            row.delete_requested.connect(self.delete_requested.emit)
            self._list_layout.addWidget(row)
        if not items:
            empty = QtWidgets.QLabel(t("(empty)"))
            empty.setAlignment(QtCore.Qt.AlignCenter)
            empty.setStyleSheet(f"color: {ThemeManager.instance().palette.text_muted}; font-size: {dpix(11)}px; padding: {dpix(4)}px;")
            self._list_layout.addWidget(empty)
        self._list_layout.addStretch(1)

    def content_height_hint(self) -> QtCore.QSize:
        self.layout().activate()
        return self.sizeHint().expandedTo(QtCore.QSize(dpix(_SECTION_POPUP_WIDTH), 0))

    def _on_save(self):
        self.save_requested.emit(self.kind)


class _RecentSlotItem(QtWidgets.QWidget):
    restore_requested = QtCore.Signal(str)
    rename_requested = QtCore.Signal(str)
    delete_requested = QtCore.Signal(str)

    def __init__(self, slot: WindowSlot, parent=None, is_current: bool = False):
        super().__init__(parent)
        self.slot = slot
        self.is_current = bool(is_current)
        self._build_ui()

    def _build_ui(self):
        p = ThemeManager.instance().palette
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(dpix(_ROW_PADDING_H), dpix(_ROW_PADDING_V), dpix(_ROW_PADDING_H), dpix(_ROW_PADDING_V))

        marker = QtWidgets.QFrame(self)
        marker.setObjectName("workspace_recent_current_marker")
        marker.setProperty("current", self.is_current)
        marker.setFixedWidth(dpix(2))
        marker.setStyleSheet(f"QFrame#workspace_recent_current_marker {{ background: {p.accent if self.is_current else 'transparent'}; border-radius: {dpix(2)}px; }}")
        layout.addWidget(marker)
        self._current_marker = marker
        layout.addSpacing(dpix(1))

        labels = QtWidgets.QVBoxLayout()
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(0)
        tooltip = _slot_tooltip(self.slot)
        title = ElidingLabel(_slot_title(self.slot))
        title.setToolTip(tooltip)
        title.setStyleSheet(f"color: {p.text_primary}; font-size: {dpix(12)}px;")
        labels.addWidget(title)
        subtitle = ElidingLabel(_slot_subtitle(self.slot))
        subtitle.setToolTip(tooltip)
        subtitle.setStyleSheet(f"color: {p.text_muted}; font-size: {dpix(10)}px;")
        labels.addWidget(subtitle)
        self._title_label = title
        self._subtitle_label = subtitle
        layout.addLayout(labels, 1)

        btn = _icon_button("history", t("Restore"), self)
        btn.clicked.connect(lambda: self.restore_requested.emit(self.slot.slot_id))
        layout.addWidget(btn)
        self._restore_button = btn

        rename_btn = _icon_button("pencil", t("Rename"), self)
        rename_btn.clicked.connect(lambda: self.rename_requested.emit(self.slot.slot_id))
        layout.addWidget(rename_btn)

        delete_btn = _icon_button("trash", t("Delete"), self)
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.slot.slot_id))
        layout.addWidget(delete_btn)


class _RecentSectionContent(QtWidgets.QWidget):
    restore_requested = QtCore.Signal(str)
    rename_requested = QtCore.Signal(str)
    delete_requested = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(dpix(_CONTENT_PADDING), dpix(_CONTENT_PADDING), dpix(_CONTENT_PADDING), dpix(_CONTENT_PADDING))
        outer.setSpacing(0)
        self._recent_layout = QtWidgets.QVBoxLayout()
        self._recent_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_layout.setSpacing(0)
        outer.addLayout(self._recent_layout)

    def populate(self, slots: list[WindowSlot], current_slot_id: str = ""):
        while self._recent_layout.count():
            it = self._recent_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for slot in slots:
            row = _RecentSlotItem(slot, parent=self, is_current=slot.slot_id == current_slot_id)
            row.restore_requested.connect(self.restore_requested.emit)
            row.rename_requested.connect(self.rename_requested.emit)
            row.delete_requested.connect(self.delete_requested.emit)
            self._recent_layout.addWidget(row)
        if not slots:
            empty = QtWidgets.QLabel(t("(empty)"))
            empty.setAlignment(QtCore.Qt.AlignCenter)
            empty.setStyleSheet(f"color: {ThemeManager.instance().palette.text_muted}; font-size: {dpix(11)}px; padding: {dpix(4)}px;")
            self._recent_layout.addWidget(empty)

    def content_height_hint(self) -> QtCore.QSize:
        self.layout().activate()
        return self.sizeHint().expandedTo(QtCore.QSize(dpix(_SECTION_POPUP_WIDTH), 0))


class WorkspaceToolbarWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_section: str | None = None
        self._section_buttons: dict[str, _SectionButton] = {}
        self._section_popups: dict[str, _SectionPopup] = {}
        self._last_loaded_mtime: float | None = None
        self._dispatcher = Dispatcher(utility_pool, parent=self)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(dpix(2), dpix(2), dpix(2), dpix(2))
        outer.setSpacing(dpix(4))

        self._ui_col = _Column(_KIND_UI, t("UI"))
        self._path_col = _Column(_KIND_PATH, t("Path"))
        self._query_col = _Column(_KIND_QUERY, t("Filter"))
        self._recent_col = _RecentSectionContent()

        for col in (self._ui_col, self._path_col, self._query_col):
            col.save_requested.connect(self._on_save)
            col.apply_requested.connect(self._on_apply)
            col.overwrite_requested.connect(self._on_overwrite)
            col.rename_requested.connect(self._on_rename)
            col.delete_requested.connect(self._on_delete)
        self._recent_col.restore_requested.connect(self._on_restore_slot)
        self._recent_col.rename_requested.connect(self._on_rename_slot)
        self._recent_col.delete_requested.connect(self._on_delete_slot)

        self._add_section(_KIND_RECENT, t("Recent"), self._recent_col, icon_key="history", icon_only=True)
        self._add_section(_KIND_UI, t("UI"), self._ui_col)
        self._add_section(_KIND_PATH, t("Path"), self._path_col)
        self._add_section(_KIND_QUERY, t("Filter"), self._query_col)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

    def _add_section(self, key: str, title: str, content: QtWidgets.QWidget, icon_key: str | None = None, icon_only: bool = False):
        button = _SectionButton(key, title, parent=self, icon_key=icon_key, icon_only=icon_only)
        button.clicked.connect(lambda _checked=False, k=key: self._on_section_button_clicked(k))
        popup = _SectionPopup(key, parent=self)
        popup.set_content_widget(content)
        popup.closed.connect(self._on_popup_closed)
        self._section_buttons[key] = button
        self._section_popups[key] = popup
        self.layout().addWidget(button, 0 if icon_only else 1)

    def refresh(self, force: bool = False):
        store = WorkspaceStore.instance()
        mtime = store.get_store_mtime()
        if not force and mtime == self._last_loaded_mtime:
            return
        current_slot_id = self._current_slot_id()

        def load():
            ui, path, query = store.snapshot()
            slots = store.list_recent_slots(limit=8, include_active=True)
            self._dispatcher.invoke(lambda: self._apply_loaded(mtime, ui, path, query, slots, current_slot_id))

        self._dispatcher.post(load, priority=4)

    def _apply_loaded(self, mtime, ui_presets, path_presets, query_presets, slots, current_slot_id):
        self._last_loaded_mtime = mtime
        self._ui_col.populate([(p.preset_id, p.name, p.updated_at) for p in ui_presets])
        self._path_col.populate([(p.preset_id, p.name, p.updated_at) for p in path_presets])
        self._query_col.populate([(p.preset_id, p.name, p.updated_at) for p in query_presets])
        self._recent_col.populate(slots, current_slot_id=current_slot_id)

    def _current_slot_id(self) -> str:
        return str(getattr(self.window(), "slot_id", "") or "")

    def _on_section_button_clicked(self, key: str):
        if self._active_section == key:
            self._close_active_popup()
            return
        self.refresh()
        self.show_popup(key)

    def show_popup(self, key: str):
        self._close_active_popup()
        self._active_section = key
        self._section_buttons[key].set_expanded(True)
        self._section_popups[key].show_below(self._section_buttons[key])

    def show_ui_popup(self):
        self.refresh()
        self.show_popup(_KIND_UI)

    def show_path_popup(self):
        self.refresh()
        self.show_popup(_KIND_PATH)

    def show_filter_popup(self):
        self.refresh()
        self.show_popup(_KIND_QUERY)

    def show_recent_popup(self):
        self.refresh()
        self.show_popup(_KIND_RECENT)

    def _close_active_popup(self):
        key = self._active_section
        if key is None:
            return
        self._active_section = None
        self._section_buttons[key].set_expanded(False)
        self._section_popups[key].hide()

    def _on_popup_closed(self, key: str):
        self._section_buttons[key].set_expanded(False)
        if self._active_section == key:
            self._active_section = None

    def _cmd(self, kind: str, action: str) -> str:
        return f"{kind}_preset.{action}"

    def _on_save(self, kind: str):
        Command.invoke(self._cmd(kind, "save_current"))
        self.refresh(force=True)

    def _on_apply(self, kind: str, preset_id: str, mode: str):
        if kind == _KIND_QUERY:
            Command.invoke(self._cmd(kind, "apply"), preset_id=preset_id, mode=mode, restore_sort=self._query_col.restore_sort())
        elif kind == _KIND_UI:
            Command.invoke(self._cmd(kind, "apply"), preset_id=preset_id, restore_window_state=self._ui_col.restore_window_state())
        else:
            Command.invoke(self._cmd(kind, "apply"), preset_id=preset_id)
        self.refresh(force=True)

    def _on_overwrite(self, kind: str, preset_id: str):
        Command.invoke(self._cmd(kind, "overwrite"), preset_id=preset_id)
        self.refresh(force=True)

    def _on_rename(self, kind: str, preset_id: str):
        Command.invoke(self._cmd(kind, "rename"), preset_id=preset_id)
        self.refresh(force=True)

    def _on_delete(self, kind: str, preset_id: str):
        Command.invoke(self._cmd(kind, "delete"), preset_id=preset_id)
        self.refresh(force=True)

    def _on_restore_slot(self, slot_id: str):
        Command.invoke("ws.restore_slot", slot_id=slot_id)
        self.refresh(force=True)

    def _on_rename_slot(self, slot_id: str):
        Command.invoke("ws.rename_slot", slot_id=slot_id)
        self.refresh(force=True)

    def _on_delete_slot(self, slot_id: str):
        slot = WorkspaceStore.instance().get_slot(slot_id)
        summary = _slot_summary(slot) if slot is not None else slot_id
        result = ConfirmDialog.ask(
            f"{t('Remove this recent workspace?')}\n\n{summary}",
            title=t("Delete Workspace Slot"),
            buttons=(t("Delete"), t("Cancel")),
            parent=self,
        )
        if result != t("Delete"):
            return
        Command.invoke("ws.delete_slot", slot_id=slot_id)
        self.refresh(force=True)

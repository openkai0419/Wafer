from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ...core.lang.manager import t
from ...core.db.key_value import SCOPE_META_INFO, SCOPE_TAG
from ...core.qt.icon_engine import themed_icon
from ...plugin import BaseKeyValuePanelPlugin
from ...ui.panel.meta_viewer import CollapsibleCard
from ...ui.widgets import FlowLayout
from ...utils.formatting import dpix
from ...utils.logs import AppLogger
from . import dialogs
from .registry import MarkRegistry


_BADGE_HEIGHT = 22


class _MarkBadge(QtWidgets.QToolButton):
    def __init__(self, mark_id: str, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.mark_id = mark_id
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAutoRaise(True)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.setFixedHeight(dpix(_BADGE_HEIGHT))
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.refresh()

    def refresh(self):
        m = MarkRegistry.instance().get(self.mark_id)
        if m is None:
            return
        size = dpix(_BADGE_HEIGHT) - dpix(6)
        self.setIcon(MarkRegistry.instance().swatch_icon(self.mark_id, size))
        self.setIconSize(QtCore.QSize(size, size))
        self.setText(m.name)
        self.setToolTip(m.name)

    def _on_context_menu(self, pos: QtCore.QPoint):
        dialogs.show_mark_context_menu(self, self.mark_id, self.mapToGlobal(pos))


class _MarkBadgeRow(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None, *, scope: str = SCOPE_META_INFO):
        super().__init__(parent)
        self._active: set[str] = set()
        self._current_path: str = ""
        self._file_hash: str = ""
        self._db: str = ""
        self._scope: str = scope if scope in (SCOPE_META_INFO, SCOPE_TAG) else SCOPE_META_INFO
        self._badges: dict[str, _MarkBadge] = {}
        self._layout = FlowLayout(self, margin=dpix(2), spacing=dpix(3))
        self.setLayout(self._layout)
        self.setMinimumHeight(dpix(28))
        self._add_btn = QtWidgets.QToolButton(self)
        self._add_btn.setIcon(themed_icon("plus", margin=0.05))
        self._add_btn.setAutoRaise(True)
        self._add_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._add_btn.setToolTip(t("Add new mark..."))
        self._add_btn.setMaximumHeight(dpix(_BADGE_HEIGHT))
        self._add_btn.clicked.connect(lambda: dialogs.prompt_new_mark(self, scope=self._scope))
        self._rebuild()
        MarkRegistry.instance().changed.connect(self._rebuild)

    def update_state(self, current_path: str, active_ids: list[str], *, file_hash: str = "", db: str = "", scope: str = "meta_info"):
        self._current_path = current_path
        self._file_hash = file_hash or ""
        self._db = db or ""
        self._set_scope(scope or SCOPE_META_INFO)
        self._active = set(active_ids)
        for mid, badge in self._badges.items():
            badge.blockSignals(True)
            badge.setChecked(mid in self._active)
            badge.blockSignals(False)

    def _set_scope(self, scope: str):
        scope = scope if scope in (SCOPE_META_INFO, SCOPE_TAG) else SCOPE_META_INFO
        if self._scope == scope:
            return
        self._scope = scope
        self._rebuild()

    def _rebuild(self):
        current_ids = MarkRegistry.instance().ids_by_scope(self._scope)
        current_set = set(current_ids)
        existing_set = set(self._badges.keys())
        for mid in existing_set - current_set:
            badge = self._badges.pop(mid, None)
            if badge is not None:
                self._layout.removeWidget(badge)
                badge.setParent(None)
                badge.deleteLater()
        self._layout.removeWidget(self._add_btn)
        for mid in current_ids:
            if mid not in self._badges:
                badge = _MarkBadge(mid, self)
                badge.clicked.connect(lambda checked, m=mid: self._on_clicked(m, checked))
                self._badges[mid] = badge
                self._layout.addWidget(badge)
        for mid, badge in self._badges.items():
            badge.refresh()
            badge.blockSignals(True)
            badge.setChecked(mid in self._active)
            badge.blockSignals(False)
        self._layout.addWidget(self._add_btn)
        self.updateGeometry()

    def _on_clicked(self, mark_id: str, checked: bool):
        if not self._current_path:
            return
        mark = MarkRegistry.instance().get(mark_id)
        if mark is None:
            return
        if not self._db:
            AppLogger.warning("[MarkPanel] missing database context")
            return
        if self._scope == SCOPE_TAG and not self._file_hash:
            AppLogger.warning("[MarkPanel] cannot edit tag mark without file hash")
            return
        from ...app.viewer.preview.tag_edit_service import TagEditService

        key = MarkRegistry.key(mark.id)
        TagEditService.instance().submit(
            [self._current_path],
            [(key, "1", False)] if checked else [],
            [] if checked else [key],
            self._db,
            scope=self._scope,
            file_hash=self._file_hash if self._scope == SCOPE_TAG else None,
            target_id=self._current_path if self._scope != SCOPE_TAG else None,
        )


class MarkTagPanelPlugin(BaseKeyValuePanelPlugin):
    NAME = "mark_panel"
    PREFIX = "mark"
    DATA_SCOPE = "*"
    DEFAULT_ENABLED = True
    PRIORITY = 50

    def __init__(self):
        self._card: CollapsibleCard | None = None
        self._row: _MarkBadgeRow | None = None
        self._scope = "meta_info"

    def create_card(self, parent: QtWidgets.QWidget | None = None, *, scope: str = "meta_info") -> QtWidgets.QWidget:
        self._scope = scope or "meta_info"
        section_id = f"tag:{self.PREFIX}" if self._scope == SCOPE_TAG else f"meta:{self.PREFIX}"
        self._card = CollapsibleCard(self.PREFIX, section_id, parent)
        self._row = _MarkBadgeRow(self._card, scope=self._scope)
        self._card.set_content_widget(self._row)
        return self._card

    def update_data(
        self,
        data: dict[str, str],
        locks: dict[str, bool] | None = None,
        path: str = "",
        file_hash: str = "",
        db: str = "",
        *,
        scope: str = "meta_info",
    ) -> None:
        ids = sorted((str(k) for k in (data or {})), key=lambda x: (len(x), x))
        if self._row is not None:
            self._row.update_state(path, ids, file_hash=file_hash, db=db, scope=scope)
        if self._card is not None:
            self._card.update_title_count(len(ids))

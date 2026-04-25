from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ...core.commands.bridge import Command
from ...core.lang.manager import t
from ...core.qt.icon_engine import themed_icon
from ...plugin import BaseTagPanelPlugin
from ...ui.panel.meta_viewer import CollapsibleCard
from ...ui.widgets import FlowLayout
from ...utils.formatting import dpix
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
    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._active: set[str] = set()
        self._current_path: str = ""
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
        self._add_btn.clicked.connect(lambda: dialogs.prompt_new_mark(self))
        self._rebuild()
        MarkRegistry.instance().changed.connect(self._rebuild)

    def update_state(self, current_path: str, active_ids: list[str]):
        self._current_path = current_path
        self._active = set(active_ids)
        for mid, badge in self._badges.items():
            badge.blockSignals(True)
            badge.setChecked(mid in self._active)
            badge.blockSignals(False)

    def _rebuild(self):
        current_ids = MarkRegistry.instance().ids()
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
        command = "mark.add" if checked else "mark.remove"
        Command.invoke(command, extras={"path": self._current_path}, name=mark.name)


class MarkTagPanelPlugin(BaseTagPanelPlugin):
    NAME = "mark_panel"
    PREFIX = "mark"
    DEFAULT_ENABLED = True
    PRIORITY = 50

    def __init__(self):
        self._card: CollapsibleCard | None = None
        self._row: _MarkBadgeRow | None = None

    def create_card(self, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QWidget:
        self._card = CollapsibleCard(self.PREFIX, f"tag:{self.PREFIX}", parent)
        self._row = _MarkBadgeRow(self._card)
        self._card.set_content_widget(self._row)
        return self._card

    def update_data(
        self,
        tags: dict[str, str],
        locks: dict[str, bool],
        path: str,
        file_hash: str,
        db: str,
    ) -> None:
        ids = sorted((str(k) for k in (tags or {})), key=lambda x: (len(x), x))
        if self._row is not None:
            self._row.update_state(path, ids)
        if self._card is not None:
            self._card.update_title_count(len(ids))

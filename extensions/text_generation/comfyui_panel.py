from __future__ import annotations

import json
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from wafer.core.color.theme import ThemeManager
from wafer.core.qt.icon_engine import icon_draw
from wafer.plugin import BaseKeyValuePanelPlugin
from wafer.ui.panel.meta_viewer import CollapsibleCard
from wafer.ui.panel.searchable_meta_widget import SearchableMetaWidget
from wafer.utils.formatting import dpix
from wafer.utils.logs import AppLogger
from wafer.utils.paths import resolve_temp_path

WORKFLOW_KEY = "workflow"
_DRAG_HINT = "Drag here into ComfyUI to load workflow"
_WORKFLOW_DIR = "comfyui_workflows"


def _clear_workflow_dir() -> None:
    directory = Path(resolve_temp_path(f"{_WORKFLOW_DIR}/"))
    for path in directory.glob("*.json"):
        try:
            path.unlink()
        except OSError as e:
            AppLogger.warning(f"[comfyui_panel] failed to remove stale workflow {path.name}: {e}", exc=e)


class WorkflowDragExport(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._workflow: str | None = None
        self._file_hash = ""
        self._press_origin: QtCore.QPoint | None = None
        self.destroyed.connect(lambda: _clear_workflow_dir())
        self.setObjectName("comfyuiWorkflowDrag")
        self._pad = dpix(6)
        self._gap = dpix(5)
        self._icon_size = dpix(13)
        self.setFixedHeight(dpix(24))
        self.hide()

    def set_workflow(self, workflow: object, file_hash: str) -> None:
        self._workflow = workflow if isinstance(workflow, str) and workflow.strip() else None
        self._file_hash = file_hash or ""
        self.setVisible(self._workflow is not None)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        palette = ThemeManager.instance().palette
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        inset = dpix(1)
        box = QtCore.QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        radius = dpix(4)
        painter.setPen(QtGui.QPen(QtGui.QColor(palette.text_secondary), dpix(1)))
        painter.setBrush(QtGui.QColor(palette.bg_primary))
        painter.drawRoundedRect(box, radius, radius)

        icon_rect = QtCore.QRectF(box.left() + self._pad, box.center().y() - self._icon_size / 2, self._icon_size, self._icon_size)
        icon_draw("cursor", painter, icon_rect, QtGui.QColor(palette.text_accent))

        text_rect = box.adjusted(self._pad + self._icon_size + self._gap, 0, 0, 0)
        painter.setPen(QtGui.QColor(palette.text_primary))
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, _DRAG_HINT)
        painter.end()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton and self._workflow:
            self._press_origin = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._press_origin is None or not self._workflow:
            return
        moved = (event.position().toPoint() - self._press_origin).manhattanLength()
        if moved < QtWidgets.QApplication.startDragDistance():
            return
        self._press_origin = None
        self._start_drag()

    def _start_drag(self) -> None:
        target = self._write_temp()
        if not target:
            return
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(target)])
        drag.setMimeData(mime)
        drag.exec(QtCore.Qt.CopyAction)

    def _write_temp(self) -> str | None:
        if not self._workflow:
            return None
        _clear_workflow_dir()
        name = self._file_hash or "workflow"
        target = resolve_temp_path(f"{_WORKFLOW_DIR}/{name}.json")
        try:
            graph = json.loads(self._workflow)
            Path(target).write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
        except (ValueError, OSError) as e:
            AppLogger.warning(f"[comfyui_panel] failed to export workflow for drag: {e}", exc=e)
            return None
        return target


class ComfyUiWorkflowPanelPlugin(BaseKeyValuePanelPlugin):
    NAME = "comfyui_panel"
    PREFIX = "comfyui"
    DATA_SCOPE = "meta_info"
    DEFAULT_ENABLED = False
    PRIORITY = 50

    def __init__(self) -> None:
        self._card: CollapsibleCard | None = None
        self._body: SearchableMetaWidget | None = None
        self._export: WorkflowDragExport | None = None

    def create_card(self, parent: QtWidgets.QWidget | None = None, *, scope: str = "meta_info") -> QtWidgets.QWidget:
        section_id = f"tag:{self.PREFIX}" if scope == "tag" else f"meta:{self.PREFIX}"
        self._card = CollapsibleCard(self.PREFIX, section_id, parent)
        container = QtWidgets.QWidget(self._card)
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(4))
        self._export = WorkflowDragExport(container)
        self._body = SearchableMetaWidget(container, scope=scope, prefix=self.PREFIX)
        self._body.count_changed.connect(self._card.update_title_count)
        layout.addWidget(self._export)
        layout.addWidget(self._body)
        self._card.set_content_widget(container)
        return self._card

    def update_data(
        self,
        data: dict,
        locks: dict[str, bool] | None = None,
        path: str = "",
        file_hash: str = "",
        db: str = "",
        *,
        scope: str = "meta_info",
    ) -> None:
        data = dict(data or {})
        workflow = data.pop(WORKFLOW_KEY, None)
        if self._export is not None:
            self._export.set_workflow(workflow, file_hash)
        if self._body is not None:
            self._body.set_context(data, locks or {}, path=path, file_hash=file_hash, db=db, scope=scope, prefix=self.PREFIX)
        if self._card is not None:
            self._card.update_title_count(len(data))

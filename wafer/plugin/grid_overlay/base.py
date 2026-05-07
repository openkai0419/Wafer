from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Callable

from PySide6 import QtCore, QtGui

from ..registry import PluginBase


@dataclass(frozen=True, slots=True)
class GridOverlayCell:
    index: int
    path: str
    source: str
    scene_rect: QtCore.QRectF
    viewport_rect: QtCore.QRectF


@dataclass(frozen=True, slots=True)
class GridOverlayContext:
    cells: tuple[GridOverlayCell, ...]
    db_path: str | None = None
    db_name: str = ""

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(cell.path for cell in self.cells)


@dataclass(frozen=True, slots=True)
class OverlayBadge:
    paint: Callable[[QtGui.QPainter, QtCore.QRectF], None]
    priority: int = 0
    tooltip: str = ""

    @classmethod
    def from_mark(cls, mark_key: str, color: QtGui.QColor | str, *, priority: int = 0, tooltip: str = "") -> OverlayBadge:
        from ...core.qt.mark_engine import mark_draw

        qcolor = QtGui.QColor(color)

        def _paint(painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
            mark_draw(mark_key, painter, rect, qcolor)

        return cls(paint=_paint, priority=priority, tooltip=str(tooltip or ""))


class BaseOverlayPlugin(PluginBase):
    DATA_SCOPE: str = ""
    KEY_PREFIX: str = ""

    def bind_host(self, host: Any) -> None:
        self._overlay_host = host

    def host(self) -> Any:
        return getattr(self, "_overlay_host", None)

    def request_update(self) -> None:
        host = self.host()
        if host is not None:
            host.request_update()


class BaseBadgeOverlayPlugin(BaseOverlayPlugin):
    def badge_for_value(self, value: str, context: GridOverlayContext) -> OverlayBadge | None:
        return None


class BaseCellOverlayPlugin(BaseOverlayPlugin):
    def values_for_path(self, path: str) -> tuple[str, ...]:
        host = self.host()
        if host is None or not self.KEY_PREFIX:
            return ()
        return host.values_for(self.NAME, path)

    def paint_cell(self, painter: QtGui.QPainter, rect: QtCore.QRectF, cell: GridOverlayCell, context: GridOverlayContext) -> None:
        return None

from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtCore, QtGui

from ....core.qt.mark_engine import draw_overflow_badge
from ....core.state import StateStore
from ....plugin.grid_overlay.base import (
    BaseBadgeOverlayPlugin,
    BaseCellOverlayPlugin,
    BaseOverlayPlugin,
    GridOverlayCell,
    GridOverlayContext,
    OverlayBadge,
)
from ....plugin.grid_overlay.handler import grid_overlay_registry
from ....plugin.grid_overlay.helper import OverlayHelper
from ....utils.formatting import dpix
from ....utils.logs import AppLogger


_STATE_NAMESPACE = "grid/overlay"
DEFAULT_BADGE_RADIUS = 8
MIN_BADGE_RADIUS = 4
MAX_BADGE_RADIUS = 40


class GridOverlayHost(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(
        self,
        dbpath_getter: Callable[[], str | None],
        dbname_getter: Callable[[], str | None],
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent)
        self._dbpath_getter = dbpath_getter
        self._dbname_getter = dbname_getter
        self._plugins: list[BaseOverlayPlugin] = []
        self._plugins_by_name: dict[str, BaseOverlayPlugin] = {}
        self._helpers: dict[str, OverlayHelper] = {}
        self._visible_paths: tuple[str, ...] = ()
        self._badge_visible: bool = True
        self._badge_radius: int = DEFAULT_BADGE_RADIUS
        self._cell_visible: dict[str, bool] = {}
        self._bind_plugins()
        StateStore.instance().register(_STATE_NAMESPACE, self._save_state, self._restore_state)

    def database_path(self) -> str | None:
        return self._dbpath_getter() if self._dbpath_getter else None

    def database_name(self) -> str:
        value = self._dbname_getter() if self._dbname_getter else ""
        return str(value or "")

    def plugin(self, name: str) -> BaseOverlayPlugin | None:
        return self._plugins_by_name.get(str(name))

    def request_update(self) -> None:
        self.changed.emit()

    def reload(self) -> None:
        for helper in self._helpers.values():
            helper.refresh(force=True)

    def values_for(self, plugin_name: str, path: str) -> tuple[str, ...]:
        helper = self._helpers.get(str(plugin_name))
        return helper.values_for(path) if helper else ()

    def badge_visible(self) -> bool:
        return self._badge_visible

    def set_badge_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if self._badge_visible == visible:
            return
        self._badge_visible = visible
        self.request_update()

    def badge_radius(self) -> int:
        return self._badge_radius

    def set_badge_radius(self, value: int) -> None:
        value = max(MIN_BADGE_RADIUS, min(MAX_BADGE_RADIUS, int(value)))
        if value == self._badge_radius:
            return
        self._badge_radius = value
        self.request_update()

    def cell_overlay_visible(self, name: str) -> bool:
        return bool(self._cell_visible.get(str(name), True))

    def set_cell_overlay_visible(self, name: str, visible: bool) -> None:
        name = str(name)
        visible = bool(visible)
        if self.cell_overlay_visible(name) == visible:
            return
        self._cell_visible[name] = visible
        self.request_update()

    def set_visible_paths(self, paths) -> None:
        visible = tuple(dict.fromkeys(str(path) for path in paths if path))
        if visible == self._visible_paths:
            return
        self._visible_paths = visible

    def paint(self, painter: QtGui.QPainter, grid_view, map_rect: Callable[[QtCore.QRectF], QtCore.QRectF]) -> None:
        context = self._build_context(grid_view, map_rect)
        if not context.cells:
            return
        self._paint_cell_overlays(painter, context)
        if self._badge_visible:
            self._paint_badge_overlays(painter, context)

    def _paint_cell_overlays(self, painter: QtGui.QPainter, context: GridOverlayContext) -> None:
        for plugin in self._plugins:
            if not isinstance(plugin, BaseCellOverlayPlugin):
                continue
            if not self.cell_overlay_visible(plugin.NAME):
                continue
            for cell in context.cells:
                try:
                    plugin.paint_cell(painter, cell.viewport_rect, cell, context)
                except Exception as e:
                    AppLogger.warning(f"[GridOverlayHost] cell paint failed: {plugin.NAME}", exc=e)

    def _paint_badge_overlays(self, painter: QtGui.QPainter, context: GridOverlayContext) -> None:
        badges_by_cell: dict[int, tuple[GridOverlayCell, list[OverlayBadge]]] = {}
        for plugin in self._plugins:
            if not isinstance(plugin, BaseBadgeOverlayPlugin):
                continue
            prefix = getattr(plugin, "KEY_PREFIX", "")
            for cell in context.cells:
                values = self.values_for(plugin.NAME, cell.path) if prefix else ()
                for value in values:
                    try:
                        badge = plugin.badge_for_value(value, context)
                    except Exception as e:
                        AppLogger.warning(f"[GridOverlayHost] badge_for_value failed: {plugin.NAME}", exc=e)
                        continue
                    if badge is None:
                        continue
                    _cell, entries = badges_by_cell.setdefault(cell.index, (cell, []))
                    entries.append(badge)
        if badges_by_cell:
            self._draw_badges(painter, badges_by_cell)

    def _draw_badges(self, painter: QtGui.QPainter, badges_by_cell: dict[int, tuple[GridOverlayCell, list[OverlayBadge]]]) -> None:
        margin = dpix(4)
        size = max(dpix(8), dpix(self._badge_radius * 2))
        gap = max(1, size // 8)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        for cell, badges in badges_by_cell.values():
            cell_rect = cell.viewport_rect
            if cell_rect.width() <= margin * 2 or cell_rect.height() <= margin * 2:
                continue
            badges = sorted(badges, key=lambda b: b.priority, reverse=True)
            columns = max(1, int((cell_rect.width() - margin * 2 + gap) // (size + gap)))
            rows = max(1, min(3, int((cell_rect.height() - margin * 2 + gap) // (size + gap))))
            limit = max(1, columns * rows)
            visible_badges = list(badges[:limit])
            overflow = len(badges) - len(visible_badges)
            if overflow > 0 and limit > 1:
                visible_badges = visible_badges[: limit - 1]
                overflow = len(badges) - (limit - 1)
            elif overflow > 0:
                visible_badges = []
                overflow = len(badges)
            painter.save()
            painter.setClipRect(cell_rect)
            for offset, badge in enumerate(visible_badges):
                col = offset % columns
                row = offset // columns
                x = cell_rect.left() + margin + col * (size + gap)
                y = cell_rect.top() + margin + row * (size + gap)
                rect = QtCore.QRectF(x, y, size, size)
                try:
                    badge.paint(painter, rect)
                except Exception as e:
                    AppLogger.warning("[GridOverlayHost] badge paint failed", exc=e)
            if overflow > 0:
                offset = len(visible_badges)
                col = offset % columns
                row = offset // columns
                x = cell_rect.left() + margin + col * (size + gap)
                y = cell_rect.top() + margin + row * (size + gap)
                rect = QtCore.QRectF(x, y, size, size)
                from ....core.color.theme import ThemeManager

                draw_overflow_badge(painter, rect, overflow, QtGui.QColor(ThemeManager.instance().palette.bg_primary))
            painter.restore()
        painter.restore()

    def _bind_plugins(self) -> None:
        self._plugins.clear()
        self._plugins_by_name.clear()
        self._helpers.clear()
        for plugin_cls in grid_overlay_registry.list_all():
            instance = grid_overlay_registry.instance(plugin_cls.NAME)
            if not isinstance(instance, BaseOverlayPlugin):
                continue
            instance.bind_host(self)
            self._plugins.append(instance)
            self._plugins_by_name[instance.NAME] = instance
            prefix = getattr(instance, "KEY_PREFIX", "")
            scope = getattr(instance, "DATA_SCOPE", "*") or "*"
            if prefix:
                helper = OverlayHelper(scope, prefix, parent=self)
                helper.bind_host(self)
                self._helpers[instance.NAME] = helper

    def _build_context(self, grid_view, map_rect: Callable[[QtCore.QRectF], QtCore.QRectF]) -> GridOverlayContext:
        if not grid_view.visible_indices or not grid_view.rects:
            return GridOverlayContext((), self.database_path(), self.database_name())
        view_rect = grid_view._scene_view_rect()
        cells: list[GridOverlayCell] = []
        paths = grid_view.items.paths
        sources = grid_view.items.sources
        for index in sorted(grid_view.visible_indices):
            if index < 0 or index >= len(grid_view.rects) or index >= len(paths):
                continue
            rect = grid_view.rects[index]
            if not rect.intersects(view_rect):
                continue
            path = paths[index]
            if not path:
                continue
            scene_rect = QtCore.QRectF(rect)
            source = sources[index] if index < len(sources) else path
            cells.append(
                GridOverlayCell(
                    index=index,
                    path=str(path),
                    source=str(source or path),
                    scene_rect=scene_rect,
                    viewport_rect=map_rect(scene_rect),
                )
            )
        return GridOverlayContext(tuple(cells), self.database_path(), self.database_name())

    def _save_state(self) -> dict:
        return {
            "badge_visible": bool(self._badge_visible),
            "badge_radius": int(self._badge_radius),
            "cell_visible": dict(self._cell_visible),
        }

    def _restore_state(self, state: dict) -> None:
        if not isinstance(state, dict):
            return
        if "badge_visible" in state:
            self._badge_visible = bool(state["badge_visible"])
        if "badge_radius" in state:
            self._badge_radius = max(MIN_BADGE_RADIUS, min(MAX_BADGE_RADIUS, int(state["badge_radius"])))
        cell_visible = state.get("cell_visible")
        if isinstance(cell_visible, dict):
            self._cell_visible = {str(k): bool(v) for k, v in cell_visible.items()}
        self.request_update()

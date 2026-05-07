from __future__ import annotations

from ...plugin import BaseBadgeOverlayPlugin, GridOverlayContext, OverlayBadge
from .registry import MarkRegistry


class MarkBadgeOverlayPlugin(BaseBadgeOverlayPlugin):
    NAME = "mark_overlay"
    DEFAULT_ENABLED = True
    PRIORITY = 100
    DATA_SCOPE = "*"
    KEY_PREFIX = MarkRegistry.tag_prefix() + "."

    def bind_host(self, host) -> None:
        super().bind_host(host)
        if getattr(self, "_registry_changed_connected", False):
            return
        MarkRegistry.instance().changed.connect(self.request_update)
        self._registry_changed_connected = True

    def badge_for_value(self, value: str, context: GridOverlayContext) -> OverlayBadge | None:
        registry = MarkRegistry.instance()
        mark = registry.get(value)
        if mark is None:
            return None
        return OverlayBadge.from_mark(
            mark.mark_key,
            mark.color,
            priority=self.PRIORITY,
            tooltip=mark.name,
        )

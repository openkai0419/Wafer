from __future__ import annotations

import re

from ..registry import PluginRegistry

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_]\w*$")


class SortRegistry(PluginRegistry):
    def register(self, plugin_cls):
        mk = getattr(plugin_cls, "META_KEY", None)
        if mk is not None and not _IDENTIFIER_RE.fullmatch(mk):
            raise ValueError(f"Invalid META_KEY {mk!r} on {plugin_cls.__name__}")
        super().register(plugin_cls)


filter_registry = PluginRegistry()
sort_registry = SortRegistry()

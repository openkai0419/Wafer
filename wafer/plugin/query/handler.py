from __future__ import annotations

import re

from .base import BaseFilterPlugin, BaseSortPlugin

_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_]\w*$')


class FilterRegistry:

    def __init__(self):
        self._filters: dict[str, type[BaseFilterPlugin]] = {}

    def register(self, cls: type[BaseFilterPlugin]):
        self._filters[cls.NAME] = cls

    def get(self, name: str) -> type[BaseFilterPlugin] | None:
        return self._filters.get(name)

    def list_all(self) -> list[type[BaseFilterPlugin]]:
        return sorted(self._filters.values(), key=lambda c: c.PRIORITY, reverse=True)


class SortRegistry:

    def __init__(self):
        self._sorts: dict[str, type[BaseSortPlugin]] = {}

    def register(self, cls: type[BaseSortPlugin]):
        mk = getattr(cls, 'META_KEY', None)
        if mk is not None and not _IDENTIFIER_RE.fullmatch(mk):
            raise ValueError(f'Invalid META_KEY {mk!r} on {cls.__name__}')
        self._sorts[cls.NAME] = cls

    def get(self, name: str) -> type[BaseSortPlugin] | None:
        return self._sorts.get(name)

    def list_all(self) -> list[type[BaseSortPlugin]]:
        return sorted(self._sorts.values(), key=lambda c: c.PRIORITY, reverse=True)


filter_registry = FilterRegistry()
sort_registry = SortRegistry()

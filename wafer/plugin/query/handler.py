from __future__ import annotations

from .base import BaseFilterPlugin, BaseSortPlugin


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
        self._sorts[cls.NAME] = cls

    def get(self, name: str) -> type[BaseSortPlugin] | None:
        return self._sorts.get(name)

    def list_all(self) -> list[type[BaseSortPlugin]]:
        return sorted(self._sorts.values(), key=lambda c: c.PRIORITY, reverse=True)


filter_registry = FilterRegistry()
sort_registry = SortRegistry()


def register_builtins():
    from .builtin import (
        TextFilter, DirectoryFilter,
        NaturalPathSort, NaturalNameSort,
        ModifiedSort, CreatedSort, SizeSort, CollectedSort,
        RandomSort,
    )
    for cls in [TextFilter, DirectoryFilter]:
        filter_registry.register(cls)
    for cls in [NaturalPathSort, NaturalNameSort,
                ModifiedSort, CreatedSort, SizeSort, CollectedSort,
                RandomSort]:
        sort_registry.register(cls)


register_builtins()

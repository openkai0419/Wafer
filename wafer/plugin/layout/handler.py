from __future__ import annotations

from .base import BaseLayoutPlugin


class LayoutRegistry:

    def __init__(self):
        self._layouts: dict[str, type[BaseLayoutPlugin]] = {}

    def register(self, cls: type[BaseLayoutPlugin]):
        self._layouts[cls.NAME] = cls

    def get(self, name: str) -> type[BaseLayoutPlugin] | None:
        return self._layouts.get(name)

    def list_all(self) -> list[type[BaseLayoutPlugin]]:
        return sorted(self._layouts.values(), key=lambda c: c.PRIORITY, reverse=True)

    def names(self) -> list[str]:
        return [cls.NAME for cls in self.list_all()]


layout_registry = LayoutRegistry()

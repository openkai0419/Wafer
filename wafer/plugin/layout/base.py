from __future__ import annotations

from abc import ABC, abstractmethod

from ..registry import PluginBase


class BaseLayoutPlugin(PluginBase, ABC):
    DISPLAY_NAME: str = ''

    @classmethod
    @abstractmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing,
                          container_width, container_height, orientation):
        ...

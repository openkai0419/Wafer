import pytest
from wafer.plugin.layout.base import BaseLayoutPlugin
from wafer.plugin.registry import PluginRegistry


class _DummyLayout(BaseLayoutPlugin):
    NAME = "dummy"
    DISPLAY_NAME = "Dummy"
    PRIORITY = 50

    @classmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing, container_width, container_height, orientation):
        return None


class _HighPriorityLayout(BaseLayoutPlugin):
    NAME = "highpri"
    DISPLAY_NAME = "HighPri"
    PRIORITY = 200

    @classmethod
    def create_calculator(cls, aspect_ratios, base_size, spacing, container_width, container_height, orientation):
        return None


def test_register_and_get():
    reg = PluginRegistry()
    reg.register(_DummyLayout)
    assert reg.get("dummy") is _DummyLayout


def test_get_unknown_returns_none():
    reg = PluginRegistry()
    assert reg.get("nonexistent") is None


def test_list_all_sorted_by_priority():
    reg = PluginRegistry()
    reg.register(_DummyLayout)
    reg.register(_HighPriorityLayout)
    layouts = reg.list_all()
    assert layouts[0] is _HighPriorityLayout
    assert layouts[1] is _DummyLayout


def test_names():
    reg = PluginRegistry()
    reg.register(_DummyLayout)
    reg.register(_HighPriorityLayout)
    names = reg.names()
    assert "dummy" in names
    assert "highpri" in names
    assert names[0] == "highpri"


def test_register_overwrites_same_name():
    reg = PluginRegistry()
    reg.register(_DummyLayout)

    class _DummyLayout2(BaseLayoutPlugin):
        NAME = "dummy"
        DISPLAY_NAME = "Dummy2"
        PRIORITY = 99

        @classmethod
        def create_calculator(cls, *a, **kw):
            return None

    reg.register(_DummyLayout2)
    assert reg.get("dummy") is _DummyLayout2
    assert len(reg.list_all()) == 1

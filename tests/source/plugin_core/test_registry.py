import py_compile
import pytest

from source.plugin_core.registry import BasePlugin, PluginRegistry


def test_compile():
    py_compile.compile('source/plugin_core/registry.py')


class DummyPluginA(BasePlugin):
    NAME = 'a'
    EXTENSIONS = ('.txt',)
    PRIORITY = 50


class DummyPluginB(BasePlugin):
    NAME = 'b'
    EXTENSIONS = ('.txt', '.csv')
    PRIORITY = 100


class DummyPluginAll(BasePlugin):
    NAME = 'all'
    EXTENSIONS = ()
    PRIORITY = 0


class TestPluginRegistry:

    def test_register_and_plugins(self):
        reg = PluginRegistry()
        reg.register(DummyPluginA)
        reg.register(DummyPluginB)
        assert len(reg.plugins()) == 2

    def test_priority_order_descending(self):
        reg = PluginRegistry()
        reg.register(DummyPluginA)
        reg.register(DummyPluginB)
        plugins = reg.plugins()
        assert plugins[0] is DummyPluginB
        assert plugins[1] is DummyPluginA

    def test_resolve_returns_highest_priority(self):
        reg = PluginRegistry()
        reg.register(DummyPluginA)
        reg.register(DummyPluginB)
        assert reg.resolve('file.txt') is DummyPluginB

    def test_resolve_no_match(self):
        reg = PluginRegistry()
        reg.register(DummyPluginA)
        assert reg.resolve('file.xyz') is None

    def test_resolve_fallback_with_empty_extensions(self):
        reg = PluginRegistry()
        reg.register(DummyPluginA)
        reg.register(DummyPluginAll)
        assert reg.resolve('file.xyz') is DummyPluginAll

    def test_resolve_all(self):
        reg = PluginRegistry()
        reg.register(DummyPluginA)
        reg.register(DummyPluginB)
        reg.register(DummyPluginAll)
        matches = reg.resolve_all('file.txt')
        assert len(matches) == 3
        assert matches[0] is DummyPluginB
        assert matches[-1] is DummyPluginAll

    def test_resolve_all_no_match(self):
        reg = PluginRegistry()
        reg.register(DummyPluginA)
        matches = reg.resolve_all('file.xyz')
        assert len(matches) == 0

    def test_names(self):
        reg = PluginRegistry()
        reg.register(DummyPluginA)
        reg.register(DummyPluginB)
        names = reg.names()
        assert names == ['b', 'a']

    def test_info(self):
        reg = PluginRegistry()
        reg.register(DummyPluginA)
        info = reg.info()
        assert info == [('a', ('.txt',))]


class TestBasePluginMatch:

    def test_match_with_extensions(self):
        assert DummyPluginA.match('file.txt')
        assert not DummyPluginA.match('file.csv')

    def test_match_empty_extensions_matches_all(self):
        assert DummyPluginAll.match('file.txt')
        assert DummyPluginAll.match('file.anything')

    def test_match_case_insensitive(self):
        assert DummyPluginA.match('FILE.TXT')
        assert DummyPluginA.match('File.Txt')

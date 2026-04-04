import sys
import pytest
from PySide6 import QtWidgets

from wafer.plugin.registry import PluginBase, PluginRegistry
from wafer.plugin.panel.base import BasePanelPlugin
from wafer.plugin.panel.handler import panel_registry as _module_registry


class DummyPanel(BasePanelPlugin):
    NAME = "dummy"
    DISPLAY_NAME = "Dummy Panel"
    PRIORITY = 10

    def create_widget(self):
        return QtWidgets.QWidget()


class HighPriorityPanel(BasePanelPlugin):
    NAME = "dummy"
    DISPLAY_NAME = "Override Panel"
    PRIORITY = 100

    def create_widget(self):
        return QtWidgets.QWidget()


class UnclosablePanel(BasePanelPlugin):
    NAME = "unclosable"
    DISPLAY_NAME = "Unclosable"
    CLOSABLE = False

    def create_widget(self):
        return QtWidgets.QWidget()


class TestBasePanelPlugin:

    def test_inherits_plugin_base(self):
        assert issubclass(BasePanelPlugin, PluginBase)

    def test_default_attributes(self):
        assert BasePanelPlugin.DISPLAY_NAME == ''
        assert BasePanelPlugin.CLOSABLE is True
        assert BasePanelPlugin.PRIORITY == 0

    def test_concrete_panel_attributes(self):
        assert DummyPanel.NAME == "dummy"
        assert DummyPanel.DISPLAY_NAME == "Dummy Panel"
        assert DummyPanel.CLOSABLE is True

    def test_create_widget_returns_qwidget(self, qtbot):
        plugin = DummyPanel()
        widget = plugin.create_widget()
        qtbot.addWidget(widget)
        assert isinstance(widget, QtWidgets.QWidget)

    def test_closable_override(self):
        assert UnclosablePanel.CLOSABLE is False


class TestPanelRegistry:

    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        registry = PluginRegistry()
        self.registry = registry
        yield

    def test_register_and_list(self):
        self.registry.register(DummyPanel)
        result = self.registry.list_all()
        assert len(result) == 1
        assert result[0] is DummyPanel

    def test_priority_override(self):
        self.registry.register(DummyPanel)
        self.registry.register(HighPriorityPanel)
        result = self.registry.list_all()
        assert len(result) == 1
        assert result[0] is HighPriorityPanel

    def test_lower_priority_rejected(self):
        self.registry.register(HighPriorityPanel)
        self.registry.register(DummyPanel)
        result = self.registry.list_all()
        assert len(result) == 1
        assert result[0] is HighPriorityPanel

    def test_multiple_panels(self):
        self.registry.register(DummyPanel)
        self.registry.register(UnclosablePanel)
        result = self.registry.list_all()
        assert len(result) == 2
        names = {p.NAME for p in result}
        assert names == {"dummy", "unclosable"}


class TestModuleLevelRegistry:

    def test_module_registry_is_plugin_registry(self):
        assert isinstance(_module_registry, PluginRegistry)


class TestPluginDiscovery:

    def test_discover_finds_panel_plugin(self):
        from wafer.plugin.loader import _discover_plugins
        import types

        module = types.ModuleType('_test_panel_mod')
        module.DummyPanel = DummyPanel
        module.__dict__['DummyPanel'] = DummyPanel

        found = _discover_plugins(module)
        keys = [key for key, cls in found]
        assert 'panel' in keys

    def test_discover_ignores_base_class(self):
        from wafer.plugin.loader import _discover_plugins
        import types

        module = types.ModuleType('_test_panel_base')
        module.BasePanelPlugin = BasePanelPlugin
        module.__dict__['BasePanelPlugin'] = BasePanelPlugin

        found = _discover_plugins(module)
        panel_entries = [(k, c) for k, c in found if k == 'panel']
        assert len(panel_entries) == 0


class TestPluginLoaderIntegration:

    @pytest.fixture
    def panel_extension(self, tmp_path):
        ext_dir = tmp_path / 'extensions'
        panel_dir = ext_dir / 'test_panel'
        panel_dir.mkdir(parents=True)
        (panel_dir / '__init__.py').write_text('')
        (panel_dir / 'panel.py').write_text(
            'from PySide6 import QtWidgets\n'
            'from wafer.plugin.panel.base import BasePanelPlugin\n'
            'class TestExtPanel(BasePanelPlugin):\n'
            '    NAME = "test_ext_panel"\n'
            '    DISPLAY_NAME = "Test Extension Panel"\n'
            '    PRIORITY = 50\n'
            '    DEFAULT_ENABLED = True\n'
            '    def create_widget(self):\n'
            '        return QtWidgets.QLabel("Test")\n'
        )
        yield str(ext_dir)
        for key in list(sys.modules):
            if key.startswith('_plugins_test_panel'):
                del sys.modules[key]

    def test_loader_discovers_panel_plugin(self, panel_extension):
        from wafer.plugin.loader import PluginLoader
        from wafer.plugin.registry import PluginRegistry, FilePluginRegistry

        registries = {
            'viewer': FilePluginRegistry(),
            'grid': FilePluginRegistry(),
            'collector': FilePluginRegistry(),
            'filter': PluginRegistry(),
            'sort': PluginRegistry(),
            'layout': PluginRegistry(),
            'panel': PluginRegistry(),
            'rename_source': PluginRegistry(),
            'command': PluginRegistry(),
        }

        loader = PluginLoader(panel_extension, registries)
        loaded = loader.load_all()

        assert 'test_panel' in loaded
        panel_cls = registries['panel'].get('test_ext_panel')
        assert panel_cls is not None
        assert panel_cls.DISPLAY_NAME == "Test Extension Panel"

        plugin = panel_cls()
        widget = plugin.create_widget()
        assert isinstance(widget, QtWidgets.QLabel)
        assert widget.text() == "Test"

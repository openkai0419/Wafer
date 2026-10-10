import pytest
from unittest.mock import MagicMock, patch
from PySide6 import QtWidgets

from wafer.builtins.commands.panel import PanelCommands, open_panel, solo_current_panel, solo_panel
from wafer.plugin.panel.base import BasePanelPlugin
from wafer.qt.layout.manager import LayoutManager


class _BuiltinPanel(BasePanelPlugin):
    NAME = "builtin_test"
    DISPLAY_NAME = "Builtin Test"
    SOURCE = "Builtin"

    def create_widget(self):
        return QtWidgets.QWidget()


class _PluginPanel(BasePanelPlugin):
    NAME = "plugin_test"
    DISPLAY_NAME = "Plugin Test"

    def create_widget(self):
        return QtWidgets.QWidget()


class _PluginPanel2(BasePanelPlugin):
    NAME = "plugin_test2"
    DISPLAY_NAME = "Plugin Test 2"
    SOURCE = "Plugin"

    def create_widget(self):
        return QtWidgets.QWidget()


class _Ctx:
    def __init__(self, window, widget=None):
        self._window = window
        self._widget = widget

    def get_instance(self, name):
        return self._window if name == "MainWindow" else None


class TestPanelCommandsCategories:
    def test_commands_separates_core_builtin_plugin(self):
        from wafer.plugin.registry import PluginRegistry

        mock_registry = PluginRegistry()
        mock_registry.register(_BuiltinPanel)
        mock_registry.register(_PluginPanel)
        mock_registry.register(_PluginPanel2)

        with patch("wafer.plugin.panel.handler.panel_registry", mock_registry):
            items = PanelCommands.commands()

        separators = [i for i, x in enumerate(items) if x == "-"]
        assert len(separators) == 5

        core_start = separators[1] + 1
        core_sep = separators[2]
        builtin_sep = separators[3]
        plugin_sep = separators[4]

        core_ids = items[core_start:core_sep]
        for name in PanelCommands._CORE_PANELS:
            assert LayoutManager._command_id(name) in core_ids

        builtin_ids = items[core_sep + 1 : builtin_sep]
        assert LayoutManager._command_id("Builtin Test") in builtin_ids

        plugin_ids = items[builtin_sep + 1 : plugin_sep]
        assert LayoutManager._command_id("Plugin Test") in plugin_ids
        assert LayoutManager._command_id("Plugin Test 2") in plugin_ids

    def test_commands_no_builtin_no_extra_separator(self):
        from wafer.plugin.registry import PluginRegistry

        mock_registry = PluginRegistry()
        mock_registry.register(_PluginPanel)

        with patch("wafer.plugin.panel.handler.panel_registry", mock_registry):
            items = PanelCommands.commands()

        separators = [i for i, x in enumerate(items) if x == "-"]
        assert len(separators) == 4

    def test_commands_no_plugin_no_extra_separator(self):
        from wafer.plugin.registry import PluginRegistry

        mock_registry = PluginRegistry()
        mock_registry.register(_BuiltinPanel)

        with patch("wafer.plugin.panel.handler.panel_registry", mock_registry):
            items = PanelCommands.commands()

        separators = [i for i, x in enumerate(items) if x == "-"]
        assert len(separators) == 4

    def test_commands_empty_registry_only_core(self):
        from wafer.plugin.registry import PluginRegistry

        mock_registry = PluginRegistry()

        with patch("wafer.plugin.panel.handler.panel_registry", mock_registry):
            items = PanelCommands.commands()

        separators = [i for i, x in enumerate(items) if x == "-"]
        assert len(separators) == 3

    def test_solo_current_notifies_when_context_is_not_panel(self, qtbot):
        win = QtWidgets.QMainWindow()
        qtbot.addWidget(win)
        holder = type("Window", (), {})()
        holder._layout_manager = LayoutManager(win)
        ctx = _Ctx(holder, QtWidgets.QWidget())

        with patch("wafer.builtins.commands.panel.Notifier.warning") as warning:
            solo_current_panel(ctx)

        warning.assert_called_once()

    def test_solo_panel_notifies_when_target_is_dormant(self, qtbot):
        win = QtWidgets.QMainWindow()
        qtbot.addWidget(win)
        mgr = LayoutManager(win)
        mgr.register("Dormant", QtWidgets.QWidget)
        holder = type("Window", (), {})()
        holder._layout_manager = mgr
        ctx = _Ctx(holder)

        with patch("wafer.builtins.commands.panel.Notifier.warning") as warning:
            solo_panel(ctx, "Dormant")

        warning.assert_called_once()


class TestOpenPanel:
    def _swap_instance(self, name, value):
        from wafer.qt.commands.binding.instance_registry import InstanceRegistry

        registry = InstanceRegistry.instance()
        previous = list(registry._by_name.get(name, []))
        if value is None:
            registry._by_name.pop(name, None)
        else:
            registry._by_name[name] = [value]

        def restore():
            if previous:
                registry._by_name[name] = previous
            else:
                registry._by_name.pop(name, None)

        return restore

    def test_open_panel_toggles_panel_with_mainwindow(self):
        mock_w = MagicMock()
        mock_w._layout_manager.panel_names.return_value = ["Batch Renamer"]
        restore = self._swap_instance("MainWindow", mock_w)
        try:
            open_panel(name="Batch Renamer")
        finally:
            restore()
        mock_w._layout_manager.toggle_panel.assert_called_once_with("Batch Renamer")

    def test_open_panel_standalone_without_mainwindow(self, monkeypatch):
        from wafer.builtins.batch_renamer.widget import BatchRenamerPlugin
        from wafer.plugin.panel.handler import panel_registry

        captured = {}

        def fake_open(factory, title, key, size=None, parent=None):
            captured.update(title=title, key=key)
            return object()

        monkeypatch.setattr("wafer.qt.layout.standalone.open_standalone", fake_open)
        had = panel_registry.get(BatchRenamerPlugin.NAME) is not None
        if not had:
            panel_registry.register(BatchRenamerPlugin)
        restore = self._swap_instance("MainWindow", None)
        try:
            open_panel(name="Batch Renamer")
        finally:
            restore()
            if not had:
                panel_registry._plugins.pop(BatchRenamerPlugin.NAME, None)
                panel_registry._instances.pop(BatchRenamerPlugin.NAME, None)
        assert captured["key"] == "batch_renamer"
        assert captured["title"] == "Batch Renamer"

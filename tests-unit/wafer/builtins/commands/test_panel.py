import pytest
from unittest.mock import patch
from PySide6 import QtWidgets

from wafer.builtins.commands.panel import PanelCommands, solo_current_panel, solo_panel
from wafer.plugin.panel.base import BasePanelPlugin
from wafer.ui.layout.manager import LayoutManager


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
    def test_workspace_is_not_a_core_panel(self):
        assert "Workspace" not in PanelCommands._CORE_PANELS

    def test_commands_contains_param_based_solo_commands(self):
        items = PanelCommands.commands()
        solo = next(x for x in items if getattr(x, "path", "") == "panel.solo")
        current = next(x for x in items if getattr(x, "path", "") == "panel.solo_current")

        assert ":Solo" in items
        assert solo.params[0].name == "name"
        assert solo.params[0].required is True
        assert callable(solo.params[0].choices_fn)
        assert current.params == []

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

        builtin_ids = items[core_sep + 1:builtin_sep]
        assert LayoutManager._command_id("Builtin Test") in builtin_ids

        plugin_ids = items[builtin_sep + 1:plugin_sep]
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

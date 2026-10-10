import sys
from unittest.mock import MagicMock, patch
from PySide6 import QtCore, QtWidgets

from wafer.plugin.registry import BasePlugin, PluginBase
from wafer.plugin.badges import ExtensionBadge
from wafer.plugin.panel.base import BasePanelPlugin
from wafer.plugin.installer import InstallState
from wafer.builtins.plugin_manager.badge_texts import HEAVY_BADGE_TOOLTIP, HEAVY_INSTALL_TITLE


class TestExtensionsTab:
    def test_collect_enabled_returns_checked(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "my_ext").mkdir(parents=True)
        (ext_dir / "my_ext" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.resolve_install_state",
            lambda folder: InstallState.INSTALLED,
        )

        class FakePlugin(BasePlugin):
            NAME = "fake_p"
            EXTENSIONS = (".fake",)
            PRIORITY = 1

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.PluginLoader.discover_extension",
            staticmethod(lambda folder: [("grid", FakePlugin)]),
        )
        from wafer.qt.common.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab({"grid:FakePlugin": True}, dispatcher)
        qtbot.waitUntil(lambda: "my_ext" in tab._cards and len(tab._cards["my_ext"]._rows) > 0, timeout=3000)
        result = tab.collect_enabled()
        assert "grid:FakePlugin" in result

    def test_needs_setup_shows_button(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "uninstalled").mkdir(parents=True)
        (ext_dir / "uninstalled" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.resolve_install_state",
            lambda folder: InstallState.NOT_INSTALLED,
        )
        from wafer.qt.common.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab({}, dispatcher)
        qtbot.waitUntil(lambda: "uninstalled" in tab._cards, timeout=3000)
        card = tab._cards["uninstalled"]
        assert card._status_btn.isEnabled()
        assert card._status_btn.text() == "Install"
        assert len(card._rows) == 0

    def test_default_enabled_none_uses_attribute(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.resolve_install_state",
            lambda folder: InstallState.INSTALLED,
        )

        class EnabledPlugin(BasePlugin):
            NAME = "enabled_p"
            EXTENSIONS = (".e",)
            PRIORITY = 1
            DEFAULT_ENABLED = True

        class DisabledPlugin(BasePlugin):
            NAME = "disabled_p"
            EXTENSIONS = (".d",)
            PRIORITY = 1
            DEFAULT_ENABLED = False

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.PluginLoader.discover_extension",
            staticmethod(lambda folder: [("grid", EnabledPlugin), ("grid", DisabledPlugin)]),
        )
        from wafer.qt.common.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab(None, dispatcher)
        qtbot.waitUntil(lambda: "ext1" in tab._cards and len(tab._cards["ext1"]._rows) > 0, timeout=3000)

        enabled = tab.collect_enabled()
        assert "grid:EnabledPlugin" in enabled
        assert "grid:DisabledPlugin" not in enabled

    def test_enabled_changed_signal(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.resolve_install_state",
            lambda folder: InstallState.INSTALLED,
        )

        class FP(BasePlugin):
            NAME = "fp"
            EXTENSIONS = (".fp",)
            PRIORITY = 1

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.PluginLoader.discover_extension",
            staticmethod(lambda folder: [("viewer", FP)]),
        )
        from wafer.qt.common.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab({"viewer:FP": True}, dispatcher)
        qtbot.waitUntil(lambda: "ext1" in tab._cards and len(tab._cards["ext1"]._rows) > 0, timeout=3000)

        signals = []
        tab.enabled_changed.connect(lambda: signals.append(True))
        row, _, _ = tab._cards["ext1"]._rows[0]
        row.checkbox.setChecked(False)
        assert len(signals) >= 1

    def test_collect_enabled_overrides_returns_default_diff_only(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.resolve_install_state",
            lambda folder: InstallState.INSTALLED,
        )

        class EnabledPlugin(BasePlugin):
            NAME = "enabled_p"
            EXTENSIONS = (".e",)
            PRIORITY = 1
            DEFAULT_ENABLED = True

        class DisabledPlugin(BasePlugin):
            NAME = "disabled_p"
            EXTENSIONS = (".d",)
            PRIORITY = 1
            DEFAULT_ENABLED = False

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.PluginLoader.discover_extension",
            staticmethod(lambda folder: [("grid", EnabledPlugin), ("grid", DisabledPlugin)]),
        )
        from wafer.qt.common.dispatcher import Dispatcher
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab({}, Dispatcher())
        qtbot.waitUntil(lambda: "ext1" in tab._cards and len(tab._cards["ext1"]._rows) == 2, timeout=3000)

        assert tab.collect_enabled_overrides() == {}

        rows = {qualified: row for row, qualified, _ in tab._cards["ext1"]._rows}
        rows["grid:EnabledPlugin"].checkbox.setChecked(False)
        rows["grid:DisabledPlugin"].checkbox.setChecked(True)

        assert tab.collect_enabled_overrides() == {
            "grid:DisabledPlugin": True,
            "grid:EnabledPlugin": False,
        }

    def test_collect_enabled_plugins_by_type(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.resolve_install_state",
            lambda folder: InstallState.INSTALLED,
        )

        class ViewerP(BasePlugin):
            NAME = "vp"
            EXTENSIONS = (".v",)
            PRIORITY = 1

        class GridP(BasePlugin):
            NAME = "gp"
            EXTENSIONS = (".g",)
            PRIORITY = 2

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.PluginLoader.discover_extension",
            staticmethod(lambda folder: [("viewer", ViewerP), ("grid", GridP)]),
        )
        from wafer.qt.common.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab({"viewer:ViewerP": True, "grid:GridP": True}, dispatcher)
        qtbot.waitUntil(lambda: "ext1" in tab._cards and len(tab._cards["ext1"]._rows) > 0, timeout=3000)

        viewers = tab.collect_enabled_plugins("viewer")
        grids = tab.collect_enabled_plugins("grid")
        assert ViewerP in viewers
        assert GridP in grids
        assert len(viewers) == 1
        assert len(grids) == 1

    def test_discover_shows_installed_when_setup_complete(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.resolve_install_state",
            lambda folder: InstallState.NO_DEPS,
        )

        class NoPostPlugin(BasePlugin):
            NAME = "nop"
            EXTENSIONS = (".np",)
            PRIORITY = 1

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.PluginLoader.discover_extension",
            staticmethod(lambda folder: [("grid", NoPostPlugin)]),
        )

        from wafer.qt.common.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab({}, dispatcher)

        qtbot.waitUntil(lambda: "ext1" in tab._cards and len(tab._cards["ext1"]._rows) > 0, timeout=3000)
        card = tab._cards["ext1"]
        assert card._status_btn.text() == "No Dependencies"

    def test_install_enqueues_and_marks_restart_required(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        (ext_dir / "ext1" / "requirements.txt").write_text("some-pkg\n")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.resolve_install_state",
            lambda folder: InstallState.NOT_INSTALLED,
        )
        from wafer.qt.common.dispatcher import Dispatcher
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab
        from wafer.plugin import installer_queue

        tab = ExtensionsTab({}, Dispatcher())
        qtbot.waitUntil(lambda: "ext1" in tab._cards, timeout=3000)
        tab._install_extension(tab._cards["ext1"])
        assert "ext1" in installer_queue.queued_names(str(ext_dir))
        assert tab._cards["ext1"]._status_btn.text() == "Restart Required"

    def test_heavy_install_uses_no_icon_confirmation(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "wd14").mkdir(parents=True)
        (ext_dir / "wd14" / "__init__.py").write_text("")
        (ext_dir / "wd14" / "requirements.txt").write_text("some-pkg\n")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.resolve_install_state",
            lambda folder: InstallState.NOT_INSTALLED,
        )
        from wafer.qt.common.dispatcher import Dispatcher
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab({}, Dispatcher())
        qtbot.waitUntil(lambda: "wd14" in tab._cards, timeout=3000)
        card = tab._cards["wd14"]
        card.badge = ExtensionBadge.HEAVY

        captured = {}

        def fake_exec(message_box):
            captured["title"] = message_box.windowTitle()
            captured["text"] = message_box.text()
            captured["icon"] = message_box.icon()
            return QtWidgets.QMessageBox.Cancel

        monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fake_exec)

        tab._install_extension(card)

        assert captured["title"] == HEAVY_INSTALL_TITLE
        assert captured["icon"] == QtWidgets.QMessageBox.NoIcon
        assert HEAVY_BADGE_TOOLTIP in captured["text"]

    def test_cancel_dequeues(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        (ext_dir / "ext1" / "requirements.txt").write_text("some-pkg\n")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.resolve_install_state",
            lambda folder: InstallState.NOT_INSTALLED,
        )
        from wafer.qt.common.dispatcher import Dispatcher
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab
        from wafer.plugin import installer_queue

        tab = ExtensionsTab({}, Dispatcher())
        qtbot.waitUntil(lambda: "ext1" in tab._cards, timeout=3000)
        tab._install_extension(tab._cards["ext1"])
        tab._cancel_extension(tab._cards["ext1"])
        assert installer_queue.queued_names(str(ext_dir)) == set()


class TestPluginRowPanelButton:
    def test_panel_row_has_open_button(self, qtbot):
        from wafer.builtins.plugin_manager.extensions_tab import _PluginRow

        class FakePanel(PluginBase):
            NAME = "test_panel"
            DISPLAY_NAME = "Test Panel"
            PRIORITY = 1

        row = _PluginRow("panel", FakePanel, True)
        qtbot.addWidget(row)
        assert row.panel_btn is not None
        assert row.panel_btn.toolTip() == "Open Test Panel"

    def test_non_panel_row_has_no_button(self, qtbot):
        from wafer.builtins.plugin_manager.extensions_tab import _PluginRow

        class FakeGrid(BasePlugin):
            NAME = "test_grid"
            EXTENSIONS = (".g",)
            PRIORITY = 1

        row = _PluginRow("grid", FakeGrid, True)
        qtbot.addWidget(row)
        assert row.panel_btn is None

    def test_kind_badges_use_short_labels_and_fixed_width(self, qtbot):
        from wafer.builtins.plugin_manager.extensions_tab import _PLUGIN_KIND_BADGE_WIDTH, _PluginRow
        from wafer.plugin.kinds import PLUGIN_KIND_IMAGE_LOADER, PLUGIN_KIND_KEY_VALUE_PANEL, PLUGIN_KIND_PARSER
        from wafer.qt.common.dpi import dpix

        class FakePlugin(BasePlugin):
            NAME = "test_plugin"
            EXTENSIONS = ()
            PRIORITY = 1

        expected = {
            PLUGIN_KIND_IMAGE_LOADER: "Loader",
            PLUGIN_KIND_KEY_VALUE_PANEL: "Data",
            PLUGIN_KIND_PARSER: "Parser",
        }
        widths = set()
        for registry_key, label in expected.items():
            row = _PluginRow(registry_key, FakePlugin, True)
            qtbot.addWidget(row)
            badge = row.findChild(QtWidgets.QLabel, "plugin_kind_badge")
            assert badge.text() == label
            assert badge.text() != registry_key
            assert badge.minimumWidth() == dpix(_PLUGIN_KIND_BADGE_WIDTH)
            assert badge.maximumWidth() == dpix(_PLUGIN_KIND_BADGE_WIDTH)
            widths.add(badge.minimumWidth())
        assert len(widths) == 1

    def test_panel_row_uses_name_when_no_display_name(self, qtbot):
        from wafer.builtins.plugin_manager.extensions_tab import _PluginRow

        class NoDisplayPanel(PluginBase):
            NAME = "bare_panel"
            DISPLAY_NAME = ""
            PRIORITY = 1

        row = _PluginRow("panel", NoDisplayPanel, True)
        qtbot.addWidget(row)
        assert row.panel_btn.toolTip() == "Open bare_panel"

    def test_panel_button_calls_toggle(self, qtbot, monkeypatch):
        from wafer.builtins.plugin_manager.extensions_tab import _PluginRow
        from wafer.plugin.panel.handler import panel_registry

        class FakePanel(PluginBase):
            NAME = "tp"
            DISPLAY_NAME = "My Panel"
            PRIORITY = 1

        panel_registry.register(FakePanel)
        try:
            row = _PluginRow("panel", FakePanel, True)
            qtbot.addWidget(row)
            assert row.panel_btn.isEnabled()

            toggled = []
            monkeypatch.setattr(
                "wafer.builtins.plugin_manager.extensions_tab._PluginRow._toggle_panel",
                staticmethod(lambda n: toggled.append(n)),
            )
            row.panel_btn.click()
            assert toggled == ["My Panel"]
        finally:
            panel_registry._plugins.pop("tp", None)

    def test_panel_button_disabled_when_not_registered(self, qtbot):
        from wafer.builtins.plugin_manager.extensions_tab import _PluginRow

        class UnloadedPanel(PluginBase):
            NAME = "__unloaded_test_panel__"
            DISPLAY_NAME = "Unloaded"
            PRIORITY = 1

        row = _PluginRow("panel", UnloadedPanel, True)
        qtbot.addWidget(row)
        assert row.panel_btn is not None
        assert not row.panel_btn.isEnabled()


class TestOrderTab:
    def test_populate_with_plugin_lists(self, qtbot):
        from wafer.builtins.plugin_manager.viewers_tab import OrderTab

        class PlugA(BasePlugin):
            NAME = "a"
            EXTENSIONS = (".a",)
            PRIORITY = 10

        class PlugB(BasePlugin):
            NAME = "b"
            EXTENSIONS = (".b",)
            PRIORITY = 20

        tab = OrderTab({"viewer": [PlugB, PlugA], "grid": [PlugA]}, {})
        qtbot.addWidget(tab)

        orders = tab.get_orders()
        assert "b" in orders["viewer"]
        assert "a" in orders["viewer"]

    def test_order_from_settings(self, qtbot):
        from wafer.builtins.plugin_manager.viewers_tab import OrderTab

        class PlugX(BasePlugin):
            NAME = "x"
            EXTENSIONS = ()
            PRIORITY = 10

        class PlugY(BasePlugin):
            NAME = "y"
            EXTENSIONS = ()
            PRIORITY = 5

        tab = OrderTab({"viewer": [PlugX, PlugY]}, {"viewer": ["y", "x"]})
        qtbot.addWidget(tab)

        assert tab.get_orders()["viewer"] == ["y", "x"]

    def test_negative_priority_sorts_after_ordered(self, qtbot):
        from wafer.builtins.plugin_manager.viewers_tab import OrderTab

        class Builtin(BasePlugin):
            NAME = "builtin"
            EXTENSIONS = ()
            PRIORITY = -100

        class UserPlug(BasePlugin):
            NAME = "user"
            EXTENSIONS = ()
            PRIORITY = 10

        tab = OrderTab({"viewer": [Builtin, UserPlug]}, {"viewer": ["user"]})
        qtbot.addWidget(tab)
        order = tab.get_orders()["viewer"]
        assert order[0] == "user"
        assert order[1] == "builtin"

    def test_refresh_updates_list(self, qtbot):
        from wafer.builtins.plugin_manager.viewers_tab import OrderTab

        class PlugA(BasePlugin):
            NAME = "a"
            EXTENSIONS = (".a",)
            PRIORITY = 10

        class PlugB(BasePlugin):
            NAME = "b"
            EXTENSIONS = (".b",)
            PRIORITY = 20

        tab = OrderTab({"viewer": [PlugA]}, {})
        qtbot.addWidget(tab)
        assert tab.get_orders()["viewer"] == ["a"]

        tab.refresh({"viewer": [PlugB, PlugA]})
        viewer_order = tab.get_orders()["viewer"]
        assert "a" in viewer_order
        assert "b" in viewer_order
        assert len(viewer_order) == 2

    def test_multiple_registry_types(self, qtbot):
        from wafer.builtins.plugin_manager.viewers_tab import OrderTab

        class ViewerP(BasePlugin):
            NAME = "vp"
            EXTENSIONS = (".v",)
            PRIORITY = 10

        class FilterP:
            NAME = "fp"
            PRIORITY = 5

        tab = OrderTab({"viewer": [ViewerP], "filter": [FilterP]}, {})
        qtbot.addWidget(tab)
        orders = tab.get_orders()
        assert orders["viewer"] == ["vp"]
        assert orders["filter"] == ["fp"]

    def test_empty_registry_skipped(self, qtbot):
        from wafer.builtins.plugin_manager.viewers_tab import OrderTab

        class PlugA(BasePlugin):
            NAME = "a"
            EXTENSIONS = ()
            PRIORITY = 10

        tab = OrderTab({"viewer": [PlugA], "filter": []}, {})
        qtbot.addWidget(tab)
        assert tab.get_orders()["viewer"] == ["a"]
        assert tab.get_orders()["filter"] == []

    def test_refresh_updates_builtin_command_names(self, qtbot):
        from wafer.builtins.plugin_manager.viewers_tab import OrderTab
        from wafer.qt.commands.command.menu import MenuGroup

        class BuiltinCmd(MenuGroup):
            NAME = "FileViewer"
            PRIORITY = 0

            @classmethod
            def commands(cls):
                return []

        class ExtCmd(MenuGroup):
            NAME = "Video"
            PRIORITY = 1000

            @classmethod
            def commands(cls):
                return []

        tab = OrderTab(
            {"command": [ExtCmd]},
            {},
            builtin_command_names={"FileViewer", "Video"},
        )
        qtbot.addWidget(tab)
        assert tab.get_orders()["command"] == []

        tab.refresh(
            {"command": [ExtCmd]},
            builtin_command_names={"FileViewer"},
        )
        assert tab.get_orders()["command"] == ["Video"]


class TestPluginManagerWidget:
    def test_restart_button_runs_restart_all(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: "/nonexistent",
        )
        from wafer.builtins.plugin_manager.widget import PluginManagerWidget

        run = MagicMock()
        monkeypatch.setattr("wafer.builtins.plugin_manager.widget.Command.run", run)
        widget = PluginManagerWidget()
        qtbot.addWidget(widget)

        qtbot.mouseClick(widget._restart_btn, QtCore.Qt.LeftButton)
        run.assert_called_once_with("win.restart_all")

    def test_has_plugin_changes_detects_enabled_diff(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: "/nonexistent",
        )
        from wafer.builtins.plugin_manager.widget import PluginManagerWidget

        dlg = PluginManagerWidget()
        qtbot.addWidget(dlg)
        dlg._initial_enabled_overrides = {"a": False, "b": True}
        dlg._initial_orders = {"grid": ["a"]}
        assert not dlg._has_plugin_changes({"a": False, "b": True}, {"grid": ["a"]})
        assert dlg._has_plugin_changes({"a": False, "b": True, "c": False}, {"grid": ["a"]})
        assert dlg._has_plugin_changes({"a": False, "b": True}, {"grid": ["b", "a"]})

    def test_send_delete_dispatches_to_node(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: "/nonexistent",
        )
        from wafer.builtins.plugin_manager.widget import PluginManagerWidget

        mock_node = MagicMock()
        from wafer.qt.commands.binding.instance_registry import InstanceRegistry

        monkeypatch.setattr(InstanceRegistry.instance(), "resolve_node", lambda: mock_node)
        dlg = PluginManagerWidget()
        qtbot.addWidget(dlg)
        dlg._send_delete([("db1", "exif")], True)
        mock_node.send_reliable.assert_called_once_with(
            "recollect",
            {"mode": "reset", "collector": "exif", "sources": None, "prefixes": None, "keys": None, "delete": True, "re_collect": True},
            dst="indexer",
            db="db1",
        )

    def test_restart_label_hidden_when_no_pending(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: "/nonexistent",
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.widget.get_plugin_dir",
            lambda: "/nonexistent",
        )
        from wafer.builtins.plugin_manager.widget import PluginManagerWidget

        dlg = PluginManagerWidget()
        qtbot.addWidget(dlg)
        assert dlg._restart_label.isHidden()

    def test_restart_label_shows_scope(self, qtbot, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(tmp_path),
        )
        from wafer.plugin.installer import RestartScope
        from wafer.builtins.plugin_manager.widget import PluginManagerWidget

        expected = {
            RestartScope.VIEWER: "Viewer Restart Required",
            RestartScope.TRAY: "Background Restart Required",
            RestartScope.ALL: "Both Restart Required",
        }
        for scope, text in expected.items():
            monkeypatch.setattr(
                "wafer.builtins.plugin_manager.widget.PluginSettings.needs_restart",
                lambda self, d, scope=scope: scope,
            )
            dlg = PluginManagerWidget()
            qtbot.addWidget(dlg)
            assert not dlg._restart_label.isHidden()
            assert dlg._restart_label.text() == text


class TestToolCommands:
    def test_command_class_exists(self):
        from wafer.builtins.commands.tools import ToolCommands

        cmds = ToolCommands.commands()
        assert len(cmds) >= 1
        paths = [c.path for c in cmds if hasattr(c, "path")]
        assert "setting.plugin_manager" in paths

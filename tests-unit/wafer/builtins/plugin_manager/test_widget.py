import os
import sys
import pytest
from unittest.mock import MagicMock, patch

from wafer.plugin.registry import BasePlugin, PluginBase
from wafer.plugin.panel.base import BasePanelPlugin


class TestExtensionsTab:
    def test_scan_finds_extension_folders(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "test_ext").mkdir(parents=True)
        (ext_dir / "test_ext" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: False,
        )
        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.PluginLoader.discover_extension",
            staticmethod(lambda folder: []),
        )
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab(set(), dispatcher)
        assert "test_ext" in tab._cards

    def test_collect_enabled_returns_checked(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "my_ext").mkdir(parents=True)
        (ext_dir / "my_ext" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: False,
        )

        class FakePlugin(BasePlugin):
            NAME = "fake_p"
            EXTENSIONS = (".fake",)
            PRIORITY = 1

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.PluginLoader.discover_extension",
            staticmethod(lambda folder: [("grid", FakePlugin)]),
        )
        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab({"grid:FakePlugin"}, dispatcher)
        qtbot.waitUntil(lambda: len(tab._cards["my_ext"]._rows) > 0, timeout=3000)
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
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: True,
        )
        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab(set(), dispatcher)
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
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: False,
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
        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab(None, dispatcher)
        qtbot.waitUntil(lambda: len(tab._cards["ext1"]._rows) > 0, timeout=3000)

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
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: False,
        )

        class FP(BasePlugin):
            NAME = "fp"
            EXTENSIONS = (".fp",)
            PRIORITY = 1

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.PluginLoader.discover_extension",
            staticmethod(lambda folder: [("viewer", FP)]),
        )
        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab({"viewer:FP"}, dispatcher)
        qtbot.waitUntil(lambda: len(tab._cards["ext1"]._rows) > 0, timeout=3000)

        signals = []
        tab.enabled_changed.connect(lambda: signals.append(True))
        row, _ = tab._cards["ext1"]._rows[0]
        row.checkbox.setChecked(False)
        assert len(signals) >= 1

    def test_collect_enabled_plugins_by_type(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: False,
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
        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab({"viewer:ViewerP", "grid:GridP"}, dispatcher)
        qtbot.waitUntil(lambda: len(tab._cards["ext1"]._rows) > 0, timeout=3000)

        viewers = tab.collect_enabled_plugins("viewer")
        grids = tab.collect_enabled_plugins("grid")
        assert ViewerP in viewers
        assert GridP in grids
        assert len(viewers) == 1
        assert len(grids) == 1

    def test_install_checks_shared_first(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        (ext_dir / "ext1" / "requirements.txt").write_text("some-pkg\n")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: True,
        )
        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab(set(), dispatcher)

        called = []

        class DummyPlugin(BasePlugin):
            NAME = "dummy"
            EXTENSIONS = (".d",)
            PRIORITY = 1

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.install_extension",
            lambda d, e, on_progress=None, is_cancelled=None: (
                called.append("install_extension"),
                (True, True, [("grid", DummyPlugin)]),
            )[1],
        )

        card = tab._cards["ext1"]
        tab._install_extension(card)
        qtbot.waitUntil(lambda: len(called) > 0, timeout=5000)
        assert called == ["install_extension"]

    def test_install_skips_extension_on_shared_failure(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        (ext_dir / "ext1" / "requirements.txt").write_text("some-pkg\n")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: True,
        )
        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab(set(), dispatcher)

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.install_extension",
            lambda d, e, on_progress=None, is_cancelled=None: (False, False, []),
        )

        card = tab._cards["ext1"]
        tab._install_extension(card)
        import time

        time.sleep(1)
        qtbot.wait(200)
        assert len(card._rows) == 0

    def test_post_install_failure_shows_retry(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        (ext_dir / "ext1" / "requirements.txt").write_text("some-pkg\n")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: True,
        )

        class FailPostPlugin(BasePlugin):
            NAME = "fail_post"
            EXTENSIONS = (".fp",)
            PRIORITY = 1

            @classmethod
            def post_install(cls, plugin_dir, on_progress=None):
                raise RuntimeError("download failed")

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.install_extension",
            lambda d, e, on_progress=None, is_cancelled=None: (True, False, [("grid", FailPostPlugin)]),
        )

        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab(set(), dispatcher)
        card = tab._cards["ext1"]
        tab._install_extension(card)

        qtbot.waitUntil(lambda: card._status_btn.text() == "Retry", timeout=5000)
        assert card._status_btn.isEnabled()
        assert len(card._rows) > 0

    def test_post_install_success_writes_stamp(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        (ext_dir / "ext1" / "requirements.txt").write_text("some-pkg\n")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: True,
        )

        class OkPlugin(BasePlugin):
            NAME = "ok_p"
            EXTENSIONS = (".ok",)
            PRIORITY = 1

            @classmethod
            def post_install(cls, plugin_dir, on_progress=None):
                pass

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.install_extension",
            lambda d, e, on_progress=None, is_cancelled=None: (True, True, [("grid", OkPlugin)]),
        )

        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab(set(), dispatcher)
        card = tab._cards["ext1"]
        tab._install_extension(card)

        qtbot.waitUntil(lambda: card._status_btn.text() == "Installed", timeout=5000)

    def test_needs_setup_true_shows_install(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: True,
        )

        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab(set(), dispatcher)

        card = tab._cards["ext1"]
        assert card._status_btn.text() == "Install"
        assert card._status_btn.isEnabled()

    def test_discover_shows_installed_when_setup_complete(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "ext1").mkdir(parents=True)
        (ext_dir / "ext1" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: False,
        )

        class NoPostPlugin(BasePlugin):
            NAME = "nop"
            EXTENSIONS = (".np",)
            PRIORITY = 1

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.PluginLoader.discover_extension",
            staticmethod(lambda folder: [("grid", NoPostPlugin)]),
        )

        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab(set(), dispatcher)

        qtbot.waitUntil(lambda: len(tab._cards["ext1"]._rows) > 0, timeout=3000)
        card = tab._cards["ext1"]
        assert card._status_btn.text() == "No Dependencies"


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

    def test_panel_button_enabled_when_registered(self, qtbot):
        from wafer.builtins.plugin_manager.extensions_tab import _PluginRow
        from wafer.plugin.panel.handler import panel_registry

        class LoadedPanel(PluginBase):
            NAME = "__loaded_test_panel__"
            DISPLAY_NAME = "Loaded"
            PRIORITY = 1

        panel_registry.register(LoadedPanel)
        try:
            row = _PluginRow("panel", LoadedPanel, True)
            qtbot.addWidget(row)
            assert row.panel_btn.isEnabled()
        finally:
            panel_registry._plugins.pop("__loaded_test_panel__", None)


class TestExtensionCardMdFiles:
    @pytest.fixture()
    def dispatcher(self):
        from wafer.core.qt.dispatcher import Dispatcher
        from wafer.core.qt.thread import SimpleThreadPool

        pool = SimpleThreadPool("test")
        return Dispatcher(pool)

    def test_detects_multiple_md_files(self, qtbot, tmp_path, dispatcher):
        folder = tmp_path / "ext"
        folder.mkdir()
        (folder / "__init__.py").write_text("")
        (folder / "README.md").write_text("# Hello")
        (folder / "CHANGELOG.md").write_text("# Changes")

        from wafer.builtins.plugin_manager.extensions_tab import _ExtensionCard

        card = _ExtensionCard("ext", str(folder), dispatcher)
        qtbot.addWidget(card)
        assert len(card._md_entries) == 2
        names = [os.path.basename(e[2]) for e in card._md_entries]
        assert "CHANGELOG.md" in names
        assert "README.md" in names

    def test_ignores_hidden_and_underscore_md(self, qtbot, tmp_path, dispatcher):
        folder = tmp_path / "ext"
        folder.mkdir()
        (folder / "__init__.py").write_text("")
        (folder / "README.md").write_text("# ok")
        (folder / ".hidden.md").write_text("# hidden")
        (folder / "_private.md").write_text("# private")

        from wafer.builtins.plugin_manager.extensions_tab import _ExtensionCard

        card = _ExtensionCard("ext", str(folder), dispatcher)
        qtbot.addWidget(card)
        assert len(card._md_entries) == 1
        assert os.path.basename(card._md_entries[0][2]) == "README.md"

    def test_max_md_limit(self, qtbot, tmp_path, dispatcher):
        folder = tmp_path / "ext"
        folder.mkdir()
        (folder / "__init__.py").write_text("")
        for i in range(15):
            (folder / f"doc_{i:02d}.md").write_text(f"# Doc {i}")

        from wafer.builtins.plugin_manager.extensions_tab import _ExtensionCard, _MAX_MD_FILES

        card = _ExtensionCard("ext", str(folder), dispatcher)
        qtbot.addWidget(card)
        assert len(card._md_entries) == _MAX_MD_FILES

    def test_no_md_files_no_entries(self, qtbot, tmp_path, dispatcher):
        folder = tmp_path / "ext"
        folder.mkdir()
        (folder / "__init__.py").write_text("")

        from wafer.builtins.plugin_manager.extensions_tab import _ExtensionCard

        card = _ExtensionCard("ext", str(folder), dispatcher)
        qtbot.addWidget(card)
        assert len(card._md_entries) == 0

    def test_toggle_md_shows_and_hides(self, qtbot, tmp_path, dispatcher):
        folder = tmp_path / "ext"
        folder.mkdir()
        (folder / "README.md").write_text("# Hello")

        from wafer.builtins.plugin_manager.extensions_tab import _ExtensionCard

        card = _ExtensionCard("ext", str(folder), dispatcher)
        qtbot.addWidget(card)
        card.show()
        qtbot.waitExposed(card)
        toggle, browser, md_path, _ = card._md_entries[0]

        assert not browser.isVisible()
        card._toggle_md(md_path, toggle, browser)
        assert browser.isVisible()
        assert "\u25bc" in toggle.text()

        card._toggle_md(md_path, toggle, browser)
        assert not browser.isVisible()
        assert "\u25b6" in toggle.text()


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

    def test_drag_reorder_returns_new_order(self, qtbot):
        from wafer.builtins.plugin_manager.viewers_tab import OrderTab

        class P1(BasePlugin):
            NAME = "first"
            EXTENSIONS = ()
            PRIORITY = 10

        class P2(BasePlugin):
            NAME = "second"
            EXTENSIONS = ()
            PRIORITY = 5

        tab = OrderTab({"viewer": [P1, P2]}, {})
        qtbot.addWidget(tab)
        order = tab.get_orders()["viewer"]
        assert len(order) == 2

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
        from wafer.core.commands.command.menu import MenuGroup

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
    def test_has_plugin_changes_detects_enabled_diff(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: "/nonexistent",
        )
        from wafer.builtins.plugin_manager.widget import PluginManagerWidget

        dlg = PluginManagerWidget()
        qtbot.addWidget(dlg)
        dlg._initial_enabled = {"a", "b"}
        dlg._initial_orders = {"grid": ["a"]}
        assert not dlg._has_plugin_changes({"a", "b"}, {"grid": ["a"]})
        assert dlg._has_plugin_changes({"a", "b", "c"}, {"grid": ["a"]})
        assert dlg._has_plugin_changes({"a", "b"}, {"grid": ["b", "a"]})

    def test_send_purge_dispatches_to_node(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: "/nonexistent",
        )
        from wafer.builtins.plugin_manager.widget import PluginManagerWidget

        mock_node = MagicMock()
        from wafer.core.commands.binding.instance_registry import InstanceRegistry

        monkeypatch.setattr(InstanceRegistry.instance(), "resolve_node", lambda: mock_node)
        dlg = PluginManagerWidget()
        qtbot.addWidget(dlg)
        dlg._send_purge([("db1", "exif")], True)
        mock_node.send_reliable.assert_called_once_with(
            "purge.collector",
            {"collector": "exif", "re_collect": True},
            dst="indexer",
            db="db1",
        )

    def test_send_purge_no_node_warns(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: "/nonexistent",
        )
        from wafer.builtins.plugin_manager.widget import PluginManagerWidget
        from wafer.core.commands.binding.instance_registry import InstanceRegistry

        monkeypatch.setattr(InstanceRegistry.instance(), "resolve_node", lambda: None)
        dlg = PluginManagerWidget()
        qtbot.addWidget(dlg)
        dlg._send_purge([("db1", "exif")], False)


class TestPluginManagerCommands:
    def test_command_class_exists(self):
        from wafer.builtins.commands.app import PluginManagerCommands

        cmds = PluginManagerCommands.commands()
        assert len(cmds) >= 1
        paths = [c.path for c in cmds if hasattr(c, "path")]
        assert "setting.plugin_manager" in paths

    def test_all_commands_registered(self):
        from wafer.builtins.commands.app import PluginManagerCommands

        cmds = PluginManagerCommands.commands()
        paths = [c.path for c in cmds if hasattr(c, "path")]
        assert "setting.plugin_manager" in paths
        assert "setting.restart_tray" in paths
        assert "setting.restart_viewer" in paths
        assert "setting.restart_all" in paths

    def test_restart_tray_calls_process(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "wafer.builtins.commands.app.AppProcess",
            type(
                "",
                (),
                {
                    "terminate_cmd": staticmethod(lambda *a: calls.append(("terminate", a))),
                    "new_main": staticmethod(lambda *a: calls.append(("new_main", a))),
                },
            )(),
        )
        from wafer.builtins.commands.app import restart_tray

        restart_tray(MagicMock())
        assert ("terminate", ("--tray",)) in calls
        assert ("new_main", ("--tray",)) in calls

    def test_restart_viewer_delegates_to_close_by_restart(self):
        from wafer.builtins.commands.app import restart_viewer

        mock_w = MagicMock()
        ctx = MagicMock()
        ctx.get_instance.return_value = mock_w
        restart_viewer(ctx)
        mock_w.close_by_restart.assert_called_once()

    def test_restart_all_calls_both(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "wafer.builtins.commands.app.AppProcess",
            type(
                "",
                (),
                {
                    "terminate_cmd": staticmethod(lambda *a: calls.append(("terminate", a))),
                    "new_main": staticmethod(lambda *a: calls.append(("new_main", a))),
                },
            )(),
        )
        mock_store = MagicMock()
        mock_store.get_active_session_ids.return_value = ["sess1", "sess2"]
        monkeypatch.setattr("wafer.builtins.commands.app.SessionStore", type("", (), {"instance": staticmethod(lambda: mock_store)}))
        from wafer.builtins.commands.app import restart_all

        mock_node = MagicMock()
        mock_w = MagicMock()
        mock_w.session_id = "sess1"
        mock_w._node = mock_node
        ctx = MagicMock()
        ctx.get_instance.return_value = mock_w
        restart_all(ctx)
        assert ("terminate", ("--tray",)) in calls
        assert ("new_main", ("--tray",)) in calls
        mock_node.send.assert_called_once_with("session.restart", "sess2", dst="viewer")
        mock_w.close_by_restart.assert_called_once()
        mock_store.set_restore_session_ids.assert_called_once_with(["sess1", "sess2"])


class TestCollectorsTab:
    def test_empty_when_no_collectors(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.list_setting_db_names",
            lambda: [],
        )
        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=[], detacher_names=[])
        qtbot.addWidget(tab)
        assert tab._matrix == {}

    def test_matrix_populated(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test.db")
        from wafer.core.db.setting_db import SettingDB

        sdb = SettingDB(db_path)
        sdb.set_enabled_collectors(["exif"])

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.list_setting_db_names",
            lambda: ["test"],
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.setting_db_path",
            lambda name: db_path,
        )
        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif", "ai_tags"], detacher_names=[])
        qtbot.addWidget(tab)

        assert tab._matrix[("exif", "test")].isChecked()
        assert not tab._matrix[("ai_tags", "test")].isChecked()

    def test_all_toggle_sets_all_dbs(self, qtbot, tmp_path, monkeypatch):
        db1 = str(tmp_path / "db1.db")
        db2 = str(tmp_path / "db2.db")
        from wafer.core.db.setting_db import SettingDB

        SettingDB(db1).set_enabled_collectors([])
        SettingDB(db2).set_enabled_collectors([])

        db_map = {"one": db1, "two": db2}
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.list_setting_db_names",
            lambda: ["one", "two"],
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.setting_db_path",
            lambda name: db_map[name],
        )
        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif"], detacher_names=[])
        qtbot.addWidget(tab)

        assert not tab._matrix[("exif", "one")].isChecked()
        assert not tab._matrix[("exif", "two")].isChecked()

        tab._on_all_toggled("exif", True)

        assert tab._matrix[("exif", "one")].isChecked()
        assert tab._matrix[("exif", "two")].isChecked()

    def test_save_to_dbs(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / "save_test.db")
        from wafer.core.db.setting_db import SettingDB

        SettingDB(db_path).set_enabled_collectors([])

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.list_setting_db_names",
            lambda: ["mydb"],
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.setting_db_path",
            lambda name: db_path,
        )
        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif", "ai_tags"], detacher_names=[])
        qtbot.addWidget(tab)

        tab._matrix[("exif", "mydb")].setChecked(True)
        tab._matrix[("ai_tags", "mydb")].setChecked(False)
        tab.save_to_dbs()

        sdb = SettingDB(db_path)
        assert sdb.get_enabled_collectors() == ["exif"]

    def test_get_per_db_collectors(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / "per_db.db")
        from wafer.core.db.setting_db import SettingDB

        SettingDB(db_path).set_enabled_collectors(["exif"])

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.list_setting_db_names",
            lambda: ["testdb"],
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.setting_db_path",
            lambda name: db_path,
        )
        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif", "ai_tags"], detacher_names=[])
        qtbot.addWidget(tab)

        result = tab.get_per_db_collectors()
        assert result == {"testdb": ["exif"]}

    def test_get_newly_disabled(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / "nd.db")
        from wafer.core.db.setting_db import SettingDB

        SettingDB(db_path).set_enabled_collectors(["exif", "ai_tags"])

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.list_setting_db_names",
            lambda: ["mydb"],
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.setting_db_path",
            lambda name: db_path,
        )
        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif", "ai_tags"], detacher_names=[])
        qtbot.addWidget(tab)

        tab._matrix[("ai_tags", "mydb")].setChecked(False)
        disabled = tab.get_newly_disabled()
        assert ("mydb", "ai_tags") in disabled
        assert len(disabled) == 1

    def test_get_newly_disabled_no_changes(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / "nc.db")
        from wafer.core.db.setting_db import SettingDB

        SettingDB(db_path).set_enabled_collectors(["exif"])

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.list_setting_db_names",
            lambda: ["db1"],
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.setting_db_path",
            lambda name: db_path,
        )
        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif"], detacher_names=[])
        qtbot.addWidget(tab)

        disabled = tab.get_newly_disabled()
        assert disabled == []

    def test_refresh_updates_matrix(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / "refresh.db")
        from wafer.core.db.setting_db import SettingDB

        SettingDB(db_path).set_enabled_collectors(["exif"])

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.list_setting_db_names",
            lambda: ["mydb"],
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.setting_db_path",
            lambda name: db_path,
        )
        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif"], detacher_names=[])
        qtbot.addWidget(tab)

        assert ("exif", "mydb") in tab._matrix
        assert ("ai_tags", "mydb") not in tab._matrix

        tab.refresh(["exif", "ai_tags"], [])

        assert ("exif", "mydb") in tab._matrix
        assert ("ai_tags", "mydb") in tab._matrix
        assert tab._matrix[("exif", "mydb")].isChecked()

    def test_has_changes_false_when_unchanged(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / "hc.db")
        from wafer.core.db.setting_db import SettingDB

        SettingDB(db_path).set_enabled_collectors(["exif"])

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.list_setting_db_names",
            lambda: ["mydb"],
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.setting_db_path",
            lambda name: db_path,
        )
        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif"], detacher_names=[])
        qtbot.addWidget(tab)
        assert not tab.has_changes()

    def test_has_changes_true_when_toggled(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / "hc2.db")
        from wafer.core.db.setting_db import SettingDB

        SettingDB(db_path).set_enabled_collectors(["exif"])

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.list_setting_db_names",
            lambda: ["mydb"],
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.collectors_tab.setting_db_path",
            lambda name: db_path,
        )
        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif"], detacher_names=[])
        qtbot.addWidget(tab)
        tab._matrix[("exif", "mydb")].setChecked(False)
        assert tab.has_changes()


class TestDataTab:
    def test_empty_state(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            "wafer.builtins.database_manager.data_tab.list_setting_db_names",
            lambda: [],
        )
        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.database_manager.data_tab import DataTab

        tab = DataTab(dispatcher)
        qtbot.addWidget(tab)
        qtbot.waitUntil(lambda: tab._collector_table.table.rowCount() == 0, timeout=3000)
        assert tab._collector_table.table.rowCount() == 0

    def test_loads_data_from_dbs(self, qtbot, tmp_path, monkeypatch):
        from wafer.core.db.setting_db import SettingDB
        from wafer.core.db.file_db import FileDB

        sdb_path = str(tmp_path / "settings.db")
        SettingDB(sdb_path).set_enabled_collectors(["exif"])

        fdb_path = str(tmp_path / "data.db")
        fdb = FileDB(fdb_path)
        fdb.start()
        fdb.initialize_database()
        fdb.upsert_basic_sources(
            [("src0", "h0", 100, 1.0)],
            [("c:/a.jpg", "src0", 1.5)],
        )
        fdb.upsert_collection_results(
            [],
            [("c:/a.jpg", "exif.width", "1920", 1920)],
            [],
            [],
        )
        fdb.close()

        monkeypatch.setattr(
            "wafer.builtins.database_manager.data_tab.list_setting_db_names",
            lambda: ["testdb"],
        )
        monkeypatch.setattr(
            "wafer.builtins.database_manager.data_tab.setting_db_path",
            lambda name: sdb_path,
        )
        monkeypatch.setattr(
            "wafer.builtins.database_manager.data_tab.data_db_path",
            lambda name: fdb_path,
        )
        monkeypatch.setattr(
            "wafer.builtins.database_manager.data_tab._resolve_plugin_info",
            lambda prefix: ("Collector", prefix) if prefix == "exif" else ("", ""),
        )

        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.database_manager.data_tab import DataTab

        tab = DataTab(dispatcher)
        qtbot.addWidget(tab)
        qtbot.waitUntil(lambda: tab._collector_table.table.rowCount() > 0, timeout=5000)
        assert tab._collector_table.table.rowCount() >= 1
        assert tab._collector_table.table.item(0, 1).text() == "exif"
        assert tab._collector_table.table.item(0, 2).text() == "1"
        assert tab._collector_table.table.item(0, 3).text() == "0"
        assert tab._collector_table.table.item(0, 4).text() == "Active"


class TestCloseEventCancels:
    def test_close_cancels_pending_installs(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "pending_ext").mkdir(parents=True)
        (ext_dir / "pending_ext" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: False,
        )
        from wafer.core.qt.dispatcher import Dispatcher, CancelSlot

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab(set(), dispatcher)

        slot = CancelSlot()
        token = slot.renew()
        tab._install_cancels["pending_ext"] = slot

        assert not token.is_cancelled()
        tab.cancel_pending()
        assert token.is_cancelled()
        assert tab._install_cancels == {}


class TestPostInstallHook:
    def test_post_install_called_after_install(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "vid_ext").mkdir(parents=True)
        (ext_dir / "vid_ext" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: True,
        )

        class HookPlugin(BasePlugin):
            NAME = "hook_p"
            EXTENSIONS = (".h",)
            PRIORITY = 1

            @classmethod
            def post_install(cls, plugin_dir, on_progress=None):
                pass

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.install_extension",
            lambda d, e, on_progress=None, is_cancelled=None: (True, True, [("viewer", HookPlugin)]),
        )
        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab(set(), dispatcher)
        qtbot.addWidget(tab)

        card = tab._cards["vid_ext"]
        tab._install_extension(card)
        qtbot.waitUntil(lambda: len(card._rows) > 0, timeout=5000)

    def test_post_install_not_called_when_absent(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / "extensions"
        (ext_dir / "plain_ext").mkdir(parents=True)
        (ext_dir / "plain_ext" / "__init__.py").write_text("")
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.get_plugin_dir",
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.needs_setup",
            lambda folder: True,
        )

        class PlainPlugin(BasePlugin):
            NAME = "plain_p"
            EXTENSIONS = (".p",)
            PRIORITY = 1

        monkeypatch.setattr(
            "wafer.builtins.plugin_manager.extensions_tab.install_extension",
            lambda d, e, on_progress=None, is_cancelled=None: (True, True, [("grid", PlainPlugin)]),
        )
        from wafer.core.qt.dispatcher import Dispatcher

        dispatcher = Dispatcher()
        from wafer.builtins.plugin_manager.extensions_tab import ExtensionsTab

        tab = ExtensionsTab(set(), dispatcher)
        qtbot.addWidget(tab)

        card = tab._cards["plain_ext"]
        tab._install_extension(card)
        qtbot.waitUntil(
            lambda: len(card._rows) > 0,
            timeout=5000,
        )

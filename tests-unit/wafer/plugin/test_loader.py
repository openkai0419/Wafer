import os
import sys
import pytest
from pathlib import Path

from wafer.plugin.registry import BasePlugin, PluginRegistry, FilePluginRegistry
from wafer.plugin.loader import PluginLoader
from wafer.plugin.installer import _PACKAGES_DIR, _STAMPS_DIR, needs_post_install, needs_setup


@pytest.fixture
def plugin_env(tmp_path):
    plugin_dir = tmp_path / "plugins"
    stub_dir = plugin_dir / "stub_plugin"
    stub_dir.mkdir(parents=True)
    (stub_dir / "__init__.py").write_text("")
    (stub_dir / "grid.py").write_text(
        "from wafer.plugin.grid.base import ImageGridPlugin\n"
        "class StubGridPlugin(ImageGridPlugin):\n"
        '    NAME = "stub_test"\n'
        '    EXTENSIONS = (".stub",)\n'
        "    PRIORITY = 10\n"
        "    DEFAULT_ENABLED = True\n"
        "    _post_installed = False\n"
        "    _configured = False\n"
        "    def load(self, path, size=None): return None\n"
        "    @classmethod\n"
        "    def post_install(cls, plugin_dir, on_progress=None): cls._post_installed = True\n"
        "    @classmethod\n"
        "    def configure(cls): cls._configured = True\n"
    )
    yield str(plugin_dir), str(stub_dir)
    for key in list(sys.modules):
        if key.startswith("_plugins_stub_plugin"):
            del sys.modules[key]


def _make_registries():
    return {
        "viewer": FilePluginRegistry(),
        "grid": FilePluginRegistry(),
        "collector": FilePluginRegistry(),
    }


class TestConfigureHook:
    def test_configure_called_after_load_all(self, plugin_env):
        plugin_dir, _ = plugin_env

        registries = _make_registries()
        loader = PluginLoader(plugin_dir, registries)
        loaded = loader.load_all()

        assert "stub_plugin" in loaded
        plugin_cls = registries["grid"].get("stub_test")
        assert plugin_cls is not None
        assert plugin_cls._configured is True

    def test_configure_failure_does_not_block_loading(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        broken_dir = plugin_dir / "broken_plugin"
        broken_dir.mkdir(parents=True)
        (broken_dir / "__init__.py").write_text("")
        (broken_dir / "grid.py").write_text(
            "from wafer.plugin.grid.base import ImageGridPlugin\n"
            "class BrokenConfigure(ImageGridPlugin):\n"
            '    NAME = "broken"\n'
            '    EXTENSIONS = (".brk",)\n'
            "    PRIORITY = 10\n"
            "    DEFAULT_ENABLED = True\n"
            "    def load(self, path, size=None): return None\n"
            "    @classmethod\n"
            '    def configure(cls): raise RuntimeError("boom")\n'
        )

        registries = _make_registries()
        loader = PluginLoader(str(plugin_dir), registries)
        loaded = loader.load_all()
        assert "broken_plugin" in loaded

        for key in list(sys.modules):
            if key.startswith("_plugins_broken_plugin"):
                del sys.modules[key]


class TestBasePluginHooksDefault:
    def test_post_install_default_is_noop(self):
        BasePlugin.post_install("/tmp")

    def test_configure_default_is_noop(self):
        BasePlugin.configure()

    def test_can_handle_default_returns_true(self):
        assert BasePlugin.can_handle("anything.xyz")


class TestDeferredCommandRegistration:
    def test_commands_deferred_not_registered_immediately(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        cmd_dir = plugin_dir / "cmd_plugin"
        cmd_dir.mkdir(parents=True)
        (cmd_dir / "__init__.py").write_text("")
        (cmd_dir / "commands.py").write_text(
            "from wafer.core.commands.command.menu import MenuGroup\n"
            "from wafer.core.commands.command.core import CommandMeta\n"
            "class TestCmdGroup(MenuGroup):\n"
            '    NAME = "TestCmd"\n'
            "    DEFAULT_ENABLED = True\n"
            "    @classmethod\n"
            "    def commands(cls):\n"
            '        return [CommandMeta(path="tcmd.noop", display="Noop", func=lambda ctx: None)]\n'
        )
        from wafer.plugin.registry import CommandGroupRegistry

        cmd_registry = CommandGroupRegistry()
        registries = _make_registries()
        registries["command"] = cmd_registry
        loader = PluginLoader(str(plugin_dir), registries)
        loader.load_all()
        assert len(cmd_registry.list_all()) > 0
        from wafer.core.commands.command.core import CommandRegistry

        reg = CommandRegistry.instance()
        assert not reg.has_command("tcmd.noop")
        cmd_registry.activate("viewer")
        assert reg.has_command("tcmd.noop")
        for key in list(sys.modules):
            if key.startswith("_plugins_cmd_plugin"):
                del sys.modules[key]


class TestSubmoduleRelativeImport:
    def test_submodule_not_treated_as_package(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        rel_dir = plugin_dir / "rel_plugin"
        rel_dir.mkdir(parents=True)
        (rel_dir / "__init__.py").write_text("")
        (rel_dir / "state.py").write_text("value = 42\n")
        (rel_dir / "reader.py").write_text("from .state import value\ndef get(): return value\n")
        registries = _make_registries()
        loader = PluginLoader(str(plugin_dir), registries)
        loader.load_all()
        mod = sys.modules.get("_plugins_rel_plugin.reader")
        assert mod is not None
        assert mod.get() == 42
        state_mod = sys.modules.get("_plugins_rel_plugin.state")
        assert state_mod is not None
        assert state_mod.value == 42
        assert not hasattr(mod, "__path__")
        for key in list(sys.modules):
            if key.startswith("_plugins_rel_plugin"):
                del sys.modules[key]


class TestRunSubprocess:
    def test_stderr_drained_without_deadlock(self, tmp_path):
        from wafer.plugin.installer import _run_subprocess

        script = tmp_path / "noisy.py"
        script.write_text('import sys\nsys.stderr.write("x" * 100000 + "\\n")\nsys.exit(0)\n')
        _run_subprocess([sys.executable, str(script)])

    def test_stderr_captured_on_failure(self, tmp_path):
        from wafer.plugin.installer import _run_subprocess

        script = tmp_path / "fail.py"
        script.write_text('import sys\nsys.stderr.write("custom error msg\\n")\nsys.exit(1)\n')
        with pytest.raises(RuntimeError, match="custom error msg"):
            _run_subprocess([sys.executable, str(script)])


class TestNeedsSetupSkip:
    def test_needs_setup_returns_zero_when_missing_stamp(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        ext_dir = plugin_dir / "uninstalled_ext"
        ext_dir.mkdir(parents=True)
        (ext_dir / "__init__.py").write_text("")
        (ext_dir / "requirements.txt").write_text("some-package\n")
        (ext_dir / "grid.py").write_text(
            "from wafer.plugin.grid.base import ImageGridPlugin\n"
            "class NeedsGrid(ImageGridPlugin):\n"
            '    NAME = "needs_ext"\n'
            '    EXTENSIONS = (".nds",)\n'
            "    PRIORITY = 1\n"
            "    def load(self, path, size=None): return None\n"
        )

        registries = _make_registries()
        loader = PluginLoader(str(plugin_dir), registries)
        loaded = loader.load_all()
        assert "uninstalled_ext" not in loaded
        assert registries["grid"].get("needs_ext") is None

        for key in list(sys.modules):
            if key.startswith("_plugins_uninstalled_ext"):
                del sys.modules[key]


class TestEnabledFilter:
    def test_enabled_none_loads_all(self, plugin_env):
        plugin_dir, _ = plugin_env
        registries = _make_registries()
        loader = PluginLoader(plugin_dir, registries, enabled=None)
        loaded = loader.load_all()
        assert "stub_plugin" in loaded
        assert registries["grid"].get("stub_test") is not None

        for key in list(sys.modules):
            if key.startswith("_plugins_stub_plugin"):
                del sys.modules[key]

    def test_enabled_includes_matching_name(self, plugin_env):
        plugin_dir, _ = plugin_env
        registries = _make_registries()
        loader = PluginLoader(plugin_dir, registries, enabled={"grid:StubGridPlugin"})
        loaded = loader.load_all()
        assert "stub_plugin" in loaded
        assert registries["grid"].get("stub_test") is not None

        for key in list(sys.modules):
            if key.startswith("_plugins_stub_plugin"):
                del sys.modules[key]

    def test_enabled_excludes_non_matching_name(self, plugin_env):
        plugin_dir, _ = plugin_env
        registries = _make_registries()
        loader = PluginLoader(plugin_dir, registries, enabled={"grid:other_plugin"})
        loaded = loader.load_all()
        assert "stub_plugin" not in loaded
        assert registries["grid"].get("stub_test") is None

        for key in list(sys.modules):
            if key.startswith("_plugins_stub_plugin"):
                del sys.modules[key]


class TestDiscoverExtension:
    def test_discover_returns_registry_key_and_class(self, plugin_env):
        _, stub_dir = plugin_env
        result = PluginLoader.discover_extension(stub_dir)
        assert len(result) >= 1
        keys = [r[0] for r in result]
        assert "grid" in keys
        names = [r[1].NAME for r in result]
        assert "stub_test" in names

    def test_discover_does_not_register(self, plugin_env):
        _, stub_dir = plugin_env
        registries = _make_registries()
        PluginLoader.discover_extension(stub_dir)
        assert registries["grid"].get("stub_test") is None


class TestNeedsPostInstall:
    def test_returns_true_when_no_stamp(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("some-pkg\n")
        assert needs_post_install(str(plugin)) is True

    def test_returns_false_when_stamp_exists(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("some-pkg\n")
        stamps = ext_dir / _PACKAGES_DIR / _STAMPS_DIR
        stamps.mkdir(parents=True)
        (stamps / "plugin.post_installed").touch()
        assert needs_post_install(str(plugin)) is False

    def test_returns_false_when_no_requirements(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        assert needs_post_install(str(plugin)) is False


class TestApplyPriorityOrder:
    def test_order_overrides_priority(self):
        class PluginA(BasePlugin):
            NAME = "a"
            PRIORITY = 10

        class PluginB(BasePlugin):
            NAME = "b"
            PRIORITY = 20

        registry = PluginRegistry()
        registry.register(PluginA)
        registry.register(PluginB)
        assert registry.list_all()[0].NAME == "b"
        registry.set_order(["a", "b"])
        assert registry.list_all()[0].NAME == "a"

    def test_empty_order_is_noop(self):
        class PluginC(BasePlugin):
            NAME = "c"
            PRIORITY = 50

        registry = PluginRegistry()
        registry.register(PluginC)
        registry.set_order([])
        assert registry.list_all()[0].NAME == "c"
        assert PluginC.PRIORITY == 50

    def test_unknown_name_in_order_ignored(self):
        class PluginD(BasePlugin):
            NAME = "d"
            PRIORITY = 5

        registry = PluginRegistry()
        registry.register(PluginD)
        registry.set_order(["nonexistent", "d"])
        assert registry.list_all()[0].NAME == "d"

    def test_unlisted_plugins_sorted_after_listed(self):
        class PluginE(BasePlugin):
            NAME = "e"
            PRIORITY = 10

        class PluginF(BasePlugin):
            NAME = "f"
            PRIORITY = 500

        class PluginG(BasePlugin):
            NAME = "g"
            PRIORITY = 1000

        registry = PluginRegistry()
        registry.register(PluginE)
        registry.register(PluginF)
        registry.register(PluginG)
        registry.set_order(["e"])
        names = [p.NAME for p in registry.list_all()]
        assert names[0] == "e"
        assert names[1] == "g"
        assert names[2] == "f"


class TestPackagesDir:
    def test_load_all_adds_packages_dir_to_sys_path(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        packages = plugin_dir / _PACKAGES_DIR
        packages.mkdir()
        (packages / "dummy.txt").write_text("")

        registries = _make_registries()
        loader = PluginLoader(str(plugin_dir), registries)
        loader.load_all()
        assert str(packages) in sys.path
        sys.path.remove(str(packages))

    def test_load_all_skips_packages_dir_when_missing(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()

        registries = _make_registries()
        loader = PluginLoader(str(plugin_dir), registries)
        before = list(sys.path)
        loader.load_all()
        packages_path = str(plugin_dir / _PACKAGES_DIR)
        assert packages_path not in sys.path
        sys.path[:] = before

    def test_discover_extension_adds_and_removes_packages_dir(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        ext_dir = plugin_dir / "test_ext"
        ext_dir.mkdir(parents=True)
        (ext_dir / "__init__.py").write_text("")
        packages = plugin_dir / _PACKAGES_DIR
        packages.mkdir()

        packages_str = str(packages)
        assert packages_str not in sys.path
        PluginLoader.discover_extension(str(ext_dir))
        assert packages_str not in sys.path

        for key in list(sys.modules):
            if key.startswith("_plugins_test_ext"):
                del sys.modules[key]

    def test_priority_not_mutated(self):
        class PluginH(BasePlugin):
            NAME = "h"
            PRIORITY = 42

        class PluginI(BasePlugin):
            NAME = "i"
            PRIORITY = 99

        registry = PluginRegistry()
        registry.register(PluginH)
        registry.register(PluginI)
        registry.set_order(["h", "i"])
        assert PluginH.PRIORITY == 42
        assert PluginI.PRIORITY == 99


class TestDefaultEnabled:
    def test_default_enabled_false_skipped_when_none(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        stub_dir = plugin_dir / "disabled_ext"
        stub_dir.mkdir(parents=True)
        (stub_dir / "__init__.py").write_text("")
        (stub_dir / "grid.py").write_text(
            "from wafer.plugin.grid.base import ImageGridPlugin\n"
            "class DisabledGridPlugin(ImageGridPlugin):\n"
            '    NAME = "disabled_test"\n'
            '    EXTENSIONS = (".dis",)\n'
            "    PRIORITY = 10\n"
            "    DEFAULT_ENABLED = False\n"
            "    def load(self, path, size=None): return None\n"
        )
        registries = _make_registries()
        loader = PluginLoader(str(plugin_dir), registries, enabled=None)
        loader.load_all()
        assert registries["grid"].get("disabled_test") is None

        for key in list(sys.modules):
            if key.startswith("_plugins_disabled_ext"):
                del sys.modules[key]

    def test_default_enabled_true_loaded_when_none(self, plugin_env):
        plugin_dir, _ = plugin_env
        registries = _make_registries()
        loader = PluginLoader(plugin_dir, registries, enabled=None)
        loader.load_all()
        assert registries["grid"].get("stub_test") is not None

        for key in list(sys.modules):
            if key.startswith("_plugins_stub_plugin"):
                del sys.modules[key]

    def test_default_enabled_false_loaded_when_explicit_set(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        stub_dir = plugin_dir / "disabled_ext2"
        stub_dir.mkdir(parents=True)
        (stub_dir / "__init__.py").write_text("")
        (stub_dir / "grid.py").write_text(
            "from wafer.plugin.grid.base import ImageGridPlugin\n"
            "class DisabledGridPlugin2(ImageGridPlugin):\n"
            '    NAME = "disabled_test2"\n'
            '    EXTENSIONS = (".dis2",)\n'
            "    PRIORITY = 10\n"
            "    DEFAULT_ENABLED = False\n"
            "    def load(self, path, size=None): return None\n"
        )
        registries = _make_registries()
        loader = PluginLoader(str(plugin_dir), registries, enabled={"grid:DisabledGridPlugin2"})
        loader.load_all()
        assert registries["grid"].get("disabled_test2") is not None

        for key in list(sys.modules):
            if key.startswith("_plugins_disabled_ext2"):
                del sys.modules[key]

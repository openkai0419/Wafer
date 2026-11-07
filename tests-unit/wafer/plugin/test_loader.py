import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from wafer.builtins import registration
from wafer.plugin import loader as loader_module, plugin_index
from wafer.plugin.collector.handler import collector_resolver
from wafer.plugin.imageloader.handler import image_loader_resolver
from wafer.plugin.parser.handler import parser_resolver
from wafer.plugin.plugin_index import ExtensionRecord, PluginEntry
from wafer.plugin.registry import BasePlugin, PluginRegistry, FilePluginRegistry
from wafer.plugin.loader import PluginLoader
from wafer.plugin.installer import _PACKAGES_DIR
from wafer.plugin.settings import PluginSettings

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def plugin_env(tmp_path):
    plugin_dir = tmp_path / "plugins"
    stub_dir = plugin_dir / "stub_plugin"
    stub_dir.mkdir(parents=True)
    (stub_dir / "__init__.py").write_text("")
    (stub_dir / "grid.py").write_text(
        "from wafer.plugin.grid.base import BaseGridPlugin\n"
        "class StubGridPlugin(BaseGridPlugin):\n"
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
        "grid_overlay": PluginRegistry(),
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
            "from wafer.plugin.grid.base import BaseGridPlugin\n"
            "class BrokenConfigure(BaseGridPlugin):\n"
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


class TestGridOverlayPluginLoading:
    def test_overlay_plugin_discovered_and_registered(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        overlay_dir = plugin_dir / "overlay_plugin"
        overlay_dir.mkdir(parents=True)
        (overlay_dir / "__init__.py").write_text("")
        (overlay_dir / "overlay.py").write_text(
            'from wafer.plugin import BaseBadgeOverlayPlugin\nclass StubOverlayPlugin(BaseBadgeOverlayPlugin):\n    NAME = "stub_overlay"\n    PRIORITY = 10\n    DEFAULT_ENABLED = True\n'
        )

        registries = _make_registries()
        loader = PluginLoader(str(plugin_dir), registries)
        loaded = loader.load_all()

        assert "overlay_plugin" in loaded
        assert registries["grid_overlay"].get("stub_overlay") is not None

        for key in list(sys.modules):
            if key.startswith("_plugins_overlay_plugin"):
                del sys.modules[key]


class TestDeferredCommandRegistration:
    def test_commands_deferred_not_registered_immediately(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        cmd_dir = plugin_dir / "cmd_plugin"
        cmd_dir.mkdir(parents=True)
        (cmd_dir / "__init__.py").write_text("")
        (cmd_dir / "commands.py").write_text(
            "from wafer.qt.commands.command.menu import MenuGroup\n"
            "from wafer.qt.commands.command.core import CommandMeta\n"
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
        from wafer.qt.commands.command.core import CommandRegistry

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


class TestNeedsSetupSkip:
    def test_needs_setup_returns_zero_when_missing_stamp(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        ext_dir = plugin_dir / "uninstalled_ext"
        ext_dir.mkdir(parents=True)
        (ext_dir / "__init__.py").write_text("")
        (ext_dir / "requirements.txt").write_text("some-package\n")
        (ext_dir / "grid.py").write_text(
            "from wafer.plugin.grid.base import BaseGridPlugin\n"
            "class NeedsGrid(BaseGridPlugin):\n"
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
    def test_enabled_override_keeps_matching_name(self, plugin_env):
        plugin_dir, _ = plugin_env
        registries = _make_registries()
        loader = PluginLoader(plugin_dir, registries, enabled={"grid:StubGridPlugin": True})
        loaded = loader.load_all()
        assert "stub_plugin" in loaded
        assert registries["grid"].get("stub_test") is not None

        for key in list(sys.modules):
            if key.startswith("_plugins_stub_plugin"):
                del sys.modules[key]

    def test_enabled_override_false_disables_default_enabled(self, plugin_env):
        plugin_dir, _ = plugin_env
        registries = _make_registries()
        loader = PluginLoader(plugin_dir, registries, enabled={"grid:StubGridPlugin": False})
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


class TestSetupPackagesDllDirectories:
    def test_registers_libs_dirs_on_windows(self, tmp_path, monkeypatch):
        from wafer.plugin.loader import _setup_packages_dll_directories

        packages = tmp_path / ".packages"
        packages.mkdir()
        (packages / "numpy.libs").mkdir()
        (packages / "torch").mkdir()
        (packages / "regular_pkg").mkdir()

        monkeypatch.setattr(sys, "platform", "win32")
        added = []
        monkeypatch.setattr(os, "add_dll_directory", lambda p: added.append(p))

        _setup_packages_dll_directories(str(packages))

        assert len(added) == 1
        assert added[0] == str(packages / "numpy.libs")

    def test_noop_when_no_dir(self, tmp_path, monkeypatch):
        from wafer.plugin.loader import _setup_packages_dll_directories

        monkeypatch.setattr(sys, "platform", "win32")
        _setup_packages_dll_directories(str(tmp_path / "nonexistent"))


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
            "from wafer.plugin.grid.base import BaseGridPlugin\n"
            "class DisabledGridPlugin(BaseGridPlugin):\n"
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
        loaded = loader.load_all()
        assert "stub_plugin" in loaded
        assert registries["grid"].get("stub_test") is not None

        for key in list(sys.modules):
            if key.startswith("_plugins_stub_plugin"):
                del sys.modules[key]

    def test_default_enabled_false_loaded_when_overridden_true(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        stub_dir = plugin_dir / "disabled_ext2"
        stub_dir.mkdir(parents=True)
        (stub_dir / "__init__.py").write_text("")
        (stub_dir / "grid.py").write_text(
            "from wafer.plugin.grid.base import BaseGridPlugin\n"
            "class DisabledGridPlugin2(BaseGridPlugin):\n"
            '    NAME = "disabled_test2"\n'
            '    EXTENSIONS = (".dis2",)\n'
            "    PRIORITY = 10\n"
            "    DEFAULT_ENABLED = False\n"
            "    def load(self, path, size=None): return None\n"
        )
        registries = _make_registries()
        loader = PluginLoader(str(plugin_dir), registries, enabled={"grid:DisabledGridPlugin2": True})
        loader.load_all()
        assert registries["grid"].get("disabled_test2") is not None

        for key in list(sys.modules):
            if key.startswith("_plugins_disabled_ext2"):
                del sys.modules[key]


PLUGIN_BASES = {
    "collector": ("wafer.plugin.collector.base", "BaseCollectorPlugin"),
    "parser": ("wafer.plugin.parser.base", "BaseParserPlugin"),
    "filter": ("wafer.plugin.query.base", "BaseFilterPlugin"),
    "panel": ("wafer.plugin.panel.base", "BasePanelPlugin"),
    "imageloader": ("wafer.plugin.imageloader.base", "BaseImageLoader"),
}


def _plugin(kind, cls_name, name, priority=10, enabled=True):
    module, base = PLUGIN_BASES[kind]
    return (
        f"from {module} import {base}\n"
        f"class {cls_name}({base}):\n"
        f'    NAME = "{name}"\n'
        f"    PRIORITY = {priority}\n"
        f"    DEFAULT_ENABLED = {enabled}\n"
    )


def _write_extension(plugin_dir, extension, **modules):
    folder = plugin_dir / extension
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text("")
    for module, source in modules.items():
        (folder / f"{module}.py").write_text(source)
    return folder


def _purge_index_extensions():
    for key in list(sys.modules):
        if key.startswith("_plugins_idx_"):
            del sys.modules[key]
    importlib.invalidate_caches()


def _registries():
    return {
        "collector": FilePluginRegistry(),
        "parser": PluginRegistry(),
        "imageloader": FilePluginRegistry(),
        "filter": PluginRegistry(),
        "panel": PluginRegistry(),
    }


def _index_for(plugin_dir):
    loader = PluginLoader(str(plugin_dir), _registries(), record_index=True)
    loader.load_all()
    _purge_index_extensions()
    return loader.records


def _select_all(kind, name):
    return True


def _select_collectors(kind, name):
    return kind == "collector"


def _capture_warnings(monkeypatch):
    warnings = []
    monkeypatch.setattr(loader_module.AppLogger, "warning", lambda text, *, exc=None: warnings.append(text))
    return warnings


def _vanish(folder):
    raise FileNotFoundError("file vanished")


@pytest.fixture
def plugin_dir(tmp_path):
    folder = tmp_path / "plugins"
    folder.mkdir()
    yield folder
    _purge_index_extensions()


@pytest.fixture
def scoped_env(plugin_dir, monkeypatch):
    monkeypatch.setattr(loader_module, "get_plugin_dir", lambda: str(plugin_dir))
    monkeypatch.setattr(collector_resolver, "registry", FilePluginRegistry())
    monkeypatch.setattr(parser_resolver, "registry", PluginRegistry())
    monkeypatch.setattr(image_loader_resolver, "registry", FilePluginRegistry())
    monkeypatch.setattr(loader_module, "_command_registry_ref", loader_module._command_registry_ref)
    return plugin_dir


def _run_probe(code, tmp_path):
    env = {**os.environ, "WIN_PD_OVERRIDE_LOCAL_APPDATA": str(tmp_path / "appdata")}
    return subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=25)


def test_loader_module_does_not_import_qt(tmp_path):
    result = _run_probe("import sys;import wafer.plugin.loader;sys.exit(1 if 'PySide6' in sys.modules else 0)", tmp_path)
    assert result.returncode == 0, result.stderr


class TestRecordingTheIndex:
    def test_load_all_records_every_extension(self, plugin_dir):
        folder_a = _write_extension(plugin_dir, "idx_a", collector=_plugin("collector", "ACollector", "a"))
        folder_b = _write_extension(plugin_dir, "idx_b", off=_plugin("parser", "BParser", "b", enabled=False))

        loader = PluginLoader(str(plugin_dir), _registries(), record_index=True)
        loader.load_all()

        assert loader.records == {
            "idx_a": ExtensionRecord(
                plugin_index.extension_fingerprint(str(folder_a)),
                (PluginEntry("collector", "collector", "ACollector", "a"),),
            ),
            "idx_b": ExtensionRecord(
                plugin_index.extension_fingerprint(str(folder_b)),
                (PluginEntry("parser", "off", "BParser", "b"),),
            ),
        }

    def test_load_all_records_nothing_by_default(self, plugin_dir):
        _write_extension(plugin_dir, "idx_a", collector=_plugin("collector", "ACollector", "a"))

        loader = PluginLoader(str(plugin_dir), _registries())
        loader.load_all()

        assert loader.records == {}

    def test_entries_use_the_defining_module(self, plugin_dir):
        _write_extension(
            plugin_dir,
            "idx_a",
            a_user="from .z_owner import OwnedCollector\nfrom ._common import SharedParser\n",
            z_owner=_plugin("collector", "OwnedCollector", "owned"),
            _common=_plugin("parser", "SharedParser", "shared"),
        )

        loader = PluginLoader(str(plugin_dir), _registries(), record_index=True)
        loader.load_all()

        assert loader.records["idx_a"].plugins == (
            PluginEntry("collector", "z_owner", "OwnedCollector", "owned"),
            PluginEntry("parser", "_common", "SharedParser", "shared"),
        )

    def test_class_from_outside_the_extension_is_not_recorded(self, plugin_dir):
        _write_extension(
            plugin_dir,
            "idx_a",
            borrowed="from wafer.builtins.imageloader import SystemImageLoader\n",
            collector=_plugin("collector", "ACollector", "a"),
        )

        loader = PluginLoader(str(plugin_dir), _registries(), record_index=True)
        loader.load_all()

        assert loader.records == {}

    def test_failed_import_is_not_recorded(self, plugin_dir):
        _write_extension(
            plugin_dir,
            "idx_a",
            broken="raise ImportError('missing dependency')\n",
            collector=_plugin("collector", "ACollector", "a"),
        )
        _write_extension(plugin_dir, "idx_b", collector=_plugin("collector", "BCollector", "b"))

        registries = _registries()
        loader = PluginLoader(str(plugin_dir), registries, record_index=True)
        loader.load_all()

        assert list(loader.records) == ["idx_b"]
        assert registries["collector"].get("a") is not None

    def test_failed_import_from_an_earlier_scan_is_not_recorded(self, plugin_dir):
        folder = _write_extension(
            plugin_dir,
            "idx_a",
            broken=_plugin("collector", "HalfCollector", "half") + "raise ImportError('missing dependency')\n",
        )
        PluginLoader.discover_extension(str(folder))

        loader = PluginLoader(str(plugin_dir), _registries(), record_index=True)
        loader.load_all()

        assert loader.records == {}

    def test_needs_setup_extension_is_not_recorded(self, plugin_dir, monkeypatch):
        _write_extension(plugin_dir, "idx_a", collector=_plugin("collector", "ACollector", "a"))
        _write_extension(plugin_dir, "idx_b", collector=_plugin("collector", "BCollector", "b"))
        monkeypatch.setattr(loader_module, "needs_setup", lambda folder: folder.endswith("idx_a"))

        loader = PluginLoader(str(plugin_dir), _registries(), record_index=True)
        loader.load_all()

        assert list(loader.records) == ["idx_b"]

    def test_fingerprint_failure_keeps_loading_and_skips_the_record(self, plugin_dir, monkeypatch):
        _write_extension(plugin_dir, "idx_a", collector=_plugin("collector", "ACollector", "a"))
        warnings = _capture_warnings(monkeypatch)
        monkeypatch.setattr(plugin_index, "extension_fingerprint", _vanish)

        registries = _registries()
        loader = PluginLoader(str(plugin_dir), registries, record_index=True)
        loaded = loader.load_all()

        assert loaded == ["idx_a"]
        assert registries["collector"].get("a") is not None
        assert loader.records == {}
        assert any("idx_a" in text for text in warnings)


class TestPluginEntries:
    def test_keeps_first_seen_order_and_removes_duplicates(self):
        class Second:
            NAME = "second"
            __module__ = "_plugins_idx_a.b"

        class First:
            NAME = "first"
            __module__ = "_plugins_idx_a.a"

        found = [("parser", Second), ("collector", First), ("parser", Second)]

        assert loader_module.plugin_entries("idx_a", found) == (
            PluginEntry("parser", "b", "Second", "second"),
            PluginEntry("collector", "a", "First", "first"),
        )

    @pytest.mark.parametrize("module", ["wafer.builtins.imageloader", "_plugins_idx_b.a", "_plugins_idx_a"])
    def test_class_defined_outside_the_extension_modules_gives_none(self, module):
        class Outside:
            NAME = "outside"

        Outside.__module__ = module

        assert loader_module.plugin_entries("idx_a", [("collector", Outside)]) is None


class TestSelectedLoad:
    def test_cached_extension_imports_only_selected_modules(self, plugin_dir):
        _write_extension(
            plugin_dir,
            "idx_a",
            collector=_plugin("collector", "ACollector", "a"),
            panel=_plugin("panel", "APanel", "a_panel"),
        )
        index = _index_for(plugin_dir)

        registries = _registries()
        loaded = PluginLoader(str(plugin_dir), registries).load_selected(_select_collectors, index)

        assert loaded == ["idx_a"]
        assert registries["collector"].get("a") is not None
        assert "_plugins_idx_a.collector" in sys.modules
        assert "_plugins_idx_a.panel" not in sys.modules

    def test_cached_load_does_not_build_the_registry_map(self, plugin_dir, monkeypatch):
        _write_extension(plugin_dir, "idx_a", collector=_plugin("collector", "ACollector", "a"))
        index = _index_for(plugin_dir)

        def fail():
            raise AssertionError("registry map built")

        monkeypatch.setattr(loader_module, "_get_registry_map", fail)
        registries = _registries()
        PluginLoader(str(plugin_dir), registries).load_selected(_select_collectors, index)

        assert registries["collector"].get("a") is not None

    def test_selected_load_without_index_scans_every_extension(self, plugin_dir):
        _write_extension(
            plugin_dir,
            "idx_a",
            collector=_plugin("collector", "ACollector", "a"),
            panel=_plugin("panel", "APanel", "a_panel"),
        )
        _write_extension(plugin_dir, "idx_b", collector=_plugin("collector", "BCollector", "b"))

        registries = _registries()
        loaded = PluginLoader(str(plugin_dir), registries).load_selected(_select_collectors, {})

        assert loaded == ["idx_a", "idx_b"]
        assert registries["collector"].names() == ["a", "b"]
        assert registries["panel"].get("a_panel") is None
        assert "_plugins_idx_a.panel" in sys.modules

    def test_changed_extension_is_scanned_and_others_stay_cached(self, plugin_dir):
        folder_a = _write_extension(
            plugin_dir,
            "idx_a",
            collector=_plugin("collector", "ACollector", "a"),
            panel=_plugin("panel", "APanel", "a_panel"),
        )
        _write_extension(
            plugin_dir,
            "idx_b",
            collector=_plugin("collector", "BCollector", "b"),
            panel=_plugin("panel", "BPanel", "b_panel"),
        )
        index = _index_for(plugin_dir)
        with open(folder_a / "collector.py", "a") as f:
            f.write(_plugin("collector", "ANewCollector", "a_new"))

        registries = _registries()
        PluginLoader(str(plugin_dir), registries).load_selected(_select_collectors, index)

        assert registries["collector"].get("a_new") is not None
        assert registries["collector"].get("b") is not None
        assert "_plugins_idx_a.panel" in sys.modules
        assert "_plugins_idx_b.panel" not in sys.modules

    def test_selected_load_skips_needs_setup_extensions(self, plugin_dir, monkeypatch):
        _write_extension(plugin_dir, "idx_a", collector=_plugin("collector", "ACollector", "a"))
        _write_extension(plugin_dir, "idx_b", collector=_plugin("collector", "BCollector", "b"))
        index = _index_for(plugin_dir)
        monkeypatch.setattr(loader_module, "needs_setup", lambda folder: folder.endswith("idx_a"))

        registries = _registries()
        loaded = PluginLoader(str(plugin_dir), registries).load_selected(_select_collectors, index)

        assert loaded == ["idx_b"]
        assert registries["collector"].get("a") is None
        assert "_plugins_idx_a" not in sys.modules

    def test_disabled_class_is_not_registered(self, plugin_dir):
        _write_extension(
            plugin_dir,
            "idx_a",
            collector=_plugin("collector", "ACollector", "a") + _plugin("collector", "BCollector", "b", enabled=False),
        )
        index = _index_for(plugin_dir)

        registries = _registries()
        loader = PluginLoader(
            str(plugin_dir),
            registries,
            enabled={"collector:ACollector": False, "collector:BCollector": True},
        )
        loader.load_selected(_select_collectors, index)

        assert registries["collector"].get("a") is None
        assert registries["collector"].get("b") is not None

    def test_cached_order_matches_full_load(self, plugin_dir):
        _write_extension(
            plugin_dir,
            "idx_b",
            a_user="from .z_owner import AAOwned\n" + _plugin("collector", "ZZLocal", "b_local"),
            z_owner=_plugin("collector", "AAOwned", "b_owned"),
        )
        _write_extension(plugin_dir, "idx_a", later=_plugin("collector", "ACollector", "a"))
        _write_extension(plugin_dir, "idx_c", mod=_plugin("collector", "CCollector", "c"))

        full = _registries()
        recording = PluginLoader(str(plugin_dir), full, record_index=True)
        recording.load_all()
        full_order = full["collector"].names()
        _purge_index_extensions()

        cached = _registries()
        PluginLoader(str(plugin_dir), cached).load_selected(_select_all, recording.records)

        assert full_order == ["a", "b_owned", "b_local", "c"]
        assert cached["collector"].names() == full_order

    @pytest.mark.parametrize(
        "broken",
        [
            PluginEntry("collector", "collector", "Gone", "a"),
            PluginEntry("collector", "gone", "ACollector", "a"),
        ],
        ids=["missing_class", "missing_module"],
    )
    def test_missing_class_in_cached_module_falls_back_to_scan(self, plugin_dir, monkeypatch, broken):
        _write_extension(
            plugin_dir,
            "idx_a",
            collector=_plugin("collector", "ACollector", "a"),
            panel=_plugin("panel", "APanel", "a_panel"),
        )
        record = _index_for(plugin_dir)["idx_a"]
        index = {"idx_a": ExtensionRecord(record.fingerprint, (broken,))}
        warnings = _capture_warnings(monkeypatch)

        registries = _registries()
        loaded = PluginLoader(str(plugin_dir), registries).load_selected(_select_collectors, index)

        assert loaded == ["idx_a"]
        assert registries["collector"].get("a").__name__ == "ACollector"
        assert "_plugins_idx_a.panel" in sys.modules
        assert any("idx_a" in text for text in warnings)

    def test_broken_package_init_stays_unloaded_after_the_fallback(self, plugin_dir, monkeypatch):
        folder = _write_extension(plugin_dir, "idx_a", collector=_plugin("collector", "ACollector", "a"))
        (folder / "__init__.py").write_text("raise RuntimeError('broken package')\n")
        entry = PluginEntry("collector", "collector", "ACollector", "a")
        index = {"idx_a": ExtensionRecord(plugin_index.extension_fingerprint(str(folder)), (entry,))}
        _capture_warnings(monkeypatch)

        registries = _registries()
        loaded = PluginLoader(str(plugin_dir), registries).load_selected(_select_collectors, index)

        assert loaded == []
        assert registries["collector"].get("a") is None
        assert "_plugins_idx_a" not in sys.modules

    def test_fingerprint_failure_scans_the_extension(self, plugin_dir, monkeypatch):
        _write_extension(
            plugin_dir,
            "idx_a",
            collector=_plugin("collector", "ACollector", "a"),
            panel=_plugin("panel", "APanel", "a_panel"),
        )
        index = _index_for(plugin_dir)
        warnings = _capture_warnings(monkeypatch)
        monkeypatch.setattr(plugin_index, "extension_fingerprint", _vanish)

        registries = _registries()
        loaded = PluginLoader(str(plugin_dir), registries).load_selected(_select_collectors, index)

        assert loaded == ["idx_a"]
        assert registries["collector"].get("a") is not None
        assert "_plugins_idx_a.panel" in sys.modules
        assert any("idx_a" in text for text in warnings)

    def test_unselected_extension_still_gets_its_dll_directory(self, plugin_dir, monkeypatch):
        folder = _write_extension(plugin_dir, "idx_a", panel=_plugin("panel", "APanel", "a_panel"))
        index = _index_for(plugin_dir)
        seen = []
        monkeypatch.setattr(loader_module, "_setup_dll_directory", seen.append)

        PluginLoader(str(plugin_dir), _registries()).load_selected(_select_collectors, index)

        assert seen == [str(folder)]
        assert "_plugins_idx_a" not in sys.modules

    def test_cached_module_can_import_from_shared_packages(self, plugin_dir):
        packages = plugin_dir / _PACKAGES_DIR
        packages.mkdir()
        (packages / "idx_shared_dep.py").write_text("VALUE = 1\n")
        _write_extension(
            plugin_dir,
            "idx_a",
            collector="import idx_shared_dep\n" + _plugin("collector", "ACollector", "a"),
        )
        try:
            index = _index_for(plugin_dir)
            sys.path.remove(str(packages))
            sys.modules.pop("idx_shared_dep", None)

            registries = _registries()
            PluginLoader(str(plugin_dir), registries).load_selected(_select_collectors, index)

            assert registries["collector"].get("a") is not None
        finally:
            if str(packages) in sys.path:
                sys.path.remove(str(packages))
            sys.modules.pop("idx_shared_dep", None)


class TestImportExtensionFailures:
    def test_reports_failed_modules(self, plugin_dir):
        folder = _write_extension(
            plugin_dir,
            "idx_a",
            broken="raise ImportError('missing dependency')\n",
            collector=_plugin("collector", "ACollector", "a"),
        )

        failed = []
        found = loader_module._import_extension("idx_a", str(folder), failed)

        assert failed == ["_plugins_idx_a.broken"]
        assert [cls.NAME for _, cls in found] == ["a"]

    def test_failed_module_is_tried_again_by_the_next_import(self, plugin_dir):
        folder = _write_extension(plugin_dir, "idx_a", broken="raise ImportError('missing dependency')\n")

        loader_module._import_extension("idx_a", str(folder))
        failed = []
        loader_module._import_extension("idx_a", str(folder), failed)

        assert failed == ["_plugins_idx_a.broken"]


class TestRoleScopedLoad:
    def test_worker_selects_by_kind_and_name(self, scoped_env, monkeypatch):
        _write_extension(
            scoped_env,
            "idx_a",
            collector=_plugin("collector", "ColorCollector", "color"),
            other=_plugin("collector", "OtherCollector", "other"),
            filter=_plugin("filter", "ColorFilter", "color"),
            loader=_plugin("imageloader", "ALoader", "a_loader"),
        )
        _write_extension(scoped_env, "idx_b", parser=_plugin("parser", "ColorNamedParser", "color"))
        index = _index_for(scoped_env)
        monkeypatch.setattr(plugin_index, "read_index", lambda: index)

        loaded = loader_module.load_worker_plugins("collector", "color")

        assert loaded == ["idx_a"]
        assert collector_resolver.registry.names() == ["color"]
        assert parser_resolver.registry.names() == []
        assert set(image_loader_resolver.registry.names()) == {"a_loader", "system_thumbnail"}
        assert "_plugins_idx_a.filter" not in sys.modules
        assert "_plugins_idx_a.other" not in sys.modules
        assert "_plugins_idx_b.parser" not in sys.modules

    def test_indexer_selects_collectors_and_parsers(self, scoped_env, monkeypatch):
        _write_extension(
            scoped_env,
            "idx_a",
            collector=_plugin("collector", "ACollector", "a"),
            parser=_plugin("parser", "AParser", "a_parser"),
            loader=_plugin("imageloader", "ALoader", "a_loader"),
        )
        index = _index_for(scoped_env)
        monkeypatch.setattr(plugin_index, "read_index", lambda: index)

        loaded = loader_module.load_indexer_plugins()

        assert loaded == ["idx_a"]
        assert collector_resolver.registry.names() == ["a"]
        assert parser_resolver.registry.names() == ["a_parser"]
        assert image_loader_resolver.registry.names() == []
        assert "_plugins_idx_a.loader" not in sys.modules

    def test_scoped_load_applies_the_saved_order(self, scoped_env, monkeypatch):
        _write_extension(
            scoped_env,
            "idx_a",
            collector=_plugin("collector", "ACollector", "a", priority=1) + _plugin("collector", "BCollector", "b", priority=2),
        )
        monkeypatch.setattr(plugin_index, "read_index", lambda: {})
        monkeypatch.setattr(PluginSettings, "priority_order", lambda self, kind: ["a", "b"] if kind == "collector" else [])

        loader_module.load_indexer_plugins()

        assert collector_resolver.registry.names() == ["a", "b"]

    @pytest.mark.parametrize(
        ("call", "expected"),
        [
            (
                'loader.load_worker_plugins("collector", "a")',
                {"collector": ["a"], "parser": [], "imageloader": ["a_loader", "system_thumbnail"]},
            ),
            (
                "loader.load_indexer_plugins()",
                {"collector": ["a", "other"], "parser": ["a_parser"], "imageloader": []},
            ),
        ],
        ids=["worker", "indexer"],
    )
    def test_cached_scoped_load_stays_free_of_qt(self, plugin_dir, tmp_path, call, expected):
        _write_extension(
            plugin_dir,
            "idx_a",
            collector=_plugin("collector", "ACollector", "a"),
            other=_plugin("collector", "OtherCollector", "other"),
            parser=_plugin("parser", "AParser", "a_parser"),
            loader=_plugin("imageloader", "ALoader", "a_loader"),
            filter=_plugin("filter", "AFilter", "a_filter"),
            panel=_plugin("panel", "APanel", "a_panel"),
        )
        index_file = tmp_path / "plugin_index.json"
        plugin_index.write_index(_index_for(plugin_dir), str(index_file))
        code = (
            "import json, sys\n"
            "from wafer.plugin import loader, plugin_index\n"
            "from wafer.plugin.collector.handler import collector_resolver\n"
            "from wafer.plugin.parser.handler import parser_resolver\n"
            "from wafer.plugin.imageloader.handler import image_loader_resolver\n"
            f"loader.get_plugin_dir = lambda: {str(plugin_dir)!r}\n"
            "reads = []\n"
            "real_read = plugin_index.read_index\n"
            f"plugin_index.read_index = lambda: reads.append(1) or real_read({str(index_file)!r})\n"
            f"{call}\n"
            "try:\n"
            "    loader.get_command_registry()\n"
            "    command_registry = True\n"
            "except RuntimeError:\n"
            "    command_registry = False\n"
            "print(json.dumps({\n"
            "    'qt': 'PySide6' in sys.modules,\n"
            "    'reads': len(reads),\n"
            "    'command_registry': command_registry,\n"
            "    'panel': '_plugins_idx_a.panel' in sys.modules,\n"
            "    'collector': sorted(collector_resolver.registry.names()),\n"
            "    'parser': sorted(parser_resolver.registry.names()),\n"
            "    'imageloader': sorted(image_loader_resolver.registry.names()),\n"
            "}))\n"
        )

        result = _run_probe(code, tmp_path)

        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report == {"qt": False, "reads": 1, "command_registry": False, "panel": False, **expected}


class TestRegisterImageLoaders:
    def test_registers_the_builtin_loader_without_the_registry_map(self, monkeypatch):
        def fail():
            raise AssertionError("registry map built")

        monkeypatch.setattr(loader_module, "_get_registry_map", fail)
        registries = _registries()

        registration.register_image_loaders(registries)

        assert registries["imageloader"].names() == ["system_thumbnail"]


class TestLoadPluginsIndexWriting:
    @pytest.fixture
    def full_load_env(self, scoped_env, monkeypatch):
        monkeypatch.setattr(registration, "register_all", lambda registries: None)
        monkeypatch.setattr(PluginLoader, "_fire_configure", lambda self: None)
        _write_extension(scoped_env, "idx_a", collector=_plugin("collector", "ACollector", "a"))
        return scoped_env

    def test_writes_the_records_when_asked(self, full_load_env, monkeypatch):
        written = []
        monkeypatch.setattr(plugin_index, "write_index", written.append)

        loaded = loader_module.load_plugins(write_index=True)

        assert loaded == ["idx_a"]
        assert [list(records) for records in written] == [["idx_a"]]

    def test_does_not_write_by_default(self, full_load_env, monkeypatch):
        written = []
        monkeypatch.setattr(plugin_index, "write_index", written.append)

        loaded = loader_module.load_plugins()

        assert loaded == ["idx_a"]
        assert written == []
        assert loader_module.get_command_registry() is not None

    def test_write_failure_does_not_stop_the_load(self, full_load_env, monkeypatch):
        def fail(records):
            raise PermissionError("cannot create the cache folder")

        monkeypatch.setattr(plugin_index, "write_index", fail)
        warnings = _capture_warnings(monkeypatch)

        loaded = loader_module.load_plugins(write_index=True)

        assert loaded == ["idx_a"]
        assert any("index" in text.lower() for text in warnings)

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch

from afterimages.plugin.registry import BasePlugin, PluginRegistry
from afterimages.plugin.loader import PluginLoader


@pytest.fixture
def plugin_env(tmp_path):
    plugin_dir = tmp_path / 'plugins'
    stub_dir = plugin_dir / 'stub_plugin'
    stub_dir.mkdir(parents=True)
    (stub_dir / '__init__.py').write_text('')
    (stub_dir / 'grid.py').write_text(
        'from afterimages.plugin.grid.base import ImageGridPlugin\n'
        'class StubGridPlugin(ImageGridPlugin):\n'
        '    NAME = "stub_test"\n'
        '    EXTENSIONS = (".stub",)\n'
        '    PRIORITY = 10\n'
        '    _post_installed = False\n'
        '    _configured = False\n'
        '    def load(self, path, size=None): return None\n'
        '    @classmethod\n'
        '    def post_install(cls, plugin_dir, on_progress=None): cls._post_installed = True\n'
        '    @classmethod\n'
        '    def configure(cls): cls._configured = True\n'
    )
    yield str(plugin_dir), str(stub_dir)
    for key in list(sys.modules):
        if key.startswith('_plugins_stub_plugin'):
            del sys.modules[key]


def _make_registries():
    return {
        'viewer': PluginRegistry(),
        'grid': PluginRegistry(),
        'collector': PluginRegistry(),
    }


class TestPostInstallHook:

    def test_post_install_called_on_fresh_install(self, plugin_env):
        plugin_dir, stub_dir = plugin_env
        req = os.path.join(stub_dir, 'requirements.txt')
        with open(req, 'w') as f:
            f.write('')

        registries = _make_registries()
        with patch('afterimages.plugin.loader._install_requirements', return_value=True):
            loader = PluginLoader(plugin_dir, registries)
            loaded = loader.load_all()

        assert 'stub_plugin' in loaded
        plugin_cls = registries['grid'].get('stub_test')
        assert plugin_cls is not None
        assert plugin_cls._post_installed is True

    def test_post_install_not_called_when_skip_install(self, plugin_env):
        plugin_dir, stub_dir = plugin_env

        registries = _make_registries()
        loader = PluginLoader(plugin_dir, registries, skip_install=True)
        loaded = loader.load_all()

        assert 'stub_plugin' in loaded
        plugin_cls = registries['grid'].get('stub_test')
        assert plugin_cls is not None
        assert plugin_cls._post_installed is False

    def test_post_install_not_called_when_already_installed(self, plugin_env):
        plugin_dir, stub_dir = plugin_env
        pkg_dir = os.path.join(stub_dir, '.packages')
        os.makedirs(pkg_dir)
        stamp = os.path.join(pkg_dir, '.installed')
        with open(stamp, 'w') as f:
            f.write('')

        registries = _make_registries()
        loader = PluginLoader(plugin_dir, registries)
        loaded = loader.load_all()

        assert 'stub_plugin' in loaded
        plugin_cls = registries['grid'].get('stub_test')
        assert plugin_cls is not None
        assert plugin_cls._post_installed is False


class TestConfigureHook:

    def test_configure_called_after_load_all(self, plugin_env):
        plugin_dir, _ = plugin_env

        registries = _make_registries()
        loader = PluginLoader(plugin_dir, registries, skip_install=True)
        loaded = loader.load_all()

        assert 'stub_plugin' in loaded
        plugin_cls = registries['grid'].get('stub_test')
        assert plugin_cls is not None
        assert plugin_cls._configured is True

    def test_configure_called_even_with_skip_install(self, plugin_env):
        plugin_dir, _ = plugin_env

        registries = _make_registries()
        loader = PluginLoader(plugin_dir, registries, skip_install=True)
        loader.load_all()

        plugin_cls = registries['grid'].get('stub_test')
        assert plugin_cls is not None
        assert plugin_cls._configured is True

    def test_configure_failure_does_not_block_loading(self, tmp_path):
        plugin_dir = tmp_path / 'plugins'
        broken_dir = plugin_dir / 'broken_plugin'
        broken_dir.mkdir(parents=True)
        (broken_dir / '__init__.py').write_text('')
        (broken_dir / 'grid.py').write_text(
            'from afterimages.plugin.grid.base import ImageGridPlugin\n'
            'class BrokenConfigure(ImageGridPlugin):\n'
            '    NAME = "broken"\n'
            '    EXTENSIONS = (".brk",)\n'
            '    PRIORITY = 10\n'
            '    def load(self, path, size=None): return None\n'
            '    @classmethod\n'
            '    def configure(cls): raise RuntimeError("boom")\n'
        )

        registries = _make_registries()
        loader = PluginLoader(str(plugin_dir), registries, skip_install=True)
        loaded = loader.load_all()
        assert 'broken_plugin' in loaded

        for key in list(sys.modules):
            if key.startswith('_plugins_broken_plugin'):
                del sys.modules[key]


class TestBasePluginHooksDefault:

    def test_post_install_default_is_noop(self):
        BasePlugin.post_install('/tmp')

    def test_configure_default_is_noop(self):
        BasePlugin.configure()


class TestDeferredCommandRegistration:

    def test_commands_deferred_not_registered_immediately(self, tmp_path):
        plugin_dir = tmp_path / 'plugins'
        cmd_dir = plugin_dir / 'cmd_plugin'
        cmd_dir.mkdir(parents=True)
        (cmd_dir / '__init__.py').write_text('')
        (cmd_dir / 'commands.py').write_text(
            'from afterimages.core.actions.command.menu import MenuGroup\n'
            'from afterimages.core.actions.command.core import CommandMeta\n'
            'class TestCmdGroup(MenuGroup):\n'
            '    NAME = "TestCmd"\n'
            '    @classmethod\n'
            '    def commands(cls):\n'
            '        return [CommandMeta(path="tcmd.noop", display="Noop", func=lambda ctx: None)]\n'
        )
        registries = _make_registries()
        PluginLoader._deferred_commands.clear()
        loader = PluginLoader(str(plugin_dir), registries, skip_install=True)
        loader.load_all()
        assert len(PluginLoader._deferred_commands) > 0
        from afterimages.core.actions.command.core import CommandRegistry
        reg = CommandRegistry.instance()
        assert not reg.has_command('tcmd.noop')
        PluginLoader.register_extension_commands()
        assert reg.has_command('tcmd.noop')
        for key in list(sys.modules):
            if key.startswith('_plugins_cmd_plugin'):
                del sys.modules[key]


class TestSubmoduleRelativeImport:

    def test_submodule_not_treated_as_package(self, tmp_path):
        plugin_dir = tmp_path / 'plugins'
        rel_dir = plugin_dir / 'rel_plugin'
        rel_dir.mkdir(parents=True)
        (rel_dir / '__init__.py').write_text('')
        (rel_dir / 'state.py').write_text('value = 42\n')
        (rel_dir / 'reader.py').write_text(
            'from .state import value\n'
            'def get(): return value\n'
        )
        registries = _make_registries()
        loader = PluginLoader(str(plugin_dir), registries, skip_install=True)
        loader.load_all()
        mod = sys.modules.get('_plugins_rel_plugin.reader')
        assert mod is not None
        assert mod.get() == 42
        state_mod = sys.modules.get('_plugins_rel_plugin.state')
        assert state_mod is not None
        assert state_mod.value == 42
        assert not hasattr(mod, '__path__')
        for key in list(sys.modules):
            if key.startswith('_plugins_rel_plugin'):
                del sys.modules[key]


class TestRunSubprocess:

    def test_stderr_drained_without_deadlock(self, tmp_path):
        from afterimages.plugin.loader import _run_subprocess
        script = tmp_path / 'noisy.py'
        script.write_text(
            'import sys\n'
            'sys.stderr.write("x" * 100000 + "\\n")\n'
            'sys.exit(0)\n'
        )
        _run_subprocess([sys.executable, str(script)])

    def test_stderr_captured_on_failure(self, tmp_path):
        from afterimages.plugin.loader import _run_subprocess
        script = tmp_path / 'fail.py'
        script.write_text(
            'import sys\n'
            'sys.stderr.write("custom error msg\\n")\n'
            'sys.exit(1)\n'
        )
        with pytest.raises(RuntimeError, match="custom error msg"):
            _run_subprocess([sys.executable, str(script)])

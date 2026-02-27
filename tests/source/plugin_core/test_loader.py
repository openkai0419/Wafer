import os
import sys
import time
import py_compile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from source.plugin_core.loader import (
    get_plugin_dir,
    _needs_install,
    _install_requirements,
    _register_api_module,
    _discover_plugins,
    _run_pip_frozen,
    _run_subprocess,
    _setup_dll_directory,
    install_plugin_deps,
    any_needs_install,
    _PACKAGES_DIR,
    _INSTALL_STAMP,
    _API_MODULE_NAME,
    PluginLoader,
    load_plugins,
)
from source.plugin_core.registry import PluginRegistry
from source.plugin_core.viewer.base import BaseViewerPlugin
from source.plugin_core.grid.base import BaseGridPlugin
from source.plugin_core.collector.base import BaseCollectorPlugin


def test_compile():
    py_compile.compile('source/plugin_core/loader.py')


def test_get_plugin_dir_dev():
    d = get_plugin_dir()
    assert d.endswith('plugins')
    assert os.path.isabs(d)


def test_get_plugin_dir_frozen():
    with patch.object(sys, 'frozen', True, create=True), \
         patch.object(sys, 'executable', r'C:\app\main.exe'):
        assert get_plugin_dir() == r'C:\app\plugins'


class TestNeedsInstall:
    def test_no_requirements(self, tmp_path):
        assert _needs_install(str(tmp_path)) is False

    def test_no_stamp(self, tmp_path):
        (tmp_path / 'requirements.txt').write_text('numpy')
        assert _needs_install(str(tmp_path)) is True

    def test_stamp_newer_than_req(self, tmp_path):
        req = tmp_path / 'requirements.txt'
        req.write_text('numpy')
        vendor = tmp_path / _PACKAGES_DIR
        vendor.mkdir()
        stamp = vendor / _INSTALL_STAMP
        stamp.touch()
        os.utime(stamp, (time.time() + 10, time.time() + 10))
        assert _needs_install(str(tmp_path)) is False

    def test_req_newer_than_stamp(self, tmp_path):
        req = tmp_path / 'requirements.txt'
        req.write_text('numpy')
        vendor = tmp_path / _PACKAGES_DIR
        vendor.mkdir()
        stamp = vendor / _INSTALL_STAMP
        stamp.touch()
        os.utime(stamp, (time.time() - 100, time.time() - 100))
        os.utime(req, (time.time(), time.time()))
        assert _needs_install(str(tmp_path)) is True


class TestInstallRequirements:
    def test_success(self, tmp_path):
        req = tmp_path / 'requirements.txt'
        req.write_text('')
        with patch('source.plugin_core.loader._run_subprocess'):
            result = _install_requirements(str(tmp_path))
        assert result is True
        assert (tmp_path / _PACKAGES_DIR / _INSTALL_STAMP).exists()

    def test_real_pip_creates_packages_dir(self, tmp_path):
        req = tmp_path / 'requirements.txt'
        req.write_text('')
        result = _install_requirements(str(tmp_path))
        assert result is True
        packages = tmp_path / _PACKAGES_DIR
        assert packages.is_dir()
        assert (packages / _INSTALL_STAMP).exists()

    def test_real_pip_installs_pure_python_package(self, tmp_path):
        pkg_src = tmp_path / 'src_pkg'
        pkg_src.mkdir()
        pkg_inner = pkg_src / 'mypkg'
        pkg_inner.mkdir()
        (pkg_inner / '__init__.py').write_text('VERSION = "0.1"')
        (pkg_src / 'pyproject.toml').write_text(
            '[build-system]\n'
            'requires = ["setuptools"]\n'
            'build-backend = "setuptools.build_meta"\n'
            '[project]\n'
            'name = "mypkg"\n'
            'version = "0.1"\n'
        )
        req = tmp_path / 'plugin'
        req.mkdir()
        (req / 'requirements.txt').write_text(str(pkg_src))
        result = _install_requirements(str(req))
        assert result is True
        packages = req / _PACKAGES_DIR
        assert packages.is_dir()
        assert (packages / _INSTALL_STAMP).exists()
        installed_files = [f.name for f in packages.iterdir() if f.name != _INSTALL_STAMP]
        assert len(installed_files) > 0

    def test_failure(self, tmp_path):
        req = tmp_path / 'requirements.txt'
        req.write_text('nonexistent-pkg-xyz')
        with patch('source.plugin_core.loader._run_subprocess', side_effect=RuntimeError('fail')):
            result = _install_requirements(str(tmp_path))
        assert result is False

    def test_frozen_uses_install_deps_flag(self, tmp_path):
        req = tmp_path / 'requirements.txt'
        req.write_text('')
        with patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, 'executable', r'C:\app\main.exe'), \
             patch('source.plugin_core.loader._run_subprocess') as mock_sub:
            _install_requirements(str(tmp_path))
        cmd = mock_sub.call_args[0][0]
        assert cmd[0] == r'C:\app\main.exe'
        assert '--install-deps' in cmd
        assert str(tmp_path) in cmd

    def test_dev_uses_python_m_pip(self, tmp_path):
        req = tmp_path / 'requirements.txt'
        req.write_text('')
        frozen_was = getattr(sys, 'frozen', None)
        if hasattr(sys, 'frozen'):
            delattr(sys, 'frozen')
        try:
            with patch('source.plugin_core.loader._run_subprocess') as mock_sub:
                _install_requirements(str(tmp_path))
            cmd = mock_sub.call_args[0][0]
            assert cmd[0] == sys.executable
            assert '-m' in cmd
            assert 'pip' in cmd
        finally:
            if frozen_was is not None:
                sys.frozen = frozen_was

    def test_on_progress_forwarded(self, tmp_path):
        req = tmp_path / 'requirements.txt'
        req.write_text('')
        progress = MagicMock()
        with patch('source.plugin_core.loader._run_subprocess') as mock_sub:
            _install_requirements(str(tmp_path), on_progress=progress)
        assert mock_sub.call_args[0][1] is progress


class TestRunPipFrozen:
    def test_success(self):
        with patch('pip._internal.cli.main.main', return_value=0):
            _run_pip_frozen(['install', '--quiet'])

    def test_nonzero_exit(self):
        with patch('pip._internal.cli.main.main', return_value=1):
            with pytest.raises(RuntimeError, match='pip exited with code 1'):
                _run_pip_frozen(['install', '--quiet'])

    def test_system_exit_caught(self):
        with patch('pip._internal.cli.main.main', side_effect=SystemExit(2)):
            with pytest.raises(RuntimeError, match='pip exited with code 2'):
                _run_pip_frozen(['install', '--quiet'])

    def test_system_exit_none(self):
        with patch('pip._internal.cli.main.main', side_effect=SystemExit(None)):
            with pytest.raises(RuntimeError):
                _run_pip_frozen(['install', '--quiet'])

    def test_script_maker_patched_and_restored(self):
        from pip._vendor.distlib.scripts import ScriptMaker
        original = ScriptMaker.make_multiple
        with patch('pip._internal.cli.main.main', return_value=0):
            _run_pip_frozen(['install', '--quiet'])
        assert ScriptMaker.make_multiple is original

    def test_script_maker_restored_on_error(self):
        from pip._vendor.distlib.scripts import ScriptMaker
        original = ScriptMaker.make_multiple
        with patch('pip._internal.cli.main.main', side_effect=SystemExit(1)):
            with pytest.raises(RuntimeError):
                _run_pip_frozen(['install', '--quiet'])
        assert ScriptMaker.make_multiple is original


class TestRegisterApiModule:
    def test_registers_afterimages(self):
        saved = sys.modules.pop(_API_MODULE_NAME, None)
        try:
            _register_api_module()
            assert _API_MODULE_NAME in sys.modules
        finally:
            if saved is not None:
                sys.modules[_API_MODULE_NAME] = saved


class TestDiscoverPlugins:
    def test_finds_viewer_plugin(self):
        class TestPlugin(BaseViewerPlugin):
            NAME = 'test_disc'
            EXTENSIONS = ('.test',)
            PRIORITY = 1

            def load_content(self, path):
                return None

        import types
        mod = types.ModuleType('fake')
        mod.TestPlugin = TestPlugin
        found = _discover_plugins(mod)
        keys = [k for k, _ in found]
        assert 'viewer' in keys

    def test_ignores_no_name(self):
        class NoNamePlugin(BaseViewerPlugin):
            NAME = ''
            EXTENSIONS = ()
            PRIORITY = 0

            def load_content(self, path):
                return None

        import types
        mod = types.ModuleType('fake')
        mod.NoNamePlugin = NoNamePlugin
        assert _discover_plugins(mod) == []


class TestPluginLoader:
    def test_load_all_empty_dir(self, tmp_path):
        registries = {'viewer': PluginRegistry(), 'grid': PluginRegistry(), 'collector': PluginRegistry()}
        loader = PluginLoader(str(tmp_path), registries)
        assert loader.load_all() == []

    def test_load_all_nonexistent_dir(self, tmp_path):
        registries = {'viewer': PluginRegistry(), 'grid': PluginRegistry(), 'collector': PluginRegistry()}
        loader = PluginLoader(str(tmp_path / 'nope'), registries)
        assert loader.load_all() == []

    def test_load_all_with_real_plugins(self):
        from source.plugin_core.viewer.handler import viewer_handler
        from source.plugin_core.grid.handler import grid_handler
        from source.plugin_core.collector.handler import collector_handler
        assert viewer_handler.registry.get('image') is not None
        assert grid_handler.registry.get('image') is not None
        assert collector_handler.registry.get('exif') is not None


def test_load_plugins_returns_list():
    result = load_plugins(skip_install=True)
    assert isinstance(result, list)


class TestAnyNeedsInstall:
    def test_no_plugins_dir(self, tmp_path):
        with patch('source.plugin_core.loader.get_plugin_dir', return_value=str(tmp_path / 'nope')):
            assert any_needs_install() is False

    def test_all_installed(self, tmp_path):
        p1 = tmp_path / 'plugin_a'
        p1.mkdir()
        (p1 / 'requirements.txt').write_text('pkg')
        vendor = p1 / _PACKAGES_DIR
        vendor.mkdir()
        stamp = vendor / _INSTALL_STAMP
        stamp.touch()
        os.utime(stamp, (time.time() + 10, time.time() + 10))
        with patch('source.plugin_core.loader.get_plugin_dir', return_value=str(tmp_path)):
            assert any_needs_install() is False

    def test_one_needs_install(self, tmp_path):
        p1 = tmp_path / 'plugin_a'
        p1.mkdir()
        (p1 / 'requirements.txt').write_text('pkg')
        with patch('source.plugin_core.loader.get_plugin_dir', return_value=str(tmp_path)):
            assert any_needs_install() is True

    def test_skips_hidden_and_pycache(self, tmp_path):
        (tmp_path / '.hidden').mkdir()
        (tmp_path / '.hidden' / 'requirements.txt').write_text('pkg')
        (tmp_path / '__pycache__').mkdir()
        (tmp_path / '__pycache__' / 'requirements.txt').write_text('pkg')
        with patch('source.plugin_core.loader.get_plugin_dir', return_value=str(tmp_path)):
            assert any_needs_install() is False

    def test_no_requirements_file(self, tmp_path):
        (tmp_path / 'plugin_a').mkdir()
        with patch('source.plugin_core.loader.get_plugin_dir', return_value=str(tmp_path)):
            assert any_needs_install() is False


class TestRunSubprocess:
    def test_success(self):
        cmd = [sys.executable, '-c', 'import sys; sys.exit(0)']
        _run_subprocess(cmd)

    def test_failure_raises(self):
        cmd = [sys.executable, '-c', 'import sys; sys.exit(1)']
        with pytest.raises(RuntimeError, match='pip exited with code 1'):
            _run_subprocess(cmd)

    def test_on_progress_called(self):
        cmd = [sys.executable, '-c', 'import time; time.sleep(0.15)']
        calls = []
        _run_subprocess(cmd, on_progress=lambda: calls.append(True))
        assert len(calls) > 0


class TestInstallPluginDeps:
    def test_success(self, tmp_path):
        req = tmp_path / 'requirements.txt'
        req.write_text('')
        with patch('source.plugin_core.loader._run_pip_frozen'):
            result = install_plugin_deps(str(tmp_path))
        assert result == 0
        assert (tmp_path / _PACKAGES_DIR / _INSTALL_STAMP).exists()

    def test_failure(self, tmp_path):
        req = tmp_path / 'requirements.txt'
        req.write_text('')
        with patch('source.plugin_core.loader._run_pip_frozen', side_effect=RuntimeError('fail')):
            result = install_plugin_deps(str(tmp_path))
        assert result == 1

    def test_passes_no_cache_dir(self, tmp_path):
        req = tmp_path / 'requirements.txt'
        req.write_text('')
        with patch('source.plugin_core.loader._run_pip_frozen') as mock_frozen:
            install_plugin_deps(str(tmp_path))
        args = mock_frozen.call_args[0][0]
        assert '--no-cache-dir' in args
        assert '--target' in args


class TestRunPipFrozenRestore:
    def test_stdout_stderr_restored_on_success(self):
        orig_out, orig_err = sys.stdout, sys.stderr
        with patch('pip._internal.cli.main.main', return_value=0):
            _run_pip_frozen(['install', '--quiet'])
        assert sys.stdout is orig_out
        assert sys.stderr is orig_err

    def test_stdout_stderr_restored_on_failure(self):
        orig_out, orig_err = sys.stdout, sys.stderr
        with patch('pip._internal.cli.main.main', side_effect=SystemExit(1)):
            with pytest.raises(RuntimeError):
                _run_pip_frozen(['install', '--quiet'])
        assert sys.stdout is orig_out
        assert sys.stderr is orig_err


class TestPluginLoaderSkipInstall:
    def test_skip_install_does_not_call_pip(self, tmp_path):
        plugin = tmp_path / 'myplugin'
        plugin.mkdir()
        (plugin / 'requirements.txt').write_text('numpy')
        (plugin / '__init__.py').write_text('')
        registries = {'viewer': PluginRegistry(), 'grid': PluginRegistry(), 'collector': PluginRegistry()}
        loader = PluginLoader(str(tmp_path), registries, skip_install=True)
        with patch('source.plugin_core.loader._install_requirements') as mock_install:
            loader.load_all()
        mock_install.assert_not_called()

    def test_no_skip_install_calls_pip(self, tmp_path):
        plugin = tmp_path / 'myplugin'
        plugin.mkdir()
        (plugin / 'requirements.txt').write_text('numpy')
        (plugin / '__init__.py').write_text('')
        registries = {'viewer': PluginRegistry(), 'grid': PluginRegistry(), 'collector': PluginRegistry()}
        loader = PluginLoader(str(tmp_path), registries, skip_install=False)
        with patch('source.plugin_core.loader._install_requirements', return_value=True) as mock_install:
            loader.load_all()
        mock_install.assert_called_once()


class TestPluginLoaderPackagesPath:
    def test_packages_dir_added_to_sys_path(self, tmp_path):
        plugin = tmp_path / 'myplugin'
        plugin.mkdir()
        vendor = plugin / _PACKAGES_DIR
        vendor.mkdir()
        (vendor / _INSTALL_STAMP).touch()
        (plugin / '__init__.py').write_text('')
        registries = {'viewer': PluginRegistry(), 'grid': PluginRegistry(), 'collector': PluginRegistry()}
        loader = PluginLoader(str(tmp_path), registries, skip_install=True)
        original_path = sys.path.copy()
        try:
            loader.load_all()
            assert str(vendor) in sys.path
        finally:
            sys.path[:] = original_path

    def test_packages_dir_not_added_if_missing(self, tmp_path):
        plugin = tmp_path / 'myplugin'
        plugin.mkdir()
        (plugin / '__init__.py').write_text('')
        registries = {'viewer': PluginRegistry(), 'grid': PluginRegistry(), 'collector': PluginRegistry()}
        loader = PluginLoader(str(tmp_path), registries, skip_install=True)
        vendor_path = str(plugin / _PACKAGES_DIR)
        original_path = sys.path.copy()
        try:
            loader.load_all()
            assert vendor_path not in sys.path
        finally:
            sys.path[:] = original_path


class TestPluginLoaderModuleLoading:
    def _create_plugin(self, tmp_path, name, code):
        plugin = tmp_path / name
        plugin.mkdir()
        (plugin / '__init__.py').write_text('')
        (plugin / 'myplugin.py').write_text(code)
        return plugin

    def test_loads_viewer_plugin(self, tmp_path):
        code = '''
from source.plugin_core.viewer.base import BaseViewerPlugin
class TestViewer(BaseViewerPlugin):
    NAME = 'test_viewer_load'
    EXTENSIONS = ('.test',)
    PRIORITY = 1
    def load_content(self, path):
        return None
'''
        self._create_plugin(tmp_path, 'testplugin', code)
        registries = {'viewer': PluginRegistry(), 'grid': PluginRegistry(), 'collector': PluginRegistry()}
        loader = PluginLoader(str(tmp_path), registries, skip_install=True)
        loaded = loader.load_all()
        assert 'testplugin' in loaded
        assert registries['viewer'].get('test_viewer_load') is not None

    def test_loads_grid_plugin(self, tmp_path):
        code = '''
from source.plugin_core.grid.base import BaseGridPlugin
class TestGrid(BaseGridPlugin):
    NAME = 'test_grid_load'
    EXTENSIONS = ('.test',)
    PRIORITY = 1
    def load(self, path, size=None):
        return None
'''
        self._create_plugin(tmp_path, 'gridplugin', code)
        registries = {'viewer': PluginRegistry(), 'grid': PluginRegistry(), 'collector': PluginRegistry()}
        loader = PluginLoader(str(tmp_path), registries, skip_install=True)
        loaded = loader.load_all()
        assert 'gridplugin' in loaded
        assert registries['grid'].get('test_grid_load') is not None

    def test_loads_collector_plugin(self, tmp_path):
        code = '''
from source.plugin_core.collector.base import BaseCollectorPlugin
class TestCollector(BaseCollectorPlugin):
    NAME = 'test_collector_load'
    EXTENSIONS = ('.test',)
    PRIORITY = 1
    def process(self, path, file_info):
        return None
'''
        self._create_plugin(tmp_path, 'collplugin', code)
        registries = {'viewer': PluginRegistry(), 'grid': PluginRegistry(), 'collector': PluginRegistry()}
        loader = PluginLoader(str(tmp_path), registries, skip_install=True)
        loaded = loader.load_all()
        assert 'collplugin' in loaded
        assert registries['collector'].get('test_collector_load') is not None

    def test_skips_underscore_files(self, tmp_path):
        plugin = tmp_path / 'myplugin'
        plugin.mkdir()
        (plugin / '__init__.py').write_text('')
        (plugin / '_internal.py').write_text('raise RuntimeError("should not be loaded")')
        registries = {'viewer': PluginRegistry(), 'grid': PluginRegistry(), 'collector': PluginRegistry()}
        loader = PluginLoader(str(tmp_path), registries, skip_install=True)
        loader.load_all()

    def test_bad_module_does_not_crash(self, tmp_path):
        plugin = tmp_path / 'badplugin'
        plugin.mkdir()
        (plugin / '__init__.py').write_text('')
        (plugin / 'broken.py').write_text('raise ImportError("intentional")')
        registries = {'viewer': PluginRegistry(), 'grid': PluginRegistry(), 'collector': PluginRegistry()}
        loader = PluginLoader(str(tmp_path), registries, skip_install=True)
        loaded = loader.load_all()
        assert loaded == []

    def test_install_failure_skips_plugin(self, tmp_path):
        plugin = tmp_path / 'failplugin'
        plugin.mkdir()
        (plugin / 'requirements.txt').write_text('nonexistent-pkg')
        (plugin / '__init__.py').write_text('')
        (plugin / 'myplugin.py').write_text('''
from source.plugin_core.viewer.base import BaseViewerPlugin
class X(BaseViewerPlugin):
    NAME = 'fail_viewer'
    EXTENSIONS = ()
    PRIORITY = 0
    def load_content(self, path):
        return None
''')
        registries = {'viewer': PluginRegistry(), 'grid': PluginRegistry(), 'collector': PluginRegistry()}
        loader = PluginLoader(str(tmp_path), registries, skip_install=False)
        with patch('source.plugin_core.loader._install_requirements', return_value=False):
            loaded = loader.load_all()
        assert 'failplugin' not in loaded
        assert registries['viewer'].get('fail_viewer') is None


class TestDiscoverPluginsAllTypes:
    def test_finds_grid_plugin(self):
        class TestGrid(BaseGridPlugin):
            NAME = 'disc_grid'
            EXTENSIONS = ('.test',)
            PRIORITY = 1
            def load(self, path, size=None):
                return None

        import types
        mod = types.ModuleType('fake_grid')
        mod.TestGrid = TestGrid
        found = _discover_plugins(mod)
        keys = [k for k, _ in found]
        assert 'grid' in keys

    def test_finds_collector_plugin(self):
        class TestColl(BaseCollectorPlugin):
            NAME = 'disc_coll'
            EXTENSIONS = ('.test',)
            PRIORITY = 1
            def process(self, path, file_info):
                return None

        import types
        mod = types.ModuleType('fake_coll')
        mod.TestColl = TestColl
        found = _discover_plugins(mod)
        keys = [k for k, _ in found]
        assert 'collector' in keys

    def test_finds_multiple_in_same_module(self):
        class TestViewer(BaseViewerPlugin):
            NAME = 'multi_v'
            EXTENSIONS = ()
            PRIORITY = 0
            def load_content(self, path):
                return None
        class TestGrid(BaseGridPlugin):
            NAME = 'multi_g'
            EXTENSIONS = ()
            PRIORITY = 0
            def load(self, path, size=None):
                return None

        import types
        mod = types.ModuleType('fake_multi')
        mod.TestViewer = TestViewer
        mod.TestGrid = TestGrid
        found = _discover_plugins(mod)
        keys = [k for k, _ in found]
        assert 'viewer' in keys
        assert 'grid' in keys


class TestRealPluginIntegration:
    def test_image_plugin_registers_all_types(self):
        from source.plugin_core.viewer.handler import viewer_handler
        from source.plugin_core.grid.handler import grid_handler
        from source.plugin_core.collector.handler import collector_handler
        assert viewer_handler.registry.get('image') is not None
        assert grid_handler.registry.get('image') is not None
        assert collector_handler.registry.get('exif') is not None

    def test_collector_info_has_extensions(self):
        from source.plugin_core.collector.handler import collector_handler
        info = collector_handler.info()
        assert len(info) > 0
        for name, extensions in info:
            assert isinstance(name, str)
            assert isinstance(extensions, tuple)

    def test_viewer_can_resolve_jpg(self):
        from source.plugin_core.viewer.handler import viewer_handler
        plugin = viewer_handler.registry.resolve('test.jpg')
        assert plugin is not None
        assert plugin.NAME == 'image'

    def test_grid_can_resolve_png(self):
        from source.plugin_core.grid.handler import grid_handler
        plugin = grid_handler.registry.resolve('test.png')
        assert plugin is not None
        assert plugin.NAME == 'image'

    def test_load_plugins_skip_install(self):
        result = load_plugins(skip_install=True)
        assert isinstance(result, list)


class TestSetupDllDirectory:

    def test_no_lib_dir(self, tmp_path):
        old_path = os.environ.get('PATH', '')
        _setup_dll_directory(str(tmp_path))
        assert os.environ.get('PATH', '') == old_path

    def test_adds_to_path_env(self, tmp_path):
        lib_dir = tmp_path / 'lib'
        lib_dir.mkdir()
        old_path = os.environ.get('PATH', '')
        try:
            _setup_dll_directory(str(tmp_path))
            assert str(lib_dir) in os.environ['PATH']
        finally:
            os.environ['PATH'] = old_path

    def test_idempotent(self, tmp_path):
        lib_dir = tmp_path / 'lib'
        lib_dir.mkdir()
        old_path = os.environ.get('PATH', '')
        try:
            _setup_dll_directory(str(tmp_path))
            path_after_first = os.environ['PATH']
            _setup_dll_directory(str(tmp_path))
            assert os.environ['PATH'] == path_after_first
        finally:
            os.environ['PATH'] = old_path

    @pytest.mark.skipif(sys.platform != 'win32', reason='Windows only')
    def test_calls_add_dll_directory(self, tmp_path):
        lib_dir = tmp_path / 'lib'
        lib_dir.mkdir()
        old_path = os.environ.get('PATH', '')
        try:
            with patch('source.plugin_core.loader.os.add_dll_directory') as mock_add:
                _setup_dll_directory(str(tmp_path))
                mock_add.assert_called_once_with(str(lib_dir))
        finally:
            os.environ['PATH'] = old_path

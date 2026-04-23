import os
import platform
import shutil
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from wafer.plugin import installer
from wafer.plugin.installer import (
    EmbeddedPython,
    RestartScope,
    InstallState,
    InstallResult,
    InstallerCancelled,
    restart_scope_of,
    restart_scope_from_plugins,
    resolve_install_state,
    _run_subprocess,
    _python_version,
    _ensure_python_version,
    _packages_dir,
    _stamps_dir,
    _extensions_dir_from_plugin,
    _stamp_path,
    install_requirements,
    write_post_install_stamp,
    needs_install,
    needs_post_install,
    needs_setup,
    has_post_install_hooks,
    install_extension,
    cleanup_legacy_dirs,
    _PACKAGES_DIR,
    _STAMPS_DIR,
    _PYTHON_VERSION_STAMP,
    _write_install_stamp,
    _stamp_version_matches,
)


class TestRunSubprocess:
    def test_success(self, tmp_path):
        script = tmp_path / "ok.py"
        script.write_text("import sys; sys.exit(0)")
        _run_subprocess([sys.executable, str(script)])

    def test_failure_raises(self, tmp_path):
        script = tmp_path / "fail.py"
        script.write_text('import sys; sys.stderr.write("err msg\\n"); sys.exit(1)')
        with pytest.raises(RuntimeError, match="err msg"):
            _run_subprocess([sys.executable, str(script)])

    def test_timeout_raises(self, tmp_path):
        script = tmp_path / "hang.py"
        script.write_text("import time; time.sleep(60)")
        with pytest.raises(TimeoutError):
            _run_subprocess([sys.executable, str(script)], timeout=1)

    def test_progress_callback(self, tmp_path):
        script = tmp_path / "slow.py"
        script.write_text("import time; time.sleep(0.3)")
        calls = []
        _run_subprocess([sys.executable, str(script)], on_progress=lambda: calls.append(1))
        assert len(calls) > 0

    def test_cancel_kills_process(self, tmp_path):
        script = tmp_path / "hang.py"
        script.write_text("import time; time.sleep(60)")
        with pytest.raises(InstallerCancelled):
            _run_subprocess([sys.executable, str(script)], is_cancelled=lambda: True)

    def test_no_timeout_by_default(self, tmp_path):
        script = tmp_path / "fast.py"
        script.write_text("import sys; sys.exit(0)")
        _run_subprocess([sys.executable, str(script)])


class TestPythonVersion:
    def test_returns_current_version(self):
        assert _python_version() == platform.python_version()


class TestEmbeddedPython:
    def test_uses_sys_executable(self):
        ep = EmbeddedPython()
        assert ep.exe_path == sys.executable

    def test_is_ready(self):
        ep = EmbeddedPython()
        assert ep.is_ready is True


class TestEnsurePythonVersion:
    def test_creates_version_stamp(self, tmp_path):
        _ensure_python_version(str(tmp_path))
        ver_file = tmp_path / _PACKAGES_DIR / _STAMPS_DIR / _PYTHON_VERSION_STAMP
        assert ver_file.exists()
        assert ver_file.read_text("utf-8").strip() == _python_version()

    def test_noop_when_version_matches(self, tmp_path):
        stamps = tmp_path / _PACKAGES_DIR / _STAMPS_DIR
        stamps.mkdir(parents=True)
        _write_install_stamp(str(stamps / _PYTHON_VERSION_STAMP))
        pkg = tmp_path / _PACKAGES_DIR / "numpy"
        pkg.mkdir()

        _ensure_python_version(str(tmp_path))
        assert pkg.exists()

    def test_purges_on_version_mismatch(self, tmp_path):
        stamps = tmp_path / _PACKAGES_DIR / _STAMPS_DIR
        stamps.mkdir(parents=True)
        (stamps / _PYTHON_VERSION_STAMP).write_text("3.10.9", "utf-8")
        pkg = tmp_path / _PACKAGES_DIR / "numpy"
        pkg.mkdir()

        _ensure_python_version(str(tmp_path))
        assert not pkg.exists()
        new_ver = tmp_path / _PACKAGES_DIR / _STAMPS_DIR / _PYTHON_VERSION_STAMP
        assert new_ver.exists()
        assert new_ver.read_text("utf-8").strip() == _python_version()


class TestPathHelpers:
    def test_packages_dir(self, tmp_path):
        assert _packages_dir(str(tmp_path)) == os.path.join(str(tmp_path), _PACKAGES_DIR)

    def test_stamps_dir(self, tmp_path):
        expected = os.path.join(str(tmp_path), _PACKAGES_DIR, _STAMPS_DIR)
        assert _stamps_dir(str(tmp_path)) == expected

    def test_extensions_dir_from_plugin(self, tmp_path):
        plugin = tmp_path / "image"
        plugin.mkdir()
        assert _extensions_dir_from_plugin(str(plugin)) == str(tmp_path)

    def test_stamp_path(self, tmp_path):
        plugin = tmp_path / "image"
        plugin.mkdir()
        result = _stamp_path(str(plugin), ".installed")
        expected = os.path.join(str(tmp_path), _PACKAGES_DIR, _STAMPS_DIR, "image.installed")
        assert result == expected


class TestInstallRequirements:
    def test_uses_merged_requirements(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "image"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("numpy==2.2.6\n")

        mock_ep = MagicMock()
        mock_ep.pip_install.return_value = None

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            success = install_requirements(str(plugin), str(ext_dir))

        assert success is True
        mock_ep.pip_install.assert_called_once()
        call_args = mock_ep.pip_install.call_args[0]
        assert _PACKAGES_DIR in call_args[1]
        stamp = ext_dir / _PACKAGES_DIR / _STAMPS_DIR / "image.installed"
        assert stamp.exists()

    def test_deferred_returns_true_with_deferred_flag(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("requests\n")

        mock_ep = MagicMock()
        mock_ep.pip_install.return_value = None

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            success = install_requirements(str(plugin), str(ext_dir))

        assert success is True

    def test_failure_returns_false(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("requests\n")

        mock_ep = MagicMock()
        mock_ep.pip_install.side_effect = RuntimeError("pip failed")

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            success = install_requirements(str(plugin), str(ext_dir))

        assert success is False

    def test_empty_merge_still_writes_stamp(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "empty"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("# no deps\n")

        success = install_requirements(str(plugin), str(ext_dir))

        assert success is True
        stamp = ext_dir / _PACKAGES_DIR / _STAMPS_DIR / "empty.installed"
        assert stamp.exists()


class TestStampVersionMatches:
    def test_correct_version(self, tmp_path):
        stamp = tmp_path / "stamp"
        stamp.write_text(_python_version(), "utf-8")
        assert _stamp_version_matches(str(stamp)) is True

    def test_wrong_version(self, tmp_path):
        stamp = tmp_path / "stamp"
        stamp.write_text("3.10.9", "utf-8")
        assert _stamp_version_matches(str(stamp)) is False

    def test_empty_stamp(self, tmp_path):
        stamp = tmp_path / "stamp"
        stamp.write_text("", "utf-8")
        assert _stamp_version_matches(str(stamp)) is False

    def test_missing_file(self, tmp_path):
        assert _stamp_version_matches(str(tmp_path / "nonexistent")) is False

    def test_legacy_stamp_touch_only(self, tmp_path):
        stamp = tmp_path / "stamp"
        stamp.touch()
        assert _stamp_version_matches(str(stamp)) is False


class TestWritePostInstallStamp:
    def test_creates_stamp_file(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        write_post_install_stamp(str(plugin))
        stamp = ext_dir / _PACKAGES_DIR / _STAMPS_DIR / "plugin.post_installed"
        assert stamp.exists()

    def test_idempotent(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        write_post_install_stamp(str(plugin))
        write_post_install_stamp(str(plugin))
        stamp = ext_dir / _PACKAGES_DIR / _STAMPS_DIR / "plugin.post_installed"
        assert stamp.exists()


class TestNeedsInstall:
    def test_no_requirements_returns_false(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        assert needs_install(str(plugin)) is False

    def test_no_stamp_returns_true(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("some-package\n")
        assert needs_install(str(plugin)) is True

    def test_stamp_newer_returns_false(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        req = plugin / "requirements.txt"
        req.write_text("some-package\n")
        os.utime(str(req), (0, 0))
        stamps = ext_dir / _PACKAGES_DIR / _STAMPS_DIR
        stamps.mkdir(parents=True)
        _write_install_stamp(str(stamps / _PYTHON_VERSION_STAMP))
        _write_install_stamp(str(stamps / "plugin.installed"))
        assert needs_install(str(plugin)) is False

    def test_stamp_older_returns_true(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("some-package\n")
        stamps = ext_dir / _PACKAGES_DIR / _STAMPS_DIR
        stamps.mkdir(parents=True)
        _write_install_stamp(str(stamps / _PYTHON_VERSION_STAMP))
        stamp = stamps / "plugin.installed"
        _write_install_stamp(str(stamp))
        os.utime(str(stamp), (0, 0))
        assert needs_install(str(plugin)) is True

    def test_version_mismatch_returns_true(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        req = plugin / "requirements.txt"
        req.write_text("some-package\n")
        os.utime(str(req), (0, 0))
        stamps = ext_dir / _PACKAGES_DIR / _STAMPS_DIR
        stamps.mkdir(parents=True)
        (stamps / _PYTHON_VERSION_STAMP).write_text("3.10.9", "utf-8")
        _write_install_stamp(str(stamps / "plugin.installed"))
        assert needs_install(str(plugin)) is True


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


class TestNeedsSetup:
    def test_true_when_pip_needed(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("pkg\n")
        assert needs_setup(str(plugin)) is True

    def test_true_when_post_install_needed(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("pkg\n")
        os.utime(str(plugin / "requirements.txt"), (0, 0))
        stamps = ext_dir / _PACKAGES_DIR / _STAMPS_DIR
        stamps.mkdir(parents=True)
        _write_install_stamp(str(stamps / _PYTHON_VERSION_STAMP))
        _write_install_stamp(str(stamps / "plugin.installed"))
        assert needs_setup(str(plugin)) is True

    def test_false_when_both_stamps_exist(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("pkg\n")
        os.utime(str(plugin / "requirements.txt"), (0, 0))
        stamps = ext_dir / _PACKAGES_DIR / _STAMPS_DIR
        stamps.mkdir(parents=True)
        _write_install_stamp(str(stamps / _PYTHON_VERSION_STAMP))
        _write_install_stamp(str(stamps / "plugin.installed"))
        (stamps / "plugin.post_installed").touch()
        assert needs_setup(str(plugin)) is False

    def test_false_when_no_requirements(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        assert needs_setup(str(plugin)) is False


class TestHasPostInstallHooks:
    def test_returns_false_for_base_plugin(self):
        from wafer.plugin.registry import PluginBase

        assert has_post_install_hooks([("grid", PluginBase)]) is False

    def test_returns_true_for_overridden_post_install(self):
        from wafer.plugin.registry import PluginBase

        class WithHook(PluginBase):
            NAME = "hooked"
            EXTENSIONS = (".h",)
            PRIORITY = 1

            @classmethod
            def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None):
                pass

        assert has_post_install_hooks([("grid", WithHook)]) is True

    def test_returns_false_when_all_inherit_default(self):
        from wafer.plugin.registry import PluginBase

        class Plain(PluginBase):
            NAME = "plain"
            EXTENSIONS = (".p",)
            PRIORITY = 1

        assert has_post_install_hooks([("grid", Plain)]) is False

    def test_mixed_returns_true(self):
        from wafer.plugin.registry import PluginBase

        class Plain(PluginBase):
            NAME = "plain"
            EXTENSIONS = (".p",)
            PRIORITY = 1

        class WithHook(PluginBase):
            NAME = "hooked"
            EXTENSIONS = (".h",)
            PRIORITY = 2

            @classmethod
            def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None):
                pass

        assert has_post_install_hooks([("a", Plain), ("b", WithHook)]) is True

    def test_skips_classes_without_post_install(self):
        class CommandGroup:
            NAME = "cmd"

        assert has_post_install_hooks([("commands", CommandGroup)]) is False


class TestInstallExtension:
    def test_skips_when_no_install_needed(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        (plugin / "__init__.py").write_text("")

        from wafer.plugin.registry import PluginBase

        class SimplePlugin(PluginBase):
            NAME = "simple"
            EXTENSIONS = (".s",)
            PRIORITY = 1

        with patch("wafer.plugin.installer.needs_install", return_value=False), patch("wafer.plugin.loader.PluginLoader.discover_extension", return_value=[("grid", SimplePlugin)]):
            result = install_extension(str(plugin), str(ext_dir))

        assert result.success is True
        assert result.post_install_ok is True
        assert len(result.plugins) == 1

    def test_install_failure_returns_false(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        with (
            patch("wafer.plugin.installer.needs_install", return_value=True),
            patch("wafer.plugin.installer.install_requirements", return_value=False),
        ):
            result = install_extension(str(plugin), str(ext_dir))

        assert result.success is False
        assert result.plugins == []

    def test_post_install_hook_called(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        from wafer.plugin.registry import PluginBase

        calls = []

        class HookPlugin(PluginBase):
            NAME = "hooked"
            EXTENSIONS = (".h",)
            PRIORITY = 1

            @classmethod
            def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None, on_log=None):
                calls.append(plugin_dir)

        with patch("wafer.plugin.installer.needs_install", return_value=False), patch("wafer.plugin.loader.PluginLoader.discover_extension", return_value=[("grid", HookPlugin)]):
            result = install_extension(str(plugin), str(ext_dir))

        assert result.success is True
        assert result.post_install_ok is True
        assert len(calls) == 1
        assert calls[0] == str(plugin)
        stamp = ext_dir / _PACKAGES_DIR / _STAMPS_DIR / "plugin.post_installed"
        assert stamp.exists()

    def test_post_install_not_called_when_absent(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        from wafer.plugin.registry import PluginBase

        class PlainPlugin(PluginBase):
            NAME = "plain"
            EXTENSIONS = (".p",)
            PRIORITY = 1

        with patch("wafer.plugin.installer.needs_install", return_value=False), patch("wafer.plugin.loader.PluginLoader.discover_extension", return_value=[("grid", PlainPlugin)]):
            result = install_extension(str(plugin), str(ext_dir))

        assert result.success is True
        assert result.post_install_ok is True
        stamp = ext_dir / _PACKAGES_DIR / _STAMPS_DIR / "plugin.post_installed"
        assert stamp.exists()

    def test_post_install_failure_returns_false(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        from wafer.plugin.registry import PluginBase

        class FailHook(PluginBase):
            NAME = "fail"
            EXTENSIONS = (".f",)
            PRIORITY = 1

            @classmethod
            def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None):
                raise RuntimeError("boom")

        with patch("wafer.plugin.installer.needs_install", return_value=False), patch("wafer.plugin.loader.PluginLoader.discover_extension", return_value=[("grid", FailHook)]):
            result = install_extension(str(plugin), str(ext_dir))

        assert result.success is True
        assert result.post_install_ok is False
        stamp = ext_dir / _PACKAGES_DIR / _STAMPS_DIR / "plugin.post_installed"
        assert not stamp.exists()

    def test_cancellation_during_install(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        cancelled = False

        def check():
            return cancelled

        with (
            patch("wafer.plugin.installer.needs_install", return_value=True),
            patch("wafer.plugin.installer.install_requirements", return_value=True),
        ):
            cancelled = True
            result = install_extension(
                str(plugin),
                str(ext_dir),
                is_cancelled=check,
            )

        assert result.success is False
        assert result.cancelled is True
        assert result.plugins == []

    def test_cancellation_during_post_install(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        from wafer.plugin.registry import PluginBase

        class CancelHook(PluginBase):
            NAME = "cancel_hook"
            EXTENSIONS = (".c",)
            PRIORITY = 1

            @classmethod
            def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None):
                raise InstallerCancelled("cancelled")

        with patch("wafer.plugin.installer.needs_install", return_value=False), patch("wafer.plugin.loader.PluginLoader.discover_extension", return_value=[("grid", CancelHook)]):
            result = install_extension(str(plugin), str(ext_dir), is_cancelled=lambda: True)

        assert result.success is False
        assert result.cancelled is True
        stamp = ext_dir / _PACKAGES_DIR / _STAMPS_DIR / "plugin.post_installed"
        assert not stamp.exists()

    def test_deferred_install_continues_discover_and_post_install(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        from wafer.plugin.registry import PluginBase

        class DeferredPlugin(PluginBase):
            NAME = "deferred"
            EXTENSIONS = (".d",)
            PRIORITY = 1

        with (
            patch("wafer.plugin.installer.needs_install", return_value=True),
            patch("wafer.plugin.installer.install_requirements", return_value=True),
            patch("wafer.plugin.loader.PluginLoader.discover_extension", return_value=[("grid", DeferredPlugin)]),
        ):
            result = install_extension(str(plugin), str(ext_dir))

        assert result.success is True
        assert result.post_install_ok is True
        assert len(result.plugins) == 1
        assert result.plugins[0][1] is DeferredPlugin


class TestRestartScope:
    def test_none_is_zero(self):
        assert RestartScope.NONE == RestartScope(0)

    def test_all_contains_viewer_and_tray(self):
        assert RestartScope.VIEWER in RestartScope.ALL
        assert RestartScope.TRAY in RestartScope.ALL

    def test_merge_viewer_tray_equals_all(self):
        assert (RestartScope.VIEWER | RestartScope.TRAY) == RestartScope.ALL

    def test_none_or_viewer(self):
        assert (RestartScope.NONE | RestartScope.VIEWER) == RestartScope.VIEWER


class TestRestartScopeOf:
    def test_viewer_scope(self):
        class ViewerPlugin:
            SCOPE = "viewer"
        assert restart_scope_of(ViewerPlugin) == RestartScope.VIEWER

    def test_tray_scope(self):
        class TrayPlugin:
            SCOPE = "tray"
        assert restart_scope_of(TrayPlugin) == RestartScope.TRAY

    def test_star_scope(self):
        class AllPlugin:
            SCOPE = "*"
        assert restart_scope_of(AllPlugin) == RestartScope.ALL

    def test_no_scope_defaults_to_viewer(self):
        class NoScopePlugin:
            pass
        assert restart_scope_of(NoScopePlugin) == RestartScope.VIEWER


class TestRestartScopeFromPlugins:
    def test_empty(self):
        assert restart_scope_from_plugins([]) == RestartScope.NONE

    def test_mixed(self):
        class V:
            SCOPE = "viewer"
        class T:
            SCOPE = "tray"
        scope = restart_scope_from_plugins([V, T])
        assert scope == RestartScope.ALL

    def test_single_tray(self):
        class T:
            SCOPE = "tray"
        assert restart_scope_from_plugins([T]) == RestartScope.TRAY


class TestInstallState:
    def test_values(self):
        assert InstallState.NO_DEPS.value == "no_deps"
        assert InstallState.NOT_INSTALLED.value == "not_installed"
        assert InstallState.NEEDS_POST_INSTALL.value == "needs_post_install"
        assert InstallState.INSTALLED.value == "installed"


class TestInstallResult:
    def test_defaults(self):
        r = InstallResult()
        assert r.success is False
        assert r.post_install_ok is True
        assert r.plugins == []


class TestResolveInstallState:
    def test_no_requirements_file(self, tmp_path):
        assert resolve_install_state(str(tmp_path)) == InstallState.NO_DEPS

    def test_needs_install(self, tmp_path, monkeypatch):
        (tmp_path / "requirements.txt").write_text("numpy==2.2.6\n")
        monkeypatch.setattr(installer, "needs_install", lambda d: True)
        assert resolve_install_state(str(tmp_path)) == InstallState.NOT_INSTALLED

    def test_needs_post_install(self, tmp_path, monkeypatch):
        (tmp_path / "requirements.txt").write_text("numpy==2.2.6\n")
        monkeypatch.setattr(installer, "needs_install", lambda d: False)
        monkeypatch.setattr(installer, "needs_post_install", lambda d: True)
        assert resolve_install_state(str(tmp_path)) == InstallState.NEEDS_POST_INSTALL

    def test_fully_installed(self, tmp_path, monkeypatch):
        (tmp_path / "requirements.txt").write_text("numpy==2.2.6\n")
        monkeypatch.setattr(installer, "needs_install", lambda d: False)
        monkeypatch.setattr(installer, "needs_post_install", lambda d: False)
        assert resolve_install_state(str(tmp_path)) == InstallState.INSTALLED



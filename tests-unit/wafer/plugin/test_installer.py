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
    _merge_requirements,
    _normalize_pkg_name,
    _parse_version_tuple,
    _collect_installed_extensions,
    _ensure_python_version,
    _packages_dir,
    _pending_dir,
    _stamps_dir,
    _extensions_dir_from_plugin,
    _stamp_path,
    _is_locked,
    _merge_or_defer,
    _merge_dir,
    _dist_info_base_name,
    _remove_stale_packages,
    apply_pending_packages,
    has_pending_packages,
    install_requirements,
    install_packages,
    write_post_install_stamp,
    needs_install,
    needs_post_install,
    needs_setup,
    has_post_install_hooks,
    install_extension,
    _PACKAGES_DIR,
    _STAMPS_DIR,
    _PENDING_DIR,
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


class TestNormalizePkgName:
    def test_lowercase(self):
        assert _normalize_pkg_name("Numpy") == "numpy"

    def test_underscore_to_dash(self):
        assert _normalize_pkg_name("opencv_python") == "opencv-python"

    def test_dots_to_dash(self):
        assert _normalize_pkg_name("a.b.c") == "a-b-c"

    def test_multiple_separators(self):
        assert _normalize_pkg_name("My__Pkg-Name") == "my-pkg-name"


class TestParseVersionTuple:
    def test_simple(self):
        assert _parse_version_tuple("1.2.3") == (1, 2, 3)

    def test_two_part(self):
        assert _parse_version_tuple("2.0") == (2, 0)

    def test_four_part(self):
        assert _parse_version_tuple("4.13.0.92") == (4, 13, 0, 92)


class TestMergeRequirements:
    def test_no_files(self):
        assert _merge_requirements([]) == []

    def test_single_file(self, tmp_path):
        req = tmp_path / "r.txt"
        req.write_text("numpy==2.2.6\npillow==12.2.0\n")
        result = _merge_requirements([str(req)])
        assert len(result) == 2
        assert "numpy==2.2.6" in result
        assert "pillow==12.2.0" in result

    def test_dedup_same_version(self, tmp_path):
        r1 = tmp_path / "a.txt"
        r1.write_text("numpy==2.2.6\n")
        r2 = tmp_path / "b.txt"
        r2.write_text("numpy==2.2.6\n")
        result = _merge_requirements([str(r1), str(r2)])
        assert len(result) == 1
        assert "numpy==2.2.6" in result

    def test_higher_version_wins(self, tmp_path):
        r1 = tmp_path / "a.txt"
        r1.write_text("py7zr==1.1.0\n")
        r2 = tmp_path / "b.txt"
        r2.write_text("py7zr==1.2.0\n")
        result = _merge_requirements([str(r1), str(r2)])
        assert len(result) == 1
        assert "py7zr==1.2.0" in result

    def test_four_part_version_comparison(self, tmp_path):
        r1 = tmp_path / "a.txt"
        r1.write_text("opencv-python==4.12.0.86\n")
        r2 = tmp_path / "b.txt"
        r2.write_text("opencv-python==4.13.0.92\n")
        result = _merge_requirements([str(r1), str(r2)])
        assert "opencv-python==4.13.0.92" in result

    def test_name_normalization(self, tmp_path):
        r1 = tmp_path / "a.txt"
        r1.write_text("opencv_python==4.12.0.86\n")
        r2 = tmp_path / "b.txt"
        r2.write_text("opencv-python==4.13.0.92\n")
        result = _merge_requirements([str(r1), str(r2)])
        assert len(result) == 1

    def test_skips_comments_and_blanks(self, tmp_path):
        req = tmp_path / "r.txt"
        req.write_text("# comment\n\nnumpy==2.2.6\n")
        result = _merge_requirements([str(req)])
        assert result == ["numpy==2.2.6"]

    def test_missing_file_ignored(self, tmp_path):
        r1 = tmp_path / "a.txt"
        r1.write_text("numpy==2.2.6\n")
        result = _merge_requirements([str(r1), str(tmp_path / "nonexistent.txt")])
        assert result == ["numpy==2.2.6"]

    def test_unpinned_requirement(self, tmp_path):
        req = tmp_path / "r.txt"
        req.write_text("requests>=2.0\n")
        result = _merge_requirements([str(req)])
        assert result == ["requests>=2.0"]

    def test_multiple_extensions_full_merge(self, tmp_path):
        r1 = tmp_path / "image.txt"
        r1.write_text("numpy==2.2.6\npillow==12.2.0\nopencv-python==4.13.0.92\n")
        r2 = tmp_path / "video.txt"
        r2.write_text("py7zr==1.1.0\npython-mpv==1.0.8\n")
        r3 = tmp_path / "ffmpeg.txt"
        r3.write_text("py7zr==1.1.0\n")
        r4 = tmp_path / "ai.txt"
        r4.write_text("numpy==2.2.6\npillow==12.2.0\nhuggingface_hub==1.10.1\n")
        result = _merge_requirements([str(r1), str(r2), str(r3), str(r4)])
        assert len(result) == 6


class TestCollectInstalledExtensions:
    def test_empty_dir(self, tmp_path):
        assert _collect_installed_extensions(str(tmp_path)) == []

    def test_no_stamps_dir(self, tmp_path):
        (tmp_path / _PACKAGES_DIR).mkdir()
        assert _collect_installed_extensions(str(tmp_path)) == []

    def test_collects_stamped_extensions(self, tmp_path):
        stamps = tmp_path / _PACKAGES_DIR / _STAMPS_DIR
        stamps.mkdir(parents=True)
        (stamps / "image.installed").write_text("3.11.9")
        (stamps / "video.installed").write_text("3.11.9")
        img_dir = tmp_path / "image"
        img_dir.mkdir()
        (img_dir / "requirements.txt").write_text("numpy\n")
        vid_dir = tmp_path / "video"
        vid_dir.mkdir()
        (vid_dir / "requirements.txt").write_text("mpv\n")

        result = _collect_installed_extensions(str(tmp_path))
        basenames = sorted(os.path.basename(os.path.dirname(r)) for r in result)
        assert basenames == ["image", "video"]

    def test_skips_stamped_without_requirements(self, tmp_path):
        stamps = tmp_path / _PACKAGES_DIR / _STAMPS_DIR
        stamps.mkdir(parents=True)
        (stamps / "exiftool.installed").write_text("3.11.9")
        ext = tmp_path / "exiftool"
        ext.mkdir()
        assert _collect_installed_extensions(str(tmp_path)) == []


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
        mock_ep.pip_install.return_value = True

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            success, deferred = install_requirements(str(plugin), str(ext_dir))

        assert success is True
        assert deferred is False
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
        mock_ep.pip_install.return_value = False

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            success, deferred = install_requirements(str(plugin), str(ext_dir))

        assert success is True
        assert deferred is True

    def test_failure_returns_false(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("requests\n")

        mock_ep = MagicMock()
        mock_ep.pip_install.side_effect = RuntimeError("pip failed")

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            success, deferred = install_requirements(str(plugin), str(ext_dir))

        assert success is False
        assert deferred is False

    def test_empty_merge_still_writes_stamp(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "empty"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("# no deps\n")

        success, deferred = install_requirements(str(plugin), str(ext_dir))

        assert success is True
        assert deferred is False
        stamp = ext_dir / _PACKAGES_DIR / _STAMPS_DIR / "empty.installed"
        assert stamp.exists()


class TestInstallPackages:
    def test_installs_to_shared_dir(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        mock_ep = MagicMock()
        mock_ep.exe_path = "/fake/python.exe"

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep), patch("wafer.plugin.installer._run_subprocess") as mock_run, patch("wafer.plugin.installer._merge_or_defer", return_value=True) as mock_merge:
            result = install_packages(str(plugin), ["onnxruntime-gpu"])

        assert result == (True, False)
        call_args = mock_run.call_args[0][0]
        assert "--target" in call_args
        assert "onnxruntime-gpu" in call_args
        mock_merge.assert_called_once()

    def test_deferred_returns_success_with_deferred(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        mock_ep = MagicMock()
        mock_ep.exe_path = "/fake/python.exe"

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep), patch("wafer.plugin.installer._run_subprocess"), patch("wafer.plugin.installer._merge_or_defer", return_value=False):
            result = install_packages(str(plugin), ["pkg"])

        assert result == (True, True)

    def test_failure_returns_false(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        with patch("wafer.plugin.installer._run_subprocess", side_effect=RuntimeError("pip failed")):
            result = install_packages(str(plugin), ["pkg"])

        assert result == (False, False)

    def test_multiple_packages(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        mock_ep = MagicMock()
        mock_ep.exe_path = "/fake/python.exe"

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep), patch("wafer.plugin.installer._run_subprocess") as mock_run:
            install_packages(str(plugin), ["pkg1", "pkg2"])

        call_args = mock_run.call_args[0][0]
        assert "pkg1" in call_args
        assert "pkg2" in call_args

    def test_extra_args_appended(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        mock_ep = MagicMock()
        mock_ep.exe_path = "/fake/python.exe"

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep), patch("wafer.plugin.installer._run_subprocess") as mock_run:
            install_packages(str(plugin), ["torch"], extra_args=["--index-url", "https://example.com/whl"])

        call_args = mock_run.call_args[0][0]
        assert "--index-url" in call_args
        assert "https://example.com/whl" in call_args

    def test_extra_args_none_no_effect(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        mock_ep = MagicMock()
        mock_ep.exe_path = "/fake/python.exe"

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep), patch("wafer.plugin.installer._run_subprocess") as mock_run:
            install_packages(str(plugin), ["pkg"])

        call_args = mock_run.call_args[0][0]
        assert "--index-url" not in call_args


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
            patch("wafer.plugin.installer.install_requirements", return_value=(False, False)),
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
            def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None):
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
            patch("wafer.plugin.installer.install_requirements", return_value=(True, False)),
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
            patch("wafer.plugin.installer.install_requirements", return_value=(True, True)),
            patch("wafer.plugin.loader.PluginLoader.discover_extension", return_value=[("grid", DeferredPlugin)]),
        ):
            result = install_extension(str(plugin), str(ext_dir))

        assert result.success is True
        assert result.post_install_ok is True
        assert result.deferred is True
        assert len(result.plugins) == 1
        assert result.plugins[0][1] is DeferredPlugin


class TestIsLocked:
    def test_unlocked_file(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("data")
        assert _is_locked(str(f)) is False

    def test_new_file_not_locked(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("data")
        assert _is_locked(str(f)) is False


class TestMergeOrDefer:
    def test_merge_when_no_locks(self, tmp_path):
        staging = tmp_path / "staging"
        target = tmp_path / "ext" / _PACKAGES_DIR
        ext_dir = tmp_path / "ext"
        staging.mkdir()
        target.mkdir(parents=True)
        (staging / "lib.py").write_text("content")

        result = _merge_or_defer(str(staging), str(target), str(ext_dir))
        assert result is True
        assert (target / "lib.py").read_text() == "content"
        assert not (ext_dir / _PENDING_DIR).exists()

    def test_defer_when_locked(self, tmp_path):
        staging = tmp_path / "staging"
        target = tmp_path / "ext" / _PACKAGES_DIR
        ext_dir = tmp_path / "ext"
        staging.mkdir()
        target.mkdir(parents=True)
        (staging / "lib.pyd").write_text("new")
        locked_file = target / "lib.pyd"
        locked_file.write_text("old")

        with patch("wafer.plugin.installer._is_locked", return_value=True):
            result = _merge_or_defer(str(staging), str(target), str(ext_dir))

        assert result is False
        pending = ext_dir / _PENDING_DIR
        assert pending.exists()
        assert (pending / "lib.pyd").read_text() == "new"
        assert locked_file.read_text() == "old"

    def test_defer_merges_into_existing_pending(self, tmp_path):
        staging = tmp_path / "staging"
        target = tmp_path / "ext" / _PACKAGES_DIR
        ext_dir = tmp_path / "ext"
        pending = ext_dir / _PENDING_DIR
        staging.mkdir()
        target.mkdir(parents=True)
        pending.mkdir(parents=True)
        (pending / "old_pkg.py").write_text("previous")
        (staging / "new_pkg.py").write_text("new")
        (target / "new_pkg.py").write_text("existing")

        with patch("wafer.plugin.installer._is_locked", return_value=True):
            result = _merge_or_defer(str(staging), str(target), str(ext_dir))

        assert result is False
        assert (pending / "old_pkg.py").read_text() == "previous"
        assert (pending / "new_pkg.py").read_text() == "new"

    def test_partial_merge_unlocked_copied_locked_deferred(self, tmp_path):
        staging = tmp_path / "staging"
        target = tmp_path / "ext" / _PACKAGES_DIR
        ext_dir = tmp_path / "ext"
        staging.mkdir()
        target.mkdir(parents=True)
        (staging / "ok.py").write_text("new_ok")
        (staging / "locked.pyd").write_text("new_locked")
        (target / "ok.py").write_text("old_ok")
        (target / "locked.pyd").write_text("old_locked")

        def fake_locked(path):
            return "locked.pyd" in path

        with patch("wafer.plugin.installer._is_locked", side_effect=fake_locked):
            result = _merge_or_defer(str(staging), str(target), str(ext_dir))

        assert result is False
        assert (target / "ok.py").read_text() == "new_ok"
        assert (target / "locked.pyd").read_text() == "old_locked"
        pending = ext_dir / _PENDING_DIR
        assert (pending / "locked.pyd").read_text() == "new_locked"
        assert not (pending / "ok.py").exists()

    def test_partial_merge_subdir_locked_file(self, tmp_path):
        staging = tmp_path / "staging"
        target = tmp_path / "ext" / _PACKAGES_DIR
        ext_dir = tmp_path / "ext"
        sub_staging = staging / "subpkg"
        sub_target = target / "subpkg"
        sub_staging.mkdir(parents=True)
        sub_target.mkdir(parents=True)
        (staging / "root.py").write_text("root_new")
        (sub_staging / "ok.py").write_text("sub_ok_new")
        (sub_staging / "mod.pyd").write_text("sub_new")
        (sub_target / "ok.py").write_text("sub_ok_old")
        (sub_target / "mod.pyd").write_text("sub_old")

        def fake_locked(path):
            return "mod.pyd" in path

        with patch("wafer.plugin.installer._is_locked", side_effect=fake_locked):
            with patch("wafer.plugin.installer._remove_stale_packages"):
                result = _merge_or_defer(str(staging), str(target), str(ext_dir))

        assert result is False
        assert (target / "root.py").read_text() == "root_new"
        assert (sub_target / "ok.py").read_text() == "sub_ok_new"
        assert (sub_target / "mod.pyd").read_text() == "sub_old"
        pending = ext_dir / _PENDING_DIR / "subpkg"
        assert (pending / "mod.pyd").read_text() == "sub_new"
        assert not (pending / "ok.py").exists()


class TestApplyPendingPackages:
    def test_applies_pending_to_packages(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        pending = ext_dir / _PENDING_DIR
        target = ext_dir / _PACKAGES_DIR
        pending.mkdir(parents=True)
        target.mkdir(parents=True)
        (pending / "new_lib.py").write_text("updated")
        (target / "old_lib.py").write_text("existing")

        result = apply_pending_packages(str(ext_dir))

        assert result is True
        assert (target / "new_lib.py").read_text() == "updated"
        assert (target / "old_lib.py").read_text() == "existing"
        assert not pending.exists()

    def test_no_pending_returns_false(self, tmp_path):
        result = apply_pending_packages(str(tmp_path))
        assert result is False

    def test_overwrites_existing_files(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        pending = ext_dir / _PENDING_DIR
        target = ext_dir / _PACKAGES_DIR
        pending.mkdir(parents=True)
        target.mkdir(parents=True)
        (pending / "lib.py").write_text("v2")
        (target / "lib.py").write_text("v1")

        result = apply_pending_packages(str(ext_dir))

        assert result is True
        assert (target / "lib.py").read_text() == "v2"

    def test_partial_apply_keeps_failed_in_pending(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        pending = ext_dir / _PENDING_DIR
        target = ext_dir / _PACKAGES_DIR
        pending.mkdir(parents=True)
        target.mkdir(parents=True)
        (pending / "ok.py").write_text("new_ok")
        (pending / "locked.pyd").write_text("new_locked")

        orig_copy2 = shutil.copy2

        def failing_copy2(src, dst, *args, **kwargs):
            if "locked.pyd" in str(dst):
                raise PermissionError("locked")
            return orig_copy2(src, dst, *args, **kwargs)

        with (
            patch("wafer.plugin.installer.shutil.copy2", side_effect=failing_copy2),
            patch("wafer.plugin.installer._PENDING_TIMEOUT", 0),
        ):
            result = apply_pending_packages(str(ext_dir))

        assert result is True
        assert (target / "ok.py").read_text() == "new_ok"
        assert not (target / "locked.pyd").exists()
        assert (pending / "locked.pyd").exists()
        assert not (pending / "ok.py").exists()

    def test_retry_succeeds_when_lock_released(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        pending = ext_dir / _PENDING_DIR
        target = ext_dir / _PACKAGES_DIR
        pending.mkdir(parents=True)
        target.mkdir(parents=True)
        (pending / "lib.pyd").write_text("new_content")
        (target / "lib.pyd").write_text("old_content")

        call_count = 0
        orig_copy2 = shutil.copy2

        def copy_fails_then_succeeds(src, dst, *args, **kwargs):
            nonlocal call_count
            if "lib.pyd" in str(dst):
                call_count += 1
                if call_count <= 2:
                    raise PermissionError("locked")
            return orig_copy2(src, dst, *args, **kwargs)

        with patch("wafer.plugin.installer.shutil.copy2", side_effect=copy_fails_then_succeeds):
            result = apply_pending_packages(str(ext_dir))

        assert result is True
        assert (target / "lib.pyd").read_text() == "new_content"
        assert not pending.exists()
        assert call_count == 3

    def test_merge_dir_locked_files_detected_as_failure(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        pending = ext_dir / _PENDING_DIR
        target = ext_dir / _PACKAGES_DIR
        pkg_pending = pending / "numpy"
        pkg_target = target / "numpy"
        pkg_pending.mkdir(parents=True)
        pkg_target.mkdir(parents=True)
        (pkg_pending / "ok.py").write_text("new")
        (pkg_pending / "locked.pyd").write_text("new_pyd")
        (pkg_target / "locked.pyd").write_text("old_pyd")

        with (
            patch("wafer.plugin.installer._is_locked", lambda p: "locked.pyd" in p),
            patch("wafer.plugin.installer._PENDING_TIMEOUT", 0),
        ):
            result = apply_pending_packages(str(ext_dir))

        assert not result
        assert (pkg_target / "ok.py").read_text() == "new"
        assert (pkg_target / "locked.pyd").read_text() == "old_pyd"
        assert (pkg_pending / "locked.pyd").exists()


class TestHasPendingPackages:
    def test_no_pending_dir(self, tmp_path):
        assert has_pending_packages(str(tmp_path)) is False

    def test_empty_pending_dir(self, tmp_path):
        (tmp_path / _PENDING_DIR).mkdir()
        assert has_pending_packages(str(tmp_path)) is False

    def test_pending_with_files(self, tmp_path):
        pending = tmp_path / _PENDING_DIR
        pending.mkdir()
        (pending / "pkg.py").write_text("data")
        assert has_pending_packages(str(tmp_path)) is True


class TestMergeDir:
    def test_basic_copy(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "a.txt").write_text("hello")
        _merge_dir(str(src), str(dst))
        assert (dst / "a.txt").read_text() == "hello"

    def test_overwrite_existing(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "a.txt").write_text("new")
        (dst / "a.txt").write_text("old")
        _merge_dir(str(src), str(dst))
        assert (dst / "a.txt").read_text() == "new"

    def test_nested_dirs(self, tmp_path):
        src = tmp_path / "src" / "sub"
        dst = tmp_path / "dst"
        src.mkdir(parents=True)
        dst.mkdir()
        (src / "f.txt").write_text("nested")
        _merge_dir(str(tmp_path / "src"), str(dst))
        assert (dst / "sub" / "f.txt").read_text() == "nested"

    def test_creates_dst_if_missing(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        (src / "a.txt").write_text("data")
        _merge_dir(str(src), str(dst))
        assert (dst / "a.txt").read_text() == "data"

    def test_locked_file_deferred_to_pending(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        pending = tmp_path / "pending"
        src.mkdir()
        dst.mkdir()
        (src / "ok.py").write_text("new_ok")
        (src / "locked.pyd").write_text("new_locked")
        (dst / "ok.py").write_text("old_ok")
        (dst / "locked.pyd").write_text("old_locked")

        def fake_locked(path):
            return "locked.pyd" in path

        with patch("wafer.plugin.installer._is_locked", side_effect=fake_locked):
            has_deferred = _merge_dir(str(src), str(dst), str(pending))

        assert has_deferred is True
        assert (dst / "ok.py").read_text() == "new_ok"
        assert (dst / "locked.pyd").read_text() == "old_locked"
        assert (pending / "locked.pyd").read_text() == "new_locked"

    def test_no_pending_dst_skips_deferred_copy(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "locked.pyd").write_text("new")
        (dst / "locked.pyd").write_text("old")

        def fake_locked(path):
            return "locked.pyd" in path

        with patch("wafer.plugin.installer._is_locked", side_effect=fake_locked):
            has_deferred = _merge_dir(str(src), str(dst))

        assert has_deferred is True
        assert (dst / "locked.pyd").read_text() == "old"


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
        assert r.deferred is False
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


class TestDistInfoBaseName:
    def test_simple_package(self):
        assert _dist_info_base_name("torch-2.6.0+cu124.dist-info") == "torch"

    def test_cpu_variant(self):
        assert _dist_info_base_name("torch-2.11.0+cpu.dist-info") == "torch"

    def test_multi_dash_name(self):
        assert _dist_info_base_name("opencv-python-4.13.0.92.dist-info") == "opencv-python"

    def test_underscore_normalized(self):
        assert _dist_info_base_name("huggingface_hub-1.10.1.dist-info") == "huggingface-hub"

    def test_non_dist_info_returns_none(self):
        assert _dist_info_base_name("torch") is None
        assert _dist_info_base_name("numpy.libs") is None

    def test_no_version_returns_none(self):
        assert _dist_info_base_name("torch.dist-info") is None


class TestRemoveStalePackages:
    def test_removes_old_dist_info(self, tmp_path):
        staging = tmp_path / "staging"
        target = tmp_path / "target"
        staging.mkdir()
        target.mkdir()
        (staging / "torch").mkdir()
        (staging / "torch-2.11.0+cpu.dist-info").mkdir()
        old_dist = target / "torch-2.6.0+cu124.dist-info"
        old_dist.mkdir()
        (old_dist / "METADATA").write_text("old")
        (target / "torch").mkdir()
        (target / "torch" / "old.dll").write_text("old dll")

        _remove_stale_packages(str(staging), str(target))

        assert not old_dist.exists()
        assert not (target / "torch").exists()

    def test_preserves_unrelated_packages(self, tmp_path):
        staging = tmp_path / "staging"
        target = tmp_path / "target"
        staging.mkdir()
        target.mkdir()
        (staging / "torch").mkdir()
        (staging / "torch-2.11.0+cpu.dist-info").mkdir()
        numpy_dir = target / "numpy"
        numpy_dir.mkdir()
        (numpy_dir / "core.py").write_text("data")
        numpy_dist = target / "numpy-2.2.6.dist-info"
        numpy_dist.mkdir()

        _remove_stale_packages(str(staging), str(target))

        assert numpy_dir.exists()
        assert numpy_dist.exists()

    def test_skips_hidden_dirs(self, tmp_path):
        staging = tmp_path / "staging"
        target = tmp_path / "target"
        staging.mkdir()
        target.mkdir()
        (staging / "torch").mkdir()
        stamps = target / ".stamps"
        stamps.mkdir()
        (stamps / "data").write_text("keep")

        _remove_stale_packages(str(staging), str(target))

        assert stamps.exists()

    def test_skips_locked_dirs(self, tmp_path):
        staging = tmp_path / "staging"
        target = tmp_path / "target"
        staging.mkdir()
        target.mkdir()
        (staging / "torch").mkdir()
        (staging / "torch" / "new.py").write_text("new")
        torch_dir = target / "torch"
        torch_dir.mkdir()
        (torch_dir / "locked.pyd").write_text("old")

        orig_rmtree = shutil.rmtree

        def fail_rmtree(path, ignore_errors=False, **kw):
            if "torch" in str(path) and str(path).startswith(str(target)):
                if ignore_errors:
                    return
                raise PermissionError("locked")
            return orig_rmtree(path, ignore_errors=ignore_errors, **kw)

        with patch("wafer.plugin.installer.shutil.rmtree", side_effect=fail_rmtree):
            _remove_stale_packages(str(staging), str(target))

        assert torch_dir.exists()
        assert (torch_dir / "locked.pyd").exists()

    def test_noop_when_no_target(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "torch").mkdir()
        _remove_stale_packages(str(staging), str(tmp_path / "nonexistent"))

    def test_multiple_old_dist_infos_removed(self, tmp_path):
        staging = tmp_path / "staging"
        target = tmp_path / "target"
        staging.mkdir()
        target.mkdir()
        (staging / "torch-2.11.0+cpu.dist-info").mkdir()
        old1 = target / "torch-2.6.0+cu124.dist-info"
        old2 = target / "torch-2.5.0+cu121.dist-info"
        old1.mkdir()
        old2.mkdir()

        _remove_stale_packages(str(staging), str(target))

        assert not old1.exists()
        assert not old2.exists()


class TestMergeOrDeferCleansMerge:
    def test_old_dist_info_removed_on_merge(self, tmp_path):
        staging = tmp_path / "staging"
        ext_dir = tmp_path / "ext"
        target = ext_dir / _PACKAGES_DIR
        staging.mkdir()
        target.mkdir(parents=True)

        (staging / "torch").mkdir()
        (staging / "torch" / "__init__.py").write_text("new")
        (staging / "torch-2.11.0+cpu.dist-info").mkdir()
        (staging / "torch-2.11.0+cpu.dist-info" / "RECORD").write_text("new")

        old_torch = target / "torch"
        old_torch.mkdir()
        (old_torch / "__init__.py").write_text("old")
        (old_torch / "cuda_stuff.dll").write_text("old cuda")
        old_dist = target / "torch-2.6.0+cu124.dist-info"
        old_dist.mkdir()
        (old_dist / "RECORD").write_text("old")

        result = _merge_or_defer(str(staging), str(target), str(ext_dir))

        assert result is True
        assert not old_dist.exists()
        assert (target / "torch-2.11.0+cpu.dist-info" / "RECORD").read_text() == "new"
        assert (target / "torch" / "__init__.py").read_text() == "new"
        assert not (target / "torch" / "cuda_stuff.dll").exists()

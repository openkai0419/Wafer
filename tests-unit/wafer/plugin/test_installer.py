import os
import platform
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from wafer.plugin import installer
from wafer.plugin.installer import (
    EmbeddedPython,
    _run_subprocess,
    _python_version,
    _merge_requirements,
    _normalize_pkg_name,
    _parse_version_tuple,
    _collect_installed_extensions,
    _ensure_python_version,
    _packages_dir,
    _stamps_dir,
    _extensions_dir_from_plugin,
    _stamp_path,
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

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            result = install_requirements(str(plugin), str(ext_dir))

        assert result is True
        mock_ep.pip_install.assert_called_once()
        call_args = mock_ep.pip_install.call_args[0]
        assert _PACKAGES_DIR in call_args[1]
        stamp = ext_dir / _PACKAGES_DIR / _STAMPS_DIR / "image.installed"
        assert stamp.exists()

    def test_failure_returns_false(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("requests\n")

        mock_ep = MagicMock()
        mock_ep.pip_install.side_effect = RuntimeError("pip failed")

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            result = install_requirements(str(plugin), str(ext_dir))

        assert result is False

    def test_empty_merge_still_writes_stamp(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "empty"
        plugin.mkdir(parents=True)
        (plugin / "requirements.txt").write_text("# no deps\n")

        result = install_requirements(str(plugin), str(ext_dir))

        assert result is True
        stamp = ext_dir / _PACKAGES_DIR / _STAMPS_DIR / "empty.installed"
        assert stamp.exists()


class TestInstallPackages:
    def test_installs_to_shared_dir(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        mock_ep = MagicMock()
        mock_ep.exe_path = "/fake/python.exe"

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep), patch("wafer.plugin.installer._run_subprocess") as mock_run, patch("wafer.plugin.installer._merge_dir") as mock_merge:
            result = install_packages(str(plugin), ["onnxruntime-gpu"])

        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "--target" in call_args
        assert "onnxruntime-gpu" in call_args
        mock_merge.assert_called_once()
        _, merge_dst = mock_merge.call_args[0]
        assert merge_dst == str(ext_dir / _PACKAGES_DIR)

    def test_failure_returns_false(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        with patch("wafer.plugin.installer._run_subprocess", side_effect=RuntimeError("pip failed")):
            result = install_packages(str(plugin), ["pkg"])

        assert result is False

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
            def post_install(cls, plugin_dir, on_progress=None):
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
            def post_install(cls, plugin_dir, on_progress=None):
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
            ok, post_ok, plugins = install_extension(str(plugin), str(ext_dir))

        assert ok is True
        assert post_ok is True
        assert len(plugins) == 1

    def test_install_failure_returns_false(self, tmp_path):
        ext_dir = tmp_path / "extensions"
        plugin = ext_dir / "plugin"
        plugin.mkdir(parents=True)

        with (
            patch("wafer.plugin.installer.needs_install", return_value=True),
            patch("wafer.plugin.installer.install_requirements", return_value=False),
        ):
            ok, post_ok, plugins = install_extension(str(plugin), str(ext_dir))

        assert ok is False
        assert plugins == []

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
            def post_install(cls, plugin_dir, on_progress=None):
                calls.append(plugin_dir)

        with patch("wafer.plugin.installer.needs_install", return_value=False), patch("wafer.plugin.loader.PluginLoader.discover_extension", return_value=[("grid", HookPlugin)]):
            ok, post_ok, plugins = install_extension(str(plugin), str(ext_dir))

        assert ok is True
        assert post_ok is True
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
            ok, post_ok, plugins = install_extension(str(plugin), str(ext_dir))

        assert ok is True
        assert post_ok is True
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
            def post_install(cls, plugin_dir, on_progress=None):
                raise RuntimeError("boom")

        with patch("wafer.plugin.installer.needs_install", return_value=False), patch("wafer.plugin.loader.PluginLoader.discover_extension", return_value=[("grid", FailHook)]):
            ok, post_ok, plugins = install_extension(str(plugin), str(ext_dir))

        assert ok is True
        assert post_ok is False
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
            ok, post_ok, plugins = install_extension(
                str(plugin),
                str(ext_dir),
                is_cancelled=check,
            )

        assert ok is False
        assert plugins == []

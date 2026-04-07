import hashlib
import os
import sys
import zipfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from wafer.plugin.installer import (
    EmbeddedPython,
    _validate_url,
    _sha256_file,
    _download_file,
    _run_subprocess,
    install_requirements,
    install_packages,
    shared_needs_install,
    install_shared_requirements,
    write_post_install_stamp,
    needs_install,
    needs_post_install,
    needs_setup,
    has_post_install_hooks,
    install_extension,
    _PACKAGES_DIR,
    _SHARED_DIR,
    _INSTALL_STAMP,
    _POST_INSTALL_STAMP,
)


class TestValidateUrl:
    def test_https_python_org_allowed(self):
        _validate_url("https://www.python.org/ftp/python/3.10.9/python-3.10.9-embed-amd64.zip")

    def test_https_bootstrap_pypa_allowed(self):
        _validate_url("https://bootstrap.pypa.io/get-pip.py")

    def test_http_rejected(self):
        with pytest.raises(ValueError, match="HTTPS"):
            _validate_url("http://www.python.org/ftp/python/3.10.9/test.zip")

    def test_untrusted_host_rejected(self):
        with pytest.raises(ValueError, match="Untrusted"):
            _validate_url("https://evil.example.com/python.zip")

    def test_ftp_scheme_rejected(self):
        with pytest.raises(ValueError, match="HTTPS"):
            _validate_url("ftp://www.python.org/test.zip")


class TestSha256File:
    def test_computes_correct_hash(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert _sha256_file(str(f)) == expected

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert _sha256_file(str(f)) == expected


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


class TestEmbeddedPython:
    def test_not_available_when_empty(self, tmp_path):
        ep = EmbeddedPython(str(tmp_path / "_python"))
        assert not ep.is_available
        assert not ep.has_pip
        assert not ep.is_ready

    def test_available_when_exe_exists(self, tmp_path):
        d = tmp_path / "_python"
        d.mkdir()
        (d / "python.exe").write_bytes(b"")
        ep = EmbeddedPython(str(d))
        assert ep.is_available
        assert not ep.has_pip

    def test_ready_when_exe_and_pip_exist(self, tmp_path):
        d = tmp_path / "_python"
        d.mkdir()
        (d / "python.exe").write_bytes(b"")
        scripts = d / "Scripts"
        scripts.mkdir()
        (scripts / "pip.exe").write_bytes(b"")
        ep = EmbeddedPython(str(d))
        assert ep.is_ready

    def test_ensure_ready_returns_true_when_already_ready(self, tmp_path):
        d = tmp_path / "_python"
        d.mkdir()
        (d / "python.exe").write_bytes(b"")
        scripts = d / "Scripts"
        scripts.mkdir()
        (scripts / "pip.exe").write_bytes(b"")
        ep = EmbeddedPython(str(d))
        assert ep.ensure_ready() is True

    def test_ensure_ready_unsupported_platform(self, tmp_path):
        ep = EmbeddedPython(str(tmp_path / "_python"))
        with patch("wafer.plugin.installer._platform_key", return_value=None):
            assert ep.ensure_ready() is False

    def test_download_and_extract(self, tmp_path):
        d = tmp_path / "_python"
        d.mkdir()

        zip_content_dir = tmp_path / "content"
        zip_content_dir.mkdir()
        (zip_content_dir / "python.exe").write_bytes(b"fake-exe")
        (zip_content_dir / "python310._pth").write_text("python310.zip\n.\n#import site\n", encoding="utf-8")

        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.write(str(zip_content_dir / "python.exe"), "python.exe")
            zf.write(str(zip_content_dir / "python310._pth"), "python310._pth")

        expected_hash = _sha256_file(str(zip_path))

        ep = EmbeddedPython(str(d))
        with patch("wafer.plugin.installer._download_file") as mock_dl:

            def fake_download(url, dest, **kw):
                import shutil

                shutil.copy2(str(zip_path), dest)
                return os.path.getsize(dest)

            mock_dl.side_effect = fake_download
            ep._download_and_extract(
                "https://www.python.org/ftp/python/3.10.9/test.zip",
                expected_hash,
            )

        assert (d / "python.exe").exists()
        assert (d / "python.exe").read_bytes() == b"fake-exe"

    def test_download_hash_mismatch_raises(self, tmp_path):
        d = tmp_path / "_python"
        d.mkdir()

        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.writestr("python.exe", b"fake")

        ep = EmbeddedPython(str(d))
        with patch("wafer.plugin.installer._download_file") as mock_dl:

            def fake_download(url, dest, **kw):
                import shutil

                shutil.copy2(str(zip_path), dest)
                return os.path.getsize(dest)

            mock_dl.side_effect = fake_download
            with pytest.raises(ValueError, match="SHA256 mismatch"):
                ep._download_and_extract(
                    "https://www.python.org/ftp/python/3.10.9/test.zip",
                    "deadbeef" * 8,
                )

    def test_path_traversal_rejected(self, tmp_path):
        d = tmp_path / "_python"
        d.mkdir()

        zip_path = tmp_path / "evil.zip"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.writestr("../escape.txt", "pwned")

        ep = EmbeddedPython(str(d))
        with patch("wafer.plugin.installer._download_file") as mock_dl:

            def fake_download(url, dest, **kw):
                import shutil

                shutil.copy2(str(zip_path), dest)
                return os.path.getsize(dest)

            mock_dl.side_effect = fake_download
            with pytest.raises(ValueError, match="Path traversal"):
                ep._download_and_extract(
                    "https://www.python.org/ftp/python/3.10.9/test.zip",
                    "",
                )

    def test_setup_pip_uncomments_site(self, tmp_path):
        d = tmp_path / "_python"
        d.mkdir()
        pth = d / "python310._pth"
        pth.write_text("python310.zip\n.\n#import site\n", encoding="utf-8")
        (d / "python.exe").write_bytes(b"")

        ep = EmbeddedPython(str(d))
        with patch("wafer.plugin.installer._download_file"):
            with patch("wafer.plugin.installer._run_subprocess"):
                ep._setup_pip()

        text = pth.read_text("utf-8")
        assert "#import site" not in text
        assert "import site" in text


class TestInstallRequirements:
    def test_uses_embedded_python(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        (plugin_dir / "requirements.txt").write_text("requests\n")

        mock_ep = MagicMock()
        mock_ep.ensure_ready.return_value = True

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            result = install_requirements(str(plugin_dir))

        assert result is True
        mock_ep.ensure_ready.assert_called_once()
        mock_ep.pip_install.assert_called_once()
        stamp = plugin_dir / _PACKAGES_DIR / _INSTALL_STAMP
        assert stamp.exists()

    def test_failure_returns_false(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        (plugin_dir / "requirements.txt").write_text("requests\n")

        mock_ep = MagicMock()
        mock_ep.ensure_ready.return_value = False

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            result = install_requirements(str(plugin_dir))

        assert result is False


class TestInstallPackages:
    def test_installs_to_vendor_dir(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()

        mock_ep = MagicMock()
        mock_ep.ensure_ready.return_value = True
        mock_ep.is_ready = True
        mock_ep.exe_path = "/fake/python.exe"

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep), patch("wafer.plugin.installer._run_subprocess") as mock_run:
            result = install_packages(str(plugin_dir), ["onnxruntime-gpu"])

        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "--target" in call_args
        vendor_idx = call_args.index("--target")
        assert _PACKAGES_DIR in call_args[vendor_idx + 1]
        assert "onnxruntime-gpu" in call_args

    def test_failure_returns_false(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()

        mock_ep = MagicMock()
        mock_ep.ensure_ready.return_value = False

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            result = install_packages(str(plugin_dir), ["pkg"])

        assert result is False

    def test_multiple_packages(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()

        mock_ep = MagicMock()
        mock_ep.ensure_ready.return_value = True
        mock_ep.is_ready = True
        mock_ep.exe_path = "/fake/python.exe"

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep), patch("wafer.plugin.installer._run_subprocess") as mock_run:
            install_packages(str(plugin_dir), ["pkg1", "pkg2"])

        call_args = mock_run.call_args[0][0]
        assert "pkg1" in call_args
        assert "pkg2" in call_args


class TestSharedNeedsInstall:
    def test_no_requirements_file(self, tmp_path):
        assert shared_needs_install(str(tmp_path)) is False

    def test_no_stamp(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("numpy\n")
        assert shared_needs_install(str(tmp_path)) is True

    def test_stamp_older_than_requirements(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("numpy\n")
        shared = tmp_path / _SHARED_DIR
        shared.mkdir()
        stamp = shared / _INSTALL_STAMP
        stamp.touch()
        os.utime(str(stamp), (0, 0))
        assert shared_needs_install(str(tmp_path)) is True

    def test_stamp_newer_than_requirements(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("numpy\n")
        os.utime(str(req), (0, 0))
        shared = tmp_path / _SHARED_DIR
        shared.mkdir()
        stamp = shared / _INSTALL_STAMP
        stamp.touch()
        assert shared_needs_install(str(tmp_path)) is False


class TestInstallSharedRequirements:
    def test_no_requirements_returns_true(self, tmp_path):
        assert install_shared_requirements(str(tmp_path)) is True

    def test_success_creates_stamp(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("numpy\n")
        mock_ep = MagicMock()
        mock_ep.ensure_ready.return_value = True

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            result = install_shared_requirements(str(tmp_path))

        assert result is True
        stamp = tmp_path / _SHARED_DIR / _INSTALL_STAMP
        assert stamp.exists()
        mock_ep.pip_install.assert_called_once()

    def test_embedded_not_ready_returns_false(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("numpy\n")
        mock_ep = MagicMock()
        mock_ep.ensure_ready.return_value = False

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            result = install_shared_requirements(str(tmp_path))

        assert result is False

    def test_pip_failure_returns_false(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("numpy\n")
        mock_ep = MagicMock()
        mock_ep.ensure_ready.return_value = True
        mock_ep.pip_install.side_effect = RuntimeError("pip failed")

        with patch("wafer.plugin.installer.EmbeddedPython", return_value=mock_ep):
            result = install_shared_requirements(str(tmp_path))

        assert result is False


class TestWritePostInstallStamp:
    def test_creates_stamp_file(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        write_post_install_stamp(str(plugin_dir))
        stamp = plugin_dir / _PACKAGES_DIR / _POST_INSTALL_STAMP
        assert stamp.exists()

    def test_creates_packages_dir_if_missing(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        assert not (plugin_dir / _PACKAGES_DIR).exists()
        write_post_install_stamp(str(plugin_dir))
        assert (plugin_dir / _PACKAGES_DIR).is_dir()

    def test_idempotent(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        write_post_install_stamp(str(plugin_dir))
        write_post_install_stamp(str(plugin_dir))
        stamp = plugin_dir / _PACKAGES_DIR / _POST_INSTALL_STAMP
        assert stamp.exists()


class TestNeedsInstall:
    def test_no_requirements_returns_false(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        assert needs_install(str(plugin_dir)) is False

    def test_no_stamp_returns_true(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        (plugin_dir / "requirements.txt").write_text("some-package\n")
        assert needs_install(str(plugin_dir)) is True

    def test_stamp_newer_returns_false(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        req = plugin_dir / "requirements.txt"
        req.write_text("some-package\n")
        os.utime(str(req), (0, 0))
        vendor = plugin_dir / _PACKAGES_DIR
        vendor.mkdir()
        (vendor / _INSTALL_STAMP).touch()
        assert needs_install(str(plugin_dir)) is False

    def test_stamp_older_returns_true(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        (plugin_dir / "requirements.txt").write_text("some-package\n")
        vendor = plugin_dir / _PACKAGES_DIR
        vendor.mkdir()
        stamp = vendor / _INSTALL_STAMP
        stamp.touch()
        os.utime(str(stamp), (0, 0))
        assert needs_install(str(plugin_dir)) is True


class TestNeedsPostInstall:
    def test_returns_true_when_no_stamp(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        (plugin_dir / "requirements.txt").write_text("some-pkg\n")
        assert needs_post_install(str(plugin_dir)) is True

    def test_returns_false_when_stamp_exists(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        vendor = plugin_dir / _PACKAGES_DIR
        vendor.mkdir(parents=True)
        (vendor / _POST_INSTALL_STAMP).touch()
        assert needs_post_install(str(plugin_dir)) is False

    def test_returns_false_when_no_requirements(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        assert needs_post_install(str(plugin_dir)) is False


class TestNeedsSetup:
    def test_true_when_pip_needed(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        (plugin_dir / "requirements.txt").write_text("pkg\n")
        assert needs_setup(str(plugin_dir)) is True

    def test_true_when_post_install_needed(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        vendor = plugin_dir / _PACKAGES_DIR
        vendor.mkdir(parents=True)
        (plugin_dir / "requirements.txt").write_text("pkg\n")
        (vendor / _INSTALL_STAMP).touch()
        assert needs_setup(str(plugin_dir)) is True

    def test_false_when_both_stamps_exist(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        vendor = plugin_dir / _PACKAGES_DIR
        vendor.mkdir(parents=True)
        (plugin_dir / "requirements.txt").write_text("pkg\n")
        (vendor / _INSTALL_STAMP).touch()
        (vendor / _POST_INSTALL_STAMP).touch()
        assert needs_setup(str(plugin_dir)) is False

    def test_false_when_no_requirements(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        assert needs_setup(str(plugin_dir)) is False


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
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("")
        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()

        from wafer.plugin.registry import PluginBase

        class SimplePlugin(PluginBase):
            NAME = "simple"
            EXTENSIONS = (".s",)
            PRIORITY = 1

        with patch("wafer.plugin.installer.needs_install", return_value=False), patch("wafer.plugin.loader.PluginLoader.discover_extension", return_value=[("grid", SimplePlugin)]):
            ok, post_ok, plugins = install_extension(str(plugin_dir), str(ext_dir))

        assert ok is True
        assert post_ok is True
        assert len(plugins) == 1

    def test_shared_failure_returns_false(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()

        with (
            patch("wafer.plugin.installer.needs_install", return_value=True),
            patch("wafer.plugin.installer.shared_needs_install", return_value=True),
            patch("wafer.plugin.installer.install_shared_requirements", return_value=False),
        ):
            ok, post_ok, plugins = install_extension(str(plugin_dir), str(ext_dir))

        assert ok is False
        assert plugins == []

    def test_extension_install_failure_returns_false(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()

        with (
            patch("wafer.plugin.installer.needs_install", return_value=True),
            patch("wafer.plugin.installer.shared_needs_install", return_value=False),
            patch("wafer.plugin.installer.install_requirements", return_value=False),
        ):
            ok, post_ok, plugins = install_extension(str(plugin_dir), str(ext_dir))

        assert ok is False
        assert plugins == []

    def test_post_install_hook_called(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()

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
            ok, post_ok, plugins = install_extension(str(plugin_dir), str(ext_dir))

        assert ok is True
        assert post_ok is True
        assert len(calls) == 1
        assert calls[0] == str(plugin_dir)
        stamp = plugin_dir / _PACKAGES_DIR / _POST_INSTALL_STAMP
        assert stamp.exists()

    def test_post_install_not_called_when_absent(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()

        from wafer.plugin.registry import PluginBase

        class PlainPlugin(PluginBase):
            NAME = "plain"
            EXTENSIONS = (".p",)
            PRIORITY = 1

        with patch("wafer.plugin.installer.needs_install", return_value=False), patch("wafer.plugin.loader.PluginLoader.discover_extension", return_value=[("grid", PlainPlugin)]):
            ok, post_ok, plugins = install_extension(str(plugin_dir), str(ext_dir))

        assert ok is True
        assert post_ok is True
        stamp = plugin_dir / _PACKAGES_DIR / _POST_INSTALL_STAMP
        assert stamp.exists()

    def test_post_install_failure_returns_false(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()

        from wafer.plugin.registry import PluginBase

        class FailHook(PluginBase):
            NAME = "fail"
            EXTENSIONS = (".f",)
            PRIORITY = 1

            @classmethod
            def post_install(cls, plugin_dir, on_progress=None):
                raise RuntimeError("boom")

        with patch("wafer.plugin.installer.needs_install", return_value=False), patch("wafer.plugin.loader.PluginLoader.discover_extension", return_value=[("grid", FailHook)]):
            ok, post_ok, plugins = install_extension(str(plugin_dir), str(ext_dir))

        assert ok is True
        assert post_ok is False
        stamp = plugin_dir / _PACKAGES_DIR / _POST_INSTALL_STAMP
        assert not stamp.exists()

    def test_cancellation_during_install(self, tmp_path):
        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()

        cancelled = False

        def check():
            return cancelled

        with (
            patch("wafer.plugin.installer.needs_install", return_value=True),
            patch("wafer.plugin.installer.shared_needs_install", return_value=False),
            patch("wafer.plugin.installer.install_requirements", return_value=True),
        ):
            cancelled = True
            ok, post_ok, plugins = install_extension(
                str(plugin_dir),
                str(ext_dir),
                is_cancelled=check,
            )

        assert ok is False
        assert plugins == []

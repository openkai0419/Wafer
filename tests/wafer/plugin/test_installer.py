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
    _PACKAGES_DIR,
    _INSTALL_STAMP,
)


class TestValidateUrl:

    def test_https_python_org_allowed(self):
        _validate_url('https://www.python.org/ftp/python/3.10.9/python-3.10.9-embed-amd64.zip')

    def test_https_bootstrap_pypa_allowed(self):
        _validate_url('https://bootstrap.pypa.io/get-pip.py')

    def test_http_rejected(self):
        with pytest.raises(ValueError, match='HTTPS'):
            _validate_url('http://www.python.org/ftp/python/3.10.9/test.zip')

    def test_untrusted_host_rejected(self):
        with pytest.raises(ValueError, match='Untrusted'):
            _validate_url('https://evil.example.com/python.zip')

    def test_ftp_scheme_rejected(self):
        with pytest.raises(ValueError, match='HTTPS'):
            _validate_url('ftp://www.python.org/test.zip')


class TestSha256File:

    def test_computes_correct_hash(self, tmp_path):
        f = tmp_path / 'test.bin'
        f.write_bytes(b'hello world')
        expected = hashlib.sha256(b'hello world').hexdigest()
        assert _sha256_file(str(f)) == expected

    def test_empty_file(self, tmp_path):
        f = tmp_path / 'empty.bin'
        f.write_bytes(b'')
        expected = hashlib.sha256(b'').hexdigest()
        assert _sha256_file(str(f)) == expected


class TestRunSubprocess:

    def test_success(self, tmp_path):
        script = tmp_path / 'ok.py'
        script.write_text('import sys; sys.exit(0)')
        _run_subprocess([sys.executable, str(script)])

    def test_failure_raises(self, tmp_path):
        script = tmp_path / 'fail.py'
        script.write_text('import sys; sys.stderr.write("err msg\\n"); sys.exit(1)')
        with pytest.raises(RuntimeError, match='err msg'):
            _run_subprocess([sys.executable, str(script)])

    def test_timeout_raises(self, tmp_path):
        script = tmp_path / 'hang.py'
        script.write_text('import time; time.sleep(60)')
        with pytest.raises(TimeoutError):
            _run_subprocess([sys.executable, str(script)], timeout=1)

    def test_progress_callback(self, tmp_path):
        script = tmp_path / 'slow.py'
        script.write_text('import time; time.sleep(0.3)')
        calls = []
        _run_subprocess([sys.executable, str(script)], on_progress=lambda: calls.append(1))
        assert len(calls) > 0


class TestEmbeddedPython:

    def test_not_available_when_empty(self, tmp_path):
        ep = EmbeddedPython(str(tmp_path / '_python'))
        assert not ep.is_available
        assert not ep.has_pip
        assert not ep.is_ready

    def test_available_when_exe_exists(self, tmp_path):
        d = tmp_path / '_python'
        d.mkdir()
        (d / 'python.exe').write_bytes(b'')
        ep = EmbeddedPython(str(d))
        assert ep.is_available
        assert not ep.has_pip

    def test_ready_when_exe_and_pip_exist(self, tmp_path):
        d = tmp_path / '_python'
        d.mkdir()
        (d / 'python.exe').write_bytes(b'')
        scripts = d / 'Scripts'
        scripts.mkdir()
        (scripts / 'pip.exe').write_bytes(b'')
        ep = EmbeddedPython(str(d))
        assert ep.is_ready

    def test_ensure_ready_returns_true_when_already_ready(self, tmp_path):
        d = tmp_path / '_python'
        d.mkdir()
        (d / 'python.exe').write_bytes(b'')
        scripts = d / 'Scripts'
        scripts.mkdir()
        (scripts / 'pip.exe').write_bytes(b'')
        ep = EmbeddedPython(str(d))
        assert ep.ensure_ready() is True

    def test_ensure_ready_unsupported_platform(self, tmp_path):
        ep = EmbeddedPython(str(tmp_path / '_python'))
        with patch('wafer.plugin.installer._platform_key', return_value=None):
            assert ep.ensure_ready() is False

    def test_download_and_extract(self, tmp_path):
        d = tmp_path / '_python'
        d.mkdir()

        zip_content_dir = tmp_path / 'content'
        zip_content_dir.mkdir()
        (zip_content_dir / 'python.exe').write_bytes(b'fake-exe')
        (zip_content_dir / 'python310._pth').write_text(
            'python310.zip\n.\n#import site\n', encoding='utf-8'
        )

        zip_path = tmp_path / 'test.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.write(str(zip_content_dir / 'python.exe'), 'python.exe')
            zf.write(str(zip_content_dir / 'python310._pth'), 'python310._pth')

        expected_hash = _sha256_file(str(zip_path))

        ep = EmbeddedPython(str(d))
        with patch('wafer.plugin.installer._download_file') as mock_dl:
            def fake_download(url, dest, **kw):
                import shutil
                shutil.copy2(str(zip_path), dest)
                return os.path.getsize(dest)
            mock_dl.side_effect = fake_download
            ep._download_and_extract(
                'https://www.python.org/ftp/python/3.10.9/test.zip',
                expected_hash,
            )

        assert (d / 'python.exe').exists()
        assert (d / 'python.exe').read_bytes() == b'fake-exe'

    def test_download_hash_mismatch_raises(self, tmp_path):
        d = tmp_path / '_python'
        d.mkdir()

        zip_path = tmp_path / 'test.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr('python.exe', b'fake')

        ep = EmbeddedPython(str(d))
        with patch('wafer.plugin.installer._download_file') as mock_dl:
            def fake_download(url, dest, **kw):
                import shutil
                shutil.copy2(str(zip_path), dest)
                return os.path.getsize(dest)
            mock_dl.side_effect = fake_download
            with pytest.raises(ValueError, match='SHA256 mismatch'):
                ep._download_and_extract(
                    'https://www.python.org/ftp/python/3.10.9/test.zip',
                    'deadbeef' * 8,
                )

    def test_path_traversal_rejected(self, tmp_path):
        d = tmp_path / '_python'
        d.mkdir()

        zip_path = tmp_path / 'evil.zip'
        with zipfile.ZipFile(str(zip_path), 'w') as zf:
            zf.writestr('../escape.txt', 'pwned')

        ep = EmbeddedPython(str(d))
        with patch('wafer.plugin.installer._download_file') as mock_dl:
            def fake_download(url, dest, **kw):
                import shutil
                shutil.copy2(str(zip_path), dest)
                return os.path.getsize(dest)
            mock_dl.side_effect = fake_download
            with pytest.raises(ValueError, match='Path traversal'):
                ep._download_and_extract(
                    'https://www.python.org/ftp/python/3.10.9/test.zip',
                    '',
                )

    def test_setup_pip_uncomments_site(self, tmp_path):
        d = tmp_path / '_python'
        d.mkdir()
        pth = d / 'python310._pth'
        pth.write_text('python310.zip\n.\n#import site\n', encoding='utf-8')
        (d / 'python.exe').write_bytes(b'')

        ep = EmbeddedPython(str(d))
        with patch('wafer.plugin.installer._download_file'):
            with patch('wafer.plugin.installer._run_subprocess'):
                ep._setup_pip()

        text = pth.read_text('utf-8')
        assert '#import site' not in text
        assert 'import site' in text


class TestInstallRequirements:

    def test_uses_embedded_python(self, tmp_path):
        plugin_dir = tmp_path / 'plugin'
        plugin_dir.mkdir()
        (plugin_dir / 'requirements.txt').write_text('requests\n')

        mock_ep = MagicMock()
        mock_ep.ensure_ready.return_value = True

        with patch('wafer.plugin.installer.EmbeddedPython', return_value=mock_ep):
            result = install_requirements(str(plugin_dir))

        assert result is True
        mock_ep.ensure_ready.assert_called_once()
        mock_ep.pip_install.assert_called_once()
        stamp = plugin_dir / _PACKAGES_DIR / _INSTALL_STAMP
        assert stamp.exists()

    def test_failure_returns_false(self, tmp_path):
        plugin_dir = tmp_path / 'plugin'
        plugin_dir.mkdir()
        (plugin_dir / 'requirements.txt').write_text('requests\n')

        mock_ep = MagicMock()
        mock_ep.ensure_ready.return_value = False

        with patch('wafer.plugin.installer.EmbeddedPython', return_value=mock_ep):
            result = install_requirements(str(plugin_dir))

        assert result is False

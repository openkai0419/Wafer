import json
import os
import subprocess
import sys
import urllib.error
import pytest
from unittest.mock import MagicMock, patch, call


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    lib_dir = str(tmp_path / 'lib')
    import extensions.video._downloader as dl
    monkeypatch.setattr(dl, '_LIB_DIR', lib_dir)
    monkeypatch.setattr(dl, '_DLL_PATH', os.path.join(lib_dir, 'libmpv-2.dll'))
    monkeypatch.setattr(dl, '_7ZR_PATH', os.path.join(lib_dir, '7zr.exe'))
    saved_path = os.environ.get('PATH', '')
    yield
    os.environ['PATH'] = saved_path


FAKE_RELEASE = {
    'assets': [
        {'name': 'mpv-dev-x86_64-20250201-git-abc1234.7z',
         'browser_download_url': 'https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20250201/mpv.7z'},
        {'name': 'mpv-dev-x86_64-v3-20250201-git-abc1234.7z',
         'browser_download_url': 'https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20250201/mpv-v3.7z'},
        {'name': 'mpv-x86_64-20250201-git-abc1234.7z',
         'browser_download_url': 'https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20250201/player.7z'},
    ]
}


class TestValidateUrl:

    def test_accepts_github_https(self):
        from extensions.video._downloader import _validate_url, _ALLOWED_HOSTS
        url = 'https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20250201/mpv.7z'
        assert _validate_url(url, _ALLOWED_HOSTS) == url

    def test_accepts_githubusercontent(self):
        from extensions.video._downloader import _validate_url, _ALLOWED_HOSTS
        url = 'https://objects.githubusercontent.com/some/path'
        assert _validate_url(url, _ALLOWED_HOSTS) == url

    def test_rejects_http(self):
        from extensions.video._downloader import _validate_url, _ALLOWED_HOSTS
        with pytest.raises(ValueError, match='Insecure URL scheme'):
            _validate_url('http://github.com/foo', _ALLOWED_HOSTS)

    def test_rejects_untrusted_host(self):
        from extensions.video._downloader import _validate_url, _ALLOWED_HOSTS
        with pytest.raises(ValueError, match='Untrusted host'):
            _validate_url('https://evil.com/mpv.7z', _ALLOWED_HOSTS)


class TestSafeDownload:

    def test_atomic_success(self, tmp_path):
        from extensions.video._downloader import _safe_download

        dest = str(tmp_path / 'file.bin')

        def fake_retrieve(url, d):
            open(d, 'w').close()

        with patch('urllib.request.urlretrieve', side_effect=fake_retrieve):
            _safe_download('https://example.com/f', dest)

        assert os.path.isfile(dest)
        assert not os.path.isfile(dest + '.tmp')

    def test_cleans_up_on_failure(self, tmp_path):
        from extensions.video._downloader import _safe_download

        dest = str(tmp_path / 'file.bin')

        def fake_retrieve(url, d):
            open(d, 'w').close()
            raise ConnectionError('network down')

        with pytest.raises(ConnectionError):
            with patch('urllib.request.urlretrieve', side_effect=fake_retrieve):
                _safe_download('https://example.com/f', dest)

        assert not os.path.isfile(dest)
        assert not os.path.isfile(dest + '.tmp')

    def test_validates_host_when_specified(self, tmp_path):
        from extensions.video._downloader import _safe_download

        dest = str(tmp_path / 'file.bin')
        with pytest.raises(ValueError, match='Untrusted host'):
            _safe_download('https://evil.com/f', dest, allowed_hosts=('github.com',))


class TestValidateArchivePath:

    def test_allows_normal_path(self):
        from extensions.video._downloader import _validate_archive_path
        _validate_archive_path('libmpv-2.dll', '/some/base')

    def test_allows_nested_path(self):
        from extensions.video._downloader import _validate_archive_path
        _validate_archive_path('subdir/libmpv-2.dll', '/some/base')

    def test_rejects_traversal(self):
        from extensions.video._downloader import _validate_archive_path
        with pytest.raises(ValueError, match='Path traversal'):
            _validate_archive_path('../../etc/passwd', '/some/base')

    def test_rejects_absolute_escape(self):
        from extensions.video._downloader import _validate_archive_path
        with pytest.raises(ValueError, match='Path traversal'):
            _validate_archive_path('../outside/file.dll', '/some/base')


class TestFindAssetUrl:

    def test_finds_non_v3_dev_asset(self):
        from extensions.video._downloader import _find_asset_url

        resp = MagicMock()
        resp.read.return_value = json.dumps(FAKE_RELEASE).encode()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=resp):
            url = _find_asset_url()

        assert 'mpv.7z' in url
        assert url.startswith('https://github.com/')

    def test_returns_none_when_no_match(self):
        from extensions.video._downloader import _find_asset_url

        release = {'assets': [{'name': 'unrelated.zip', 'browser_download_url': 'https://github.com/other'}]}
        resp = MagicMock()
        resp.read.return_value = json.dumps(release).encode()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=resp):
            url = _find_asset_url()

        assert url is None

    def test_rejects_untrusted_download_url(self):
        from extensions.video._downloader import _find_asset_url

        release = {'assets': [{
            'name': 'mpv-dev-x86_64-20250201-git-abc1234.7z',
            'browser_download_url': 'https://evil.com/mpv.7z',
        }]}
        resp = MagicMock()
        resp.read.return_value = json.dumps(release).encode()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=resp):
            with pytest.raises(ValueError, match='Untrusted host'):
                _find_asset_url()

    def test_rejects_oversized_response(self):
        from extensions.video._downloader import _find_asset_url, _MAX_API_RESPONSE

        resp = MagicMock()
        resp.read.return_value = b'x' * (_MAX_API_RESPONSE + 2)
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=resp):
            with pytest.raises(RuntimeError, match='too large'):
                _find_asset_url()


class TestExtractDll:

    def test_py7zr_extracts_flat_dll(self, tmp_path):
        from extensions.video._downloader import _extract_dll_py7zr, _DLL_NAME
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        dl._LIB_DIR = lib_dir
        dl._DLL_PATH = os.path.join(lib_dir, _DLL_NAME)

        fake_archive = str(tmp_path / 'test.7z')

        mock_7z = MagicMock()
        mock_file = MagicMock()
        mock_file.getnames.return_value = [_DLL_NAME]
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_7z.SevenZipFile.return_value = mock_file

        with patch.dict(sys.modules, {'py7zr': mock_7z}):
            os.makedirs(lib_dir, exist_ok=True)
            dll_path = os.path.join(lib_dir, _DLL_NAME)
            mock_file.extract.side_effect = lambda d, t: open(dll_path, 'w').close()
            _extract_dll_py7zr(fake_archive)

        mock_file.extract.assert_called_once_with(lib_dir, [_DLL_NAME])

    def test_py7zr_raises_when_dll_missing_in_archive(self, tmp_path):
        from extensions.video._downloader import _extract_dll_py7zr
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        dl._LIB_DIR = lib_dir

        mock_7z = MagicMock()
        mock_file = MagicMock()
        mock_file.getnames.return_value = ['include/mpv.h', 'mpv.def']
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_7z.SevenZipFile.return_value = mock_file

        with patch.dict(sys.modules, {'py7zr': mock_7z}):
            with pytest.raises(FileNotFoundError):
                _extract_dll_py7zr(str(tmp_path / 'test.7z'))

    def test_py7zr_rejects_path_traversal(self, tmp_path):
        from extensions.video._downloader import _extract_dll_py7zr
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        dl._LIB_DIR = lib_dir

        mock_7z = MagicMock()
        mock_file = MagicMock()
        mock_file.getnames.return_value = ['../../etc/passwd', 'libmpv-2.dll']
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_7z.SevenZipFile.return_value = mock_file

        with patch.dict(sys.modules, {'py7zr': mock_7z}):
            with pytest.raises(ValueError, match='Path traversal'):
                _extract_dll_py7zr(str(tmp_path / 'test.7z'))

    def test_fallback_py7zr_to_system_7z(self, tmp_path):
        from extensions.video._downloader import _extract_dll, _DLL_NAME
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        dl._LIB_DIR = lib_dir
        dl._DLL_PATH = os.path.join(lib_dir, _DLL_NAME)

        mock_7z_mod = MagicMock()
        mock_7z_mod.SevenZipFile.side_effect = Exception('BCJ2 unsupported')

        def fake_run(cmd, **kwargs):
            os.makedirs(lib_dir, exist_ok=True)
            open(os.path.join(lib_dir, _DLL_NAME), 'w').close()
            return subprocess.CompletedProcess(cmd, 0, '', '')

        with (
            patch.dict(sys.modules, {'py7zr': mock_7z_mod}),
            patch.object(dl, '_find_7z_exe', return_value='7z'),
            patch('subprocess.run', side_effect=fake_run),
        ):
            _extract_dll(str(tmp_path / 'archive.7z'))

        assert os.path.isfile(os.path.join(lib_dir, _DLL_NAME))

    def test_fallback_py7zr_to_downloaded_7zr(self, tmp_path):
        from extensions.video._downloader import _extract_dll, _DLL_NAME
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        dl._LIB_DIR = lib_dir
        dl._DLL_PATH = os.path.join(lib_dir, _DLL_NAME)
        zr_path = os.path.join(lib_dir, '7zr.exe')
        dl._7ZR_PATH = zr_path

        mock_7z_mod = MagicMock()
        mock_7z_mod.SevenZipFile.side_effect = Exception('BCJ2 unsupported')

        def fake_retrieve(url, dest):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, 'w').close()

        def fake_run(cmd, **kwargs):
            assert cmd[0] == zr_path
            os.makedirs(lib_dir, exist_ok=True)
            open(os.path.join(lib_dir, _DLL_NAME), 'w').close()
            return subprocess.CompletedProcess(cmd, 0, '', '')

        with (
            patch.dict(sys.modules, {'py7zr': mock_7z_mod}),
            patch.object(dl, '_find_7z_exe', return_value=None),
            patch('urllib.request.urlretrieve', side_effect=fake_retrieve),
            patch('subprocess.run', side_effect=fake_run),
        ):
            _extract_dll(str(tmp_path / 'archive.7z'))

        assert os.path.isfile(os.path.join(lib_dir, _DLL_NAME))


class TestRun7z:

    def test_extracts_dll_successfully(self, tmp_path):
        from extensions.video._downloader import _run_7z, _DLL_NAME
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        dl._LIB_DIR = lib_dir
        dl._DLL_PATH = os.path.join(lib_dir, _DLL_NAME)

        def fake_run(cmd, **kwargs):
            os.makedirs(lib_dir, exist_ok=True)
            open(os.path.join(lib_dir, _DLL_NAME), 'w').close()
            return subprocess.CompletedProcess(cmd, 0, '', '')

        with patch('subprocess.run', side_effect=fake_run):
            _run_7z('7z', str(tmp_path / 'archive.7z'))

        assert os.path.isfile(os.path.join(lib_dir, _DLL_NAME))

    def test_raises_on_nonzero_returncode(self, tmp_path):
        from extensions.video._downloader import _run_7z
        import extensions.video._downloader as dl

        dl._LIB_DIR = str(tmp_path / 'lib')

        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 2, '', 'error')):
            with pytest.raises(RuntimeError, match='7z extraction failed'):
                _run_7z('7z', str(tmp_path / 'archive.7z'))

    def test_raises_when_dll_not_extracted(self, tmp_path):
        from extensions.video._downloader import _run_7z
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        dl._LIB_DIR = lib_dir
        dl._DLL_PATH = os.path.join(lib_dir, 'libmpv-2.dll')

        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            with pytest.raises(FileNotFoundError):
                _run_7z('7z', str(tmp_path / 'archive.7z'))


class TestEnsure7zr:

    def test_returns_cached_if_exists(self, tmp_path):
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        os.makedirs(lib_dir, exist_ok=True)
        zr_path = os.path.join(lib_dir, '7zr.exe')
        open(zr_path, 'w').close()
        dl._7ZR_PATH = zr_path

        result = dl._ensure_7zr()
        assert result == zr_path

    def test_downloads_when_missing(self, tmp_path):
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        zr_path = os.path.join(lib_dir, '7zr.exe')
        dl._LIB_DIR = lib_dir
        dl._7ZR_PATH = zr_path

        def fake_retrieve(url, dest):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, 'w').close()

        with patch('urllib.request.urlretrieve', side_effect=fake_retrieve):
            result = dl._ensure_7zr()

        assert result == zr_path
        assert os.path.isfile(zr_path)

    def test_no_partial_file_on_failure(self, tmp_path):
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        zr_path = os.path.join(lib_dir, '7zr.exe')
        dl._LIB_DIR = lib_dir
        dl._7ZR_PATH = zr_path

        def fail_retrieve(url, dest):
            open(dest, 'w').close()
            raise ConnectionError('interrupted')

        with pytest.raises(ConnectionError):
            with patch('urllib.request.urlretrieve', side_effect=fail_retrieve):
                dl._ensure_7zr()

        assert not os.path.isfile(zr_path)
        assert not os.path.isfile(zr_path + '.tmp')


class TestFind7zExe:

    def test_finds_on_path(self):
        from extensions.video._downloader import _find_7z_exe
        with patch('shutil.which', return_value='7z'):
            assert _find_7z_exe() == '7z'

    def test_finds_in_program_files(self, tmp_path):
        from extensions.video._downloader import _find_7z_exe
        sevenzip_dir = tmp_path / '7-Zip'
        sevenzip_dir.mkdir()
        exe = sevenzip_dir / '7z.exe'
        exe.touch()
        with (
            patch('shutil.which', return_value=None),
            patch.dict(os.environ, {'ProgramFiles': str(tmp_path), 'ProgramFiles(x86)': ''}),
        ):
            assert _find_7z_exe() == str(exe)

    def test_returns_none_when_not_found(self):
        from extensions.video._downloader import _find_7z_exe
        with (
            patch('shutil.which', return_value=None),
            patch.dict(os.environ, {'ProgramFiles': '', 'ProgramFiles(x86)': ''}),
        ):
            assert _find_7z_exe() is None


class TestSetupDllPath:

    def test_adds_lib_dir_to_path(self, tmp_path):
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        dl._LIB_DIR = lib_dir
        os.environ['PATH'] = ''

        with patch('os.add_dll_directory') as mock_add:
            dl._setup_dll_path()

        assert lib_dir in os.environ['PATH'].split(os.pathsep)
        if sys.platform == 'win32':
            mock_add.assert_called_once_with(lib_dir)

    def test_skips_duplicate_path_entry(self, tmp_path):
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        dl._LIB_DIR = lib_dir
        os.environ['PATH'] = lib_dir

        with patch('os.add_dll_directory'):
            dl._setup_dll_path()

        entries = [e for e in os.environ['PATH'].split(os.pathsep) if e == lib_dir]
        assert len(entries) == 1

    def test_no_false_substring_match(self, tmp_path):
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        similar_dir = lib_dir + '2'
        dl._LIB_DIR = lib_dir
        os.environ['PATH'] = similar_dir

        with patch('os.add_dll_directory'):
            dl._setup_dll_path()

        entries = os.environ['PATH'].split(os.pathsep)
        assert lib_dir in entries
        assert similar_dir in entries


class TestEnsureMpvDll:

    def test_returns_true_when_dll_exists(self, tmp_path):
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        os.makedirs(lib_dir)
        dll_path = os.path.join(lib_dir, 'libmpv-2.dll')
        open(dll_path, 'w').close()

        dl._LIB_DIR = lib_dir
        dl._DLL_PATH = dll_path

        with patch('os.add_dll_directory'):
            assert dl.ensure_mpv_dll() is True

    def test_downloads_when_dll_missing(self, tmp_path):
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        dll_path = os.path.join(lib_dir, 'libmpv-2.dll')
        dl._LIB_DIR = lib_dir
        dl._DLL_PATH = dll_path

        with (
            patch.object(dl, '_find_asset_url', return_value='https://github.com/shinchiro/mpv.7z'),
            patch.object(dl, '_extract_dll') as mock_extract,
            patch.object(dl, '_safe_download') as mock_download,
            patch('os.add_dll_directory'),
        ):
            mock_extract.side_effect = lambda archive: (
                os.makedirs(lib_dir, exist_ok=True) or open(dll_path, 'w').close()
            )
            assert dl.ensure_mpv_dll() is True
            mock_download.assert_called_once()
            mock_extract.assert_called_once()

    def test_returns_false_when_no_asset_found(self, tmp_path):
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        dl._LIB_DIR = lib_dir
        dl._DLL_PATH = os.path.join(lib_dir, 'libmpv-2.dll')

        with patch.object(dl, '_find_asset_url', return_value=None):
            assert dl.ensure_mpv_dll() is False

    def test_returns_false_on_network_error(self, tmp_path):
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        dl._LIB_DIR = lib_dir
        dl._DLL_PATH = os.path.join(lib_dir, 'libmpv-2.dll')

        with patch.object(dl, '_find_asset_url', side_effect=urllib.error.URLError('timeout')):
            assert dl.ensure_mpv_dll() is False

    def test_returns_false_on_extraction_error(self, tmp_path):
        import extensions.video._downloader as dl

        lib_dir = str(tmp_path / 'lib')
        dl._LIB_DIR = lib_dir
        dl._DLL_PATH = os.path.join(lib_dir, 'libmpv-2.dll')

        with (
            patch.object(dl, '_find_asset_url', return_value='https://github.com/shinchiro/mpv.7z'),
            patch.object(dl, '_safe_download'),
            patch.object(dl, '_extract_dll', side_effect=FileNotFoundError('no dll')),
        ):
            assert dl.ensure_mpv_dll() is False

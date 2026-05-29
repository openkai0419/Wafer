import io
import json as _json
import os
import sys

import pytest
from unittest.mock import patch

import extensions.video._downloader as dl
from wafer.utils import downloader as common


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    lib_dir = str(tmp_path / "lib")
    monkeypatch.setattr(dl, "_LIB_DIR", lib_dir)
    monkeypatch.setattr(dl, "_DLL_PATH", os.path.join(lib_dir, "libmpv-2.dll"))
    saved_path = os.environ.get("PATH", "")
    yield
    os.environ["PATH"] = saved_path


class _Resp:
    def __init__(self, payload: bytes):
        self._buf = io.BytesIO(payload)

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestFindAsset:
    def _patch(self, monkeypatch, body: bytes):
        monkeypatch.setattr(common.urllib.request, "urlopen",
                            lambda req, timeout=None: _Resp(body))

    def test_returns_tuple_for_matching_asset(self, monkeypatch):
        digest = "sha256:" + ("a" * 64)
        payload = {
            "tag_name": "20260527",
            "assets": [
                {"name": "mpv-dev-x86_64-20260527-git-abcdef0.7z",
                 "browser_download_url": "https://github.com/shinchiro/mpv/releases/download/20260527/x.7z",
                 "digest": digest},
            ],
        }
        self._patch(monkeypatch, _json.dumps(payload).encode("utf-8"))
        url, sha, label = dl._find_asset()
        assert url.startswith("https://github.com/")
        assert sha == "a" * 64
        assert "20260527" in label

    def test_rejects_non_matching_asset_names(self, monkeypatch):
        payload = {
            "tag_name": "20260527",
            "assets": [
                {"name": "mpv-dev-aarch64-20260527-git-abcdef0.7z",
                 "browser_download_url": "https://github.com/x.7z",
                 "digest": "sha256:" + ("b" * 64)},
                {"name": "mpv-dev-x86_64-v3-20260527-git-abcdef0.7z",
                 "browser_download_url": "https://github.com/y.7z",
                 "digest": "sha256:" + ("c" * 64)},
            ],
        }
        self._patch(monkeypatch, _json.dumps(payload).encode("utf-8"))
        with pytest.raises(RuntimeError, match="asset not found"):
            dl._find_asset()

    def test_missing_digest_skipped(self, monkeypatch):
        payload = {
            "tag_name": "20260527",
            "assets": [
                {"name": "mpv-dev-x86_64-20260527-git-abcdef0.7z",
                 "browser_download_url": "https://github.com/x.7z",
                 "digest": ""},
            ],
        }
        self._patch(monkeypatch, _json.dumps(payload).encode("utf-8"))
        with pytest.raises(RuntimeError, match="asset not found"):
            dl._find_asset()


class TestSetupDllPath:
    def test_adds_lib_dir_to_path(self):
        lib_dir = dl._LIB_DIR
        os.environ["PATH"] = ""

        with patch("os.add_dll_directory") as mock_add:
            dl._setup_dll_path()

        assert lib_dir in os.environ["PATH"].split(os.pathsep)
        if sys.platform == "win32":
            mock_add.assert_called_once_with(lib_dir)

    def test_skips_duplicate_path_entry(self):
        lib_dir = dl._LIB_DIR
        os.environ["PATH"] = lib_dir

        with patch("os.add_dll_directory"):
            dl._setup_dll_path()

        entries = [e for e in os.environ["PATH"].split(os.pathsep) if e == lib_dir]
        assert len(entries) == 1

    def test_no_false_substring_match(self):
        lib_dir = dl._LIB_DIR
        similar_dir = lib_dir + "2"
        os.environ["PATH"] = similar_dir

        with patch("os.add_dll_directory"):
            dl._setup_dll_path()

        entries = os.environ["PATH"].split(os.pathsep)
        assert lib_dir in entries
        assert similar_dir in entries


class TestEnsureMpvDll:
    def test_returns_true_when_dll_exists(self):
        os.makedirs(dl._LIB_DIR, exist_ok=True)
        open(dl._DLL_PATH, "w").close()

        with patch("os.add_dll_directory"):
            assert dl.ensure_mpv_dll() is True

    def test_downloads_when_dll_missing(self):
        asset = ("https://github.com/shinchiro/mpv.7z", "a" * 64, "tag/name")
        with (
            patch.object(dl, "_find_asset", return_value=asset),
            patch.object(dl, "extract_7z_members") as mock_extract,
            patch.object(dl, "safe_download") as mock_download,
            patch("os.add_dll_directory"),
        ):
            mock_extract.side_effect = lambda archive, target, members: (
                os.makedirs(target, exist_ok=True) or open(dl._DLL_PATH, "w").close()
            )
            assert dl.ensure_mpv_dll() is True
            mock_download.assert_called_once()
            mock_extract.assert_called_once()

    def test_raises_when_download_fails(self):
        asset = ("https://github.com/shinchiro/mpv.7z", "a" * 64, "tag/name")
        with (
            patch.object(dl, "_find_asset", return_value=asset),
            patch.object(dl, "safe_download", side_effect=ConnectionError("offline")),
        ):
            with pytest.raises(RuntimeError, match="Failed to acquire mpv DLL"):
                dl.ensure_mpv_dll()

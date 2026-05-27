import io
import json as _json

import pytest

import extensions.video._downloader as dl
from wafer.utils import downloader as common


def _payload(name="mpv-dev-x86_64-20260527-git-abcdef0.7z",
             digest="sha256:" + ("a" * 64),
             url="https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20260527/x.7z",
             tag="20260527"):
    return {"tag_name": tag, "assets": [{"name": name, "digest": digest, "browser_download_url": url}]}


class _Resp:
    def __init__(self, payload: bytes):
        self._buf = io.BytesIO(payload)

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, payload: bytes):
    monkeypatch.setattr(common.urllib.request, "urlopen",
                        lambda req, timeout=None: _Resp(payload))


class TestFindAssetEdgeCases:
    def test_skips_invalid_digest_prefix(self, monkeypatch):
        _patch(monkeypatch, _json.dumps(_payload(digest="md5:" + ("b" * 32))).encode("utf-8"))
        with pytest.raises(RuntimeError, match="asset not found"):
            dl._find_asset()

    def test_skips_short_digest(self, monkeypatch):
        _patch(monkeypatch, _json.dumps(_payload(digest="sha256:" + ("a" * 32))).encode("utf-8"))
        with pytest.raises(RuntimeError, match="asset not found"):
            dl._find_asset()

    def test_oversized_response_rejected(self, monkeypatch):
        _patch(monkeypatch, b"x" * (dl._MAX_RELEASE_RESPONSE + 10))
        with pytest.raises(RuntimeError, match="too large"):
            dl._find_asset()

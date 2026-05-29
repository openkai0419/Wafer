import io

import pytest

import extensions.ffmpeg._downloader as dl
from wafer.utils import downloader as common


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


class TestFetchExpectedSha256:
    def test_parses_companion_file(self, monkeypatch):
        _patch(monkeypatch,
               b"23ad8969fbe701d44e6e7e2b97c5fae4a71224fc33a2560a9034e5110d029d15  ffmpeg-release-essentials.7z\n")
        assert dl._fetch_expected_sha256() == "23ad8969fbe701d44e6e7e2b97c5fae4a71224fc33a2560a9034e5110d029d15"

    def test_lowercases_hex(self, monkeypatch):
        _patch(monkeypatch, b"ABCDEF" + b"0" * 58 + b"\n")
        assert dl._fetch_expected_sha256() == "abcdef" + "0" * 58

    def test_rejects_garbage(self, monkeypatch):
        _patch(monkeypatch, b"<html>not a checksum</html>")
        with pytest.raises(RuntimeError, match="Unexpected .sha256 format"):
            dl._fetch_expected_sha256()

    def test_rejects_oversized(self, monkeypatch):
        _patch(monkeypatch, b"a" * (dl._MAX_SHA256_RESPONSE + 10))
        with pytest.raises(RuntimeError, match="too large"):
            dl._fetch_expected_sha256()

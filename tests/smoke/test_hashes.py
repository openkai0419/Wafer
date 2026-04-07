import os

from wafer.utils.hashes import fast_signature_hash, full_hash


def _write_file(path, content: bytes):
    with open(str(path), "wb") as f:
        f.write(content)


class TestFastSignatureHash:
    def test_same_file_same_hash(self, tmp_path):
        p = tmp_path / "a.bin"
        _write_file(p, b"hello world" * 100)
        h1 = fast_signature_hash(str(p))
        h2 = fast_signature_hash(str(p))
        assert h1 == h2
        assert isinstance(h1, str)
        assert len(h1) > 0

    def test_different_files_different_hash(self, tmp_path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        _write_file(a, b"content_a" * 200)
        _write_file(b, b"content_b" * 200)
        assert fast_signature_hash(str(a)) != fast_signature_hash(str(b))

    def test_empty_file_returns_z(self, tmp_path):
        p = tmp_path / "empty.bin"
        _write_file(p, b"")
        assert fast_signature_hash(str(p)) == "z"

    def test_nonexistent_file_returns_f(self, tmp_path):
        assert fast_signature_hash(str(tmp_path / "nonexistent.bin")) == "f"

    def test_small_file(self, tmp_path):
        p = tmp_path / "tiny.bin"
        _write_file(p, b"x")
        h = fast_signature_hash(str(p))
        assert isinstance(h, str)
        assert h not in ("", "z", "f")

    def test_with_explicit_size(self, tmp_path):
        p = tmp_path / "sized.bin"
        data = b"0123456789" * 100
        _write_file(p, data)
        h = fast_signature_hash(str(p), size=len(data))
        assert h == fast_signature_hash(str(p))


class TestFullHash:
    def test_same_file_same_hash(self, tmp_path):
        p = tmp_path / "f.bin"
        _write_file(p, b"deterministic content" * 50)
        h1 = full_hash(str(p))
        h2 = full_hash(str(p))
        assert h1 == h2

    def test_different_files_different_hash(self, tmp_path):
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        _write_file(a, b"alpha" * 100)
        _write_file(b, b"bravo" * 100)
        assert full_hash(str(a)) != full_hash(str(b))

    def test_nonexistent_returns_f(self, tmp_path):
        assert full_hash(str(tmp_path / "missing")) == "f"

    def test_full_hash_differs_from_fast(self, tmp_path):
        p = tmp_path / "data.bin"
        _write_file(p, os.urandom(10000))
        fast = fast_signature_hash(str(p))
        full = full_hash(str(p))
        assert fast != full

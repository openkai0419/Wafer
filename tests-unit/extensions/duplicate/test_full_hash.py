import pytest

from extensions.duplicate.full_hash import FULL_HASH_LENGTH, FullHashParser
from wafer.core.common.hashes import fast_signature_hash, full_hash


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"duplicate extension payload" * 100)
    return str(path)


def test_replaces_partial_signature_with_full_hash(image):
    parser = FullHashParser()
    result = parser.process(image, (1.0, 100, fast_signature_hash(image)), {})
    assert result.status is True
    assert result.update_hash == full_hash(image)
    assert len(result.update_hash) == FULL_HASH_LENGTH


def test_skips_when_already_full_hashed(image):
    parser = FullHashParser()
    result = parser.process(image, (1.0, 100, full_hash(image)), {})
    assert result.status is True
    assert result.update_hash is None


def test_runs_when_file_info_has_no_hash(image):
    parser = FullHashParser()
    result = parser.process(image, (1.0, 100), {})
    assert result.update_hash == full_hash(image)


def test_fails_on_unreadable_file(tmp_path):
    parser = FullHashParser()
    result = parser.process(str(tmp_path / "missing.bin"), (1.0, 100, "fast"), {})
    assert result.status is False
    assert result.update_hash is None

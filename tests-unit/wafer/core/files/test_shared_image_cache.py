import pytest

from wafer.core.files.shared_image_cache import IMAGE_CACHE_DEFAULT_MB, IMAGE_CACHE_KEY, image_cache_limit_mb, set_image_cache_limit, shared_image_cache
from wafer.core.store.settings import app_settings

MEBIBYTE = 1024 * 1024


@pytest.fixture(autouse=True)
def restore_limit():
    before = shared_image_cache().max_bytes
    yield
    app_settings.settings.remove(IMAGE_CACHE_KEY)
    shared_image_cache().max_bytes = before


def test_default_limit_is_512_mib():
    app_settings.settings.remove(IMAGE_CACHE_KEY)
    assert IMAGE_CACHE_DEFAULT_MB == 512 and image_cache_limit_mb() == 512


def test_setting_the_limit_saves_it_and_applies_it_at_once():
    set_image_cache_limit(256)
    assert image_cache_limit_mb() == 256
    assert shared_image_cache().max_bytes == 256 * MEBIBYTE


def test_saving_tells_the_other_viewers():
    sent = []
    app_settings.committed.connect(sent.append)
    try:
        set_image_cache_limit(128)
    finally:
        app_settings.committed.disconnect(sent.append)
    assert sent == [{IMAGE_CACHE_KEY: 128}]


def test_a_change_from_another_viewer_applies_the_limit(qapp):
    app_settings.apply_remote({IMAGE_CACHE_KEY: 1024})
    assert shared_image_cache().max_bytes == 1024 * MEBIBYTE


def test_other_keys_do_not_touch_the_limit(qapp):
    before = shared_image_cache().max_bytes
    app_settings.apply_remote({"viewer/some_other_key": 1})
    assert shared_image_cache().max_bytes == before

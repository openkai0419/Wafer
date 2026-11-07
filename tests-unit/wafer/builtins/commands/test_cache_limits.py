from unittest.mock import patch

import pytest

from wafer.builtins.commands import cache_limits
from wafer.builtins.commands.cache_limits import CacheLimitCommands, CacheLimitsDialog, TrayCacheLimitCommands
from wafer.core.db.cache_limit import db_cache_limit_mb, save_db_cache_limit
from wafer.core.files.shared_image_cache import IMAGE_CACHE_KEY, image_cache_limit_mb, shared_image_cache
from wafer.core.store.settings import app_settings


@pytest.fixture(autouse=True)
def restore():
    image_before = shared_image_cache().max_bytes
    db_before = db_cache_limit_mb()
    with patch.object(cache_limits, "open_viewer_count", return_value=4):
        yield
    app_settings.settings.remove(IMAGE_CACHE_KEY)
    shared_image_cache().max_bytes = image_before
    save_db_cache_limit(db_before)


def test_dialog_starts_from_the_saved_values(qtbot):
    save_db_cache_limit(1024)
    dialog = CacheLimitsDialog()
    qtbot.addWidget(dialog)
    assert dialog.image_limit.value() == image_cache_limit_mb()
    assert dialog.db_limit.value() == 1024


def test_saving_stores_both_limits(qtbot):
    dialog = CacheLimitsDialog()
    qtbot.addWidget(dialog)
    dialog.image_limit.setValue(1024)
    dialog.db_limit.setValue(256)
    dialog.save()
    assert image_cache_limit_mb() == 1024
    assert shared_image_cache().max_bytes == 1024 * 1024 * 1024
    assert db_cache_limit_mb() == 256


def test_image_total_multiplies_by_the_open_viewers(qtbot):
    dialog = CacheLimitsDialog()
    qtbot.addWidget(dialog)
    dialog.image_limit.setValue(1024)
    assert "4" in dialog.image_total.text() and "4096" in dialog.image_total.text()
    dialog.image_limit.setValue(512)
    assert "2048" in dialog.image_total.text()


def test_low_database_limit_warns_about_speed(qtbot):
    dialog = CacheLimitsDialog()
    qtbot.addWidget(dialog)
    dialog.db_limit.setValue(512)
    assert dialog.db_warning.isHidden()
    dialog.db_limit.setValue(128)
    assert not dialog.db_warning.isHidden()


def test_both_command_groups_are_discovered():
    from wafer.builtins.registration import _discover_builtins
    from wafer.plugin.loader import _get_registry_map

    found = {cls for _key, cls in _discover_builtins(cache_limits, _get_registry_map())}
    assert {CacheLimitCommands, TrayCacheLimitCommands} <= found


def test_command_is_offered_in_the_viewer_and_the_tray():
    assert CacheLimitCommands.SCOPE == "viewer" and TrayCacheLimitCommands.SCOPE == "tray"
    assert CacheLimitCommands.NAME == TrayCacheLimitCommands.NAME
    paths = [command.path for command in CacheLimitCommands.commands() if hasattr(command, "path")]
    assert paths == ["setting.cache_limits"]

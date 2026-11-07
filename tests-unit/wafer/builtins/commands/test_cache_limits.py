import pytest
from PySide6 import QtWidgets

from wafer.builtins.commands import cache_limits
from wafer.builtins.commands.cache_limits import CacheLimitsDialog, TrayCacheLimitCommands
from wafer.builtins.commands.setting import SettingCommands
from wafer.core.db.cache_limit import db_cache_limit_mb, save_db_cache_limit
from wafer.core.files.shared_image_cache import IMAGE_CACHE_KEY, image_cache_limit_mb, shared_image_cache
from wafer.core.store.settings import app_settings


@pytest.fixture(autouse=True)
def restore():
    image_before = shared_image_cache().max_bytes
    db_before = db_cache_limit_mb()
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


def test_dialog_does_not_count_the_open_viewers(qtbot):
    dialog = CacheLimitsDialog()
    qtbot.addWidget(dialog)
    texts = [label.text() for label in dialog.findChildren(QtWidgets.QLabel)]
    assert "Image cache (per Viewer)" in texts
    assert not any("Viewers open" in text for text in texts)


def test_each_limit_says_what_it_is_for(qtbot):
    dialog = CacheLimitsDialog()
    qtbot.addWidget(dialog)
    texts = [label.text() for label in dialog.findChildren(QtWidgets.QLabel)]
    assert "SQLite cache (per process)" in texts
    assert any("Thumbnails and full-size images" in text for text in texts)
    assert any("reading and writing the database" in text for text in texts)


def test_dialog_does_not_name_any_plugin(qtbot):
    dialog = CacheLimitsDialog()
    qtbot.addWidget(dialog)
    text = " ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))
    assert not any(name in text for name in ("Mapping", "Zip", "Animated", "GIF"))


def test_low_database_limit_warns_about_speed(qtbot):
    dialog = CacheLimitsDialog()
    qtbot.addWidget(dialog)
    dialog.db_limit.setValue(512)
    assert dialog.db_warning.isHidden()
    dialog.db_limit.setValue(128)
    assert not dialog.db_warning.isHidden()


def test_viewer_lists_it_right_under_the_thumbnail_size():
    paths = [item.path for item in SettingCommands.commands() if hasattr(item, "path")]
    assert paths.index("setting.cache_limits") == paths.index("setting.viewer_thumbnail_default_size") + 1


def test_tray_lists_it_directly_in_the_setting_menu():
    assert TrayCacheLimitCommands.SCOPE == "tray"
    assert TrayCacheLimitCommands.NAME == SettingCommands.NAME
    assert [item.path for item in TrayCacheLimitCommands.commands()] == ["setting.cache_limits"]


def test_tray_group_is_discovered():
    from wafer.builtins.registration import _discover_builtins
    from wafer.plugin.loader import _get_registry_map

    assert TrayCacheLimitCommands in {cls for _key, cls in _discover_builtins(cache_limits, _get_registry_map())}

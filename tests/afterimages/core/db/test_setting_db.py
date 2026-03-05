import py_compile

import pytest

from afterimages.core.db.setting_db import SettingDB

TEST_DB_NAME = None


@pytest.fixture
def setting_db(tmp_path):
    return SettingDB(str(tmp_path / 'settings.db'))


def test_compile():
    py_compile.compile('afterimages/core/db/setting_db.py')


def test_parent_folder_crud(setting_db):
    assert setting_db.add_parent_folder('C:/photos') is True
    assert setting_db.add_parent_folder('C:/photos') is False
    folders = setting_db.get_all_parent_folders()
    assert len(folders) == 1
    assert setting_db.remove_parent_folder('C:/photos') is True
    assert setting_db.remove_parent_folder('C:/photos') is False
    assert setting_db.get_all_parent_folders() == []


def test_ignore_folder_crud(setting_db):
    assert setting_db.add_ignore_folder('C:/temp') is True
    assert setting_db.add_ignore_folder('C:/temp') is False
    folders = setting_db.get_all_ignore_folders()
    assert len(folders) == 1
    assert setting_db.remove_ignore_folder('C:/temp') is True
    assert setting_db.remove_ignore_folder('C:/temp') is False
    assert setting_db.get_all_ignore_folders() == []


def test_sync_parent_folders(setting_db):
    setting_db.add_parent_folder('C:/old')
    result = setting_db.sync_parent_folders(['C:/new1', 'C:/new2'])
    assert 'C:/old' not in setting_db.get_all_parent_folders()
    assert len(setting_db.get_all_parent_folders()) == 2


def test_kv_store(setting_db):
    setting_db.set_setting('theme', 'dark')
    assert setting_db.get_setting('theme') == 'dark'
    setting_db.set_setting('theme', 'light')
    assert setting_db.get_setting('theme') == 'light'
    assert setting_db.get_setting('missing', 'default') == 'default'


def test_kv_store_complex_value(setting_db):
    setting_db.set_setting('config', {'a': 1, 'b': [2, 3]})
    result = setting_db.get_setting('config')
    assert result == {'a': 1, 'b': [2, 3]}


def test_invalid_folder_type_raises(setting_db):
    with pytest.raises(ValueError, match='Invalid folder type'):
        setting_db._sync_folders('invalid_table', [])
    with pytest.raises(ValueError, match='Invalid folder type'):
        setting_db._add_folder('malicious; DROP TABLE', 'C:/')
    with pytest.raises(ValueError, match='Invalid folder type'):
        setting_db._remove_folder('bad_table', 'C:/')
    with pytest.raises(ValueError, match='Invalid folder type'):
        setting_db._get_all_folders('bad_table')


def test_sync_folders_is_atomic(tmp_path):
    import sqlite3
    db = SettingDB(str(tmp_path / 'atomic.db'))
    db.add_parent_folder('C:/keep')
    db.add_parent_folder('C:/remove')

    db._sync_folders('parent_folders', ['C:/keep', 'C:/new'])

    folders = db.get_all_parent_folders()
    from afterimages.utils.paths import normalize_path
    norm = {normalize_path(f) for f in folders}
    assert normalize_path('C:/keep') in norm
    assert normalize_path('C:/new') in norm
    assert normalize_path('C:/remove') not in norm

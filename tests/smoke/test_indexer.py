import os
import sqlite3
import time

import pytest
from PIL import Image
from unittest.mock import patch

from wafer.core.ipc.broker import Broker
from wafer.core.db.setting_db import SettingDB
from wafer.utils.paths import normalize_path


def _create_test_image(path, width=200, height=150):
    Image.new('RGB', (width, height), color=(100, 150, 200)).save(str(path), format='JPEG')


def _poll_until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.1)
    return predicate()


def _db_source_count(db_path):
    try:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, check_same_thread=False)
        count = conn.execute('SELECT COUNT(*) FROM sources').fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


class TestSmokeIndexer:

    def test_indexer_scans_and_indexes(self, tmp_path):
        img_dir = tmp_path / 'photos'
        img_dir.mkdir()
        for name in ['a.jpg', 'b.jpg', 'c.png']:
            _create_test_image(img_dir / name)

        data_dir = tmp_path / 'data'
        data_dir.mkdir()
        setting_dir = tmp_path / 'dirs'
        setting_dir.mkdir()

        db_name = 'smoke_indexer'
        db_path = str(data_dir / f'{db_name}.db')
        s_path = str(setting_dir / f'{db_name}.db')

        sdb = SettingDB(s_path)
        sdb.add_parent_folder(normalize_path(str(img_dir)))

        broker = Broker()
        broker.start()
        try:
            with patch('wafer.app.indexer.main_indexer.data_db_path', return_value=db_path), \
                 patch('wafer.app.indexer.main_indexer.setting_db_path', return_value=s_path), \
                 patch('wafer.core.platform.process.AppProcess.new_main'):

                from wafer.app.indexer.main_indexer import IndexerProcess
                indexer = IndexerProcess(db_name)
                try:
                    indexer.start_watch()

                    assert _poll_until(
                        lambda: _db_source_count(db_path) >= 3,
                        timeout=15.0,
                    ), f'Expected >= 3 sources, got {_db_source_count(db_path)}'

                    conn = sqlite3.connect(
                        f'file:{db_path}?mode=ro', uri=True, check_same_thread=False,
                    )
                    rows = conn.execute('SELECT source FROM sources').fetchall()
                    conn.close()
                    indexed_paths = {r[0] for r in rows}
                    for name in ['a.jpg', 'b.jpg', 'c.png']:
                        expected = normalize_path(str(img_dir / name))
                        assert expected in indexed_paths, f'{expected} not in DB'
                finally:
                    indexer.stop()
        finally:
            broker.stop()

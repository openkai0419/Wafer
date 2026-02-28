import py_compile
import time

from source.app.indexer.writer import CollectionWriter, _WRITE_INTERVAL, _BATCH_SIZE
from source.app.indexer.progress_notifier import ProgressAggregator


class _StubNode:
    def __init__(self):
        self.sent = []

    def send(self, *a, **kw):
        self.sent.append(('send', a, kw))

    def send_coalesced(self, *a, **kw):
        self.sent.append(('send_coalesced', a, kw))


class _StubMsg:
    def __init__(self, payload):
        self.payload = payload


def test_compile():
    py_compile.compile('source/app/indexer/writer.py')


def test_handle_result_returns_true():
    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = CollectionWriter('dummy.db', progress)
    msg = _StubMsg({'collector': 'exif', 'results': [{'source': 'a', 'status': True}]})
    assert writer.handle_result(msg) is True


def test_handle_result_invalid_payload():
    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = CollectionWriter('dummy.db', progress)
    msg = _StubMsg('not_a_dict')
    assert writer.handle_result(msg) is True


def test_handle_result_queues_results():
    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = CollectionWriter('dummy.db', progress)
    results = [{'source': f'p{i}', 'status': True} for i in range(5)]
    msg = _StubMsg({'collector': 'exif', 'results': results})
    writer.handle_result(msg)
    assert writer._queue.qsize() == 5


def test_handle_result_queues_multi_path_results():
    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = CollectionWriter('dummy.db', progress)
    results = [
        {'source': 'archive.zip', 'path': 'archive.zip::a.png', 'status': True},
        {'source': 'archive.zip', 'path': 'archive.zip::b.png', 'status': True},
    ]
    msg = _StubMsg({'collector': 'zip', 'results': results})
    writer.handle_result(msg)
    assert writer._queue.qsize() == 2


def test_handle_result_does_not_add_maximum():
    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = CollectionWriter('dummy.db', progress)
    results = [{'source': f'p{i}', 'status': True} for i in range(3)]
    msg = _StubMsg({'collector': 'exif', 'results': results})
    writer.handle_result(msg)
    assert progress.maximum == 0


def test_write_batch_to_real_db(tmp_path):
    from source.core.db.file_db import FileDB

    db_path = tmp_path / 'test.db'
    db = FileDB(db_path)
    db.start()
    db.initialize_database()

    db.conn.execute("INSERT INTO hash_index (file_hash) VALUES ('h1')")
    db.conn.execute(
        "INSERT INTO sources (source, file_hash, size, modified, created, collected, status) "
        "VALUES ('src1', 'h1', 100, 1.0, 1.0, NULL, 'indexed')"
    )
    db.conn.execute(
        "INSERT INTO files (path, source, name, aspect_ratio) VALUES ('src1', 'src1', 'test', 1.0)"
    )
    db.conn.commit()
    db.close()

    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = CollectionWriter(str(db_path), progress)
    writer.start()

    results = [{
        'source': 'src1',
        'path': 'src1',
        'name': 'updated.png',
        'aspect': 1.5,
        'file_hash': 'h1',
        'meta_info': {'width': '100', 'height': '200'},
        'tags': {'rating': '5'},
        'status': True,
    }]
    msg = _StubMsg({'collector': 'exif', 'results': results})
    writer.handle_result(msg)

    time.sleep(_WRITE_INTERVAL + 1.0)
    writer.stop()

    db2 = FileDB(db_path)
    db2.start()
    row = db2.read_conn.execute("SELECT name, aspect_ratio FROM files WHERE path='src1'").fetchone()
    assert row[0] == 'updated.png'
    assert row[1] == 1.5

    meta = db2.read_conn.execute("SELECT value FROM meta_info WHERE path='src1' AND key='width'").fetchone()
    assert meta[0] == '100'

    cs = db2.read_conn.execute("SELECT status FROM collection_status WHERE source='src1' AND collector='exif'").fetchone()
    assert cs[0] == 'ok'
    db2.close()


def test_write_batch_multi_path_per_source(tmp_path):
    from source.core.db.file_db import FileDB

    db_path = tmp_path / 'test_multi.db'
    db = FileDB(db_path)
    db.start()
    db.initialize_database()

    db.conn.execute("INSERT INTO hash_index (file_hash) VALUES ('h_zip')")
    db.conn.execute(
        "INSERT INTO sources (source, file_hash, size, modified, created, collected, status) "
        "VALUES ('archive.zip', 'h_zip', 5000, 1.0, 1.0, NULL, 'indexed')"
    )
    db.conn.execute(
        "INSERT INTO files (path, source, name, aspect_ratio) VALUES ('archive.zip', 'archive.zip', 'archive.zip', NULL)"
    )
    db.conn.commit()
    db.close()

    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = CollectionWriter(str(db_path), progress)
    writer.start()

    results = [
        {
            'source': 'archive.zip',
            'path': 'archive.zip::img1.png',
            'name': 'img1.png',
            'aspect': 0.75,
            'meta_info': {'width': '300', 'height': '400'},
            'status': True,
        },
        {
            'source': 'archive.zip',
            'path': 'archive.zip::img2.jpg',
            'name': 'img2.jpg',
            'aspect': 1.5,
            'meta_info': {'width': '600', 'height': '400'},
            'status': True,
        },
    ]
    msg = _StubMsg({'collector': 'zip', 'results': results})
    writer.handle_result(msg)

    time.sleep(_WRITE_INTERVAL + 1.0)
    writer.stop()

    db2 = FileDB(db_path)
    db2.start()

    rows = db2.read_conn.execute(
        "SELECT path, name, aspect_ratio FROM files WHERE source='archive.zip' ORDER BY path"
    ).fetchall()
    paths = [r[0] for r in rows]
    assert 'archive.zip::img1.png' in paths
    assert 'archive.zip::img2.jpg' in paths

    meta1 = db2.read_conn.execute(
        "SELECT value FROM meta_info WHERE path='archive.zip::img1.png' AND key='width'"
    ).fetchone()
    assert meta1[0] == '300'

    meta2 = db2.read_conn.execute(
        "SELECT value FROM meta_info WHERE path='archive.zip::img2.jpg' AND key='width'"
    ).fetchone()
    assert meta2[0] == '600'

    src_status = db2.read_conn.execute(
        "SELECT status FROM sources WHERE source='archive.zip'"
    ).fetchone()
    assert src_status[0] == 'ok'

    cs = db2.read_conn.execute(
        "SELECT status FROM collection_status WHERE source='archive.zip' AND collector='zip'"
    ).fetchone()
    assert cs[0] == 'ok'
    db2.close()


def test_constants():
    assert _WRITE_INTERVAL > 0
    assert _BATCH_SIZE > 0


def test_write_batch_skips_none_meta_values(tmp_path):
    from source.core.db.file_db import FileDB

    db_path = tmp_path / 'test_none.db'
    db = FileDB(db_path)
    db.start()
    db.initialize_database()

    db.conn.execute("INSERT INTO hash_index (file_hash) VALUES ('h_n')")
    db.conn.execute(
        "INSERT INTO sources (source, file_hash, size, modified, created, collected, status) "
        "VALUES ('src_n', 'h_n', 100, 1.0, 1.0, NULL, 'indexed')"
    )
    db.conn.execute(
        "INSERT INTO files (path, source, name, aspect_ratio) VALUES ('src_n', 'src_n', 'test', 1.0)"
    )
    db.conn.commit()
    db.close()

    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = CollectionWriter(str(db_path), progress)
    writer.start()

    results = [{
        'source': 'src_n',
        'name': 'test.png',
        'aspect': 1.0,
        'file_hash': 'h_n',
        'meta_info': {'width': '100', 'empty_key': None, 'height': '200'},
        'tags': {'good': 'yes', 'bad': None},
        'status': True,
    }]
    msg = _StubMsg({'collector': 'exif', 'results': results})
    writer.handle_result(msg)

    time.sleep(_WRITE_INTERVAL + 1.0)
    writer.stop()

    db2 = FileDB(db_path)
    db2.start()

    meta_keys = db2.read_conn.execute(
        "SELECT key FROM meta_info WHERE path='src_n' ORDER BY key"
    ).fetchall()
    keys = [r[0] for r in meta_keys]
    assert 'width' in keys
    assert 'height' in keys
    assert 'empty_key' not in keys

    tag_keys = db2.read_conn.execute(
        "SELECT key FROM tags WHERE file_hash='h_n' ORDER BY key"
    ).fetchall()
    t_keys = [r[0] for r in tag_keys]
    assert 'good' in t_keys
    assert 'bad' not in t_keys
    db2.close()


def test_write_batch_bool_status_false(tmp_path):
    from source.core.db.file_db import FileDB

    db_path = tmp_path / 'test_fail.db'
    db = FileDB(db_path)
    db.start()
    db.initialize_database()

    db.conn.execute("INSERT INTO hash_index (file_hash) VALUES ('hf')")
    db.conn.execute(
        "INSERT INTO sources (source, file_hash, size, modified, created, collected, status) "
        "VALUES ('fail_src', 'hf', 50, 1.0, 1.0, NULL, 'indexed')"
    )
    db.conn.execute(
        "INSERT INTO files (path, source, name, aspect_ratio) VALUES ('fail_src', 'fail_src', 'x', 1.0)"
    )
    db.conn.commit()
    db.close()

    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = CollectionWriter(str(db_path), progress)
    writer.start()

    results = [{'source': 'fail_src', 'name': 'x.png', 'status': False}]
    msg = _StubMsg({'collector': 'exif', 'results': results})
    writer.handle_result(msg)

    time.sleep(_WRITE_INTERVAL + 1.0)
    writer.stop()

    db2 = FileDB(db_path)
    db2.start()
    src = db2.read_conn.execute("SELECT status FROM sources WHERE source='fail_src'").fetchone()
    assert src[0] == 'fail'
    cs = db2.read_conn.execute("SELECT status FROM collection_status WHERE source='fail_src' AND collector='exif'").fetchone()
    assert cs[0] == 'fail'
    db2.close()


def test_write_batch_minimal_result_status_only(tmp_path):
    from source.core.db.file_db import FileDB

    db_path = tmp_path / 'test_minimal.db'
    db = FileDB(db_path)
    db.start()
    db.initialize_database()

    db.conn.execute("INSERT INTO hash_index (file_hash) VALUES ('h_min')")
    db.conn.execute(
        "INSERT INTO sources (source, file_hash, size, modified, created, collected, status) "
        "VALUES ('min_src', 'h_min', 10, 1.0, 1.0, NULL, 'indexed')"
    )
    db.conn.execute(
        "INSERT INTO files (path, source, name, aspect_ratio) VALUES ('min_src', 'min_src', 'orig.png', 1.5)"
    )
    db.conn.commit()
    db.close()

    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = CollectionWriter(str(db_path), progress)
    writer.start()

    results = [{'source': 'min_src', 'status': True}]
    msg = _StubMsg({'collector': 'exif', 'results': results})
    writer.handle_result(msg)

    time.sleep(_WRITE_INTERVAL + 1.0)
    writer.stop()

    db2 = FileDB(db_path)
    db2.start()
    src = db2.read_conn.execute("SELECT status, collected FROM sources WHERE source='min_src'").fetchone()
    assert src[0] == 'ok'
    assert src[1] is not None

    f = db2.read_conn.execute("SELECT name, aspect_ratio FROM files WHERE source='min_src'").fetchone()
    assert f[0] == 'orig.png'
    assert f[1] == 1.5

    cs = db2.read_conn.execute("SELECT status FROM collection_status WHERE source='min_src' AND collector='exif'").fetchone()
    assert cs[0] == 'ok'
    db2.close()

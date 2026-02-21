import py_compile
import time

from source.image_indexer.writer import CollectionWriter, _WRITE_INTERVAL, _BATCH_SIZE
from source.image_indexer.progress_notifier import ProgressAggregator


class _StubNode:
    def __init__(self):
        self.sent = []

    def send(self, *a, **kw):
        self.sent.append(('send', a, kw))

    def send_latest(self, *a, **kw):
        self.sent.append(('send_latest', a, kw))


class _StubMsg:
    def __init__(self, payload):
        self.payload = payload


def test_compile():
    py_compile.compile('source/image_indexer/writer.py')


def test_handle_result_returns_true():
    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = CollectionWriter('dummy.db', progress)
    msg = _StubMsg({'collector': 'image', 'results': [{'source': 'a', 'info': {}, 'status': 'ok'}]})
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
    results = [{'source': f'p{i}', 'info': {}, 'status': 'ok'} for i in range(5)]
    msg = _StubMsg({'collector': 'image', 'results': results})
    writer.handle_result(msg)
    assert writer._queue.qsize() == 5


def test_handle_result_does_not_add_maximum():
    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = CollectionWriter('dummy.db', progress)
    results = [{'source': f'p{i}', 'info': {}, 'status': 'ok'} for i in range(3)]
    msg = _StubMsg({'collector': 'image', 'results': results})
    writer.handle_result(msg)
    assert progress.maximum == 0


def test_write_batch_to_real_db(tmp_path):
    from source.db.file_db import FileDB

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
    db.exit()

    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = CollectionWriter(str(db_path), progress)
    writer.start()

    results = [{
        'source': 'src1',
        'info': {'path': 'src1', 'name': 'updated.png', 'aspect': 1.5, 'file_hash': 'h1'},
        'meta_info': {'width': '100', 'height': '200'},
        'tags': {'rating': '5'},
        'status': 'ok',
    }]
    msg = _StubMsg({'collector': 'image', 'results': results})
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

    cs = db2.read_conn.execute("SELECT status FROM collection_status WHERE source='src1' AND collector='image'").fetchone()
    assert cs[0] == 'ok'
    db2.exit()


def test_constants():
    assert _WRITE_INTERVAL > 0
    assert _BATCH_SIZE > 0

import py_compile

from wayfer.app.indexer.dispatcher import CollectorDispatcher, _BATCH_SIZE, _DISPATCH_INTERVAL


def test_compile():
    py_compile.compile('wayfer/app/indexer/dispatcher.py')


def test_constants():
    assert _BATCH_SIZE > 0
    assert _DISPATCH_INTERVAL > 0


def test_init_with_defaults(tmp_path):
    from wayfer.core.db.indexer import FileIndexer
    idx = FileIndexer(tmp_path / 'test.db')
    dispatcher = CollectorDispatcher('testdb', idx)
    assert dispatcher._db_name == 'testdb'
    assert 'exif' in dispatcher._collectors


def test_init_with_custom_collectors(tmp_path):
    from wayfer.core.db.indexer import FileIndexer
    idx = FileIndexer(tmp_path / 'test.db')
    dispatcher = CollectorDispatcher('testdb', idx, collectors=['exif', 'video'])
    assert dispatcher._collectors == ['exif', 'video']


def test_request_dispatch_sets_event(tmp_path):
    from wayfer.core.db.indexer import FileIndexer
    idx = FileIndexer(tmp_path / 'test.db')
    dispatcher = CollectorDispatcher('testdb', idx)
    assert not dispatcher._dispatch_event.is_set()
    dispatcher.request_dispatch()
    assert dispatcher._dispatch_event.is_set()


def test_reset_stale_on_start(tmp_path):
    from wayfer.core.db.indexer import FileIndexer
    db_path = tmp_path / 'test.db'
    with FileIndexer(db_path) as idx:
        idx.initialize()
        idx.db.upsert_basic_sources(
            [('src1', 'h1', 100, 1.0, 1.0, 1.0, 'indexed')],
            [('src1', 'src1', 'f.jpg', 1.0)],
        )
        idx.db.insert_pending_collection(['src1'], ['exif'])
        idx.db.mark_dispatched(['src1'], 'exif')

    idx2 = FileIndexer(db_path)
    dispatcher = CollectorDispatcher('testdb', idx2)
    dispatcher._reset_stale()

    with idx2 as idx:
        pending = idx.db.get_pending_sources('exif')
        assert len(pending) == 1
        assert pending[0][0] == 'src1'

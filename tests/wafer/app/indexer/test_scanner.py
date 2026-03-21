import py_compile
from unittest.mock import MagicMock

from wafer.app.indexer.scanner import DirectoryScanner, _CHUNK, _get_stat


def test_compile():
    py_compile.compile('wafer/app/indexer/scanner.py')


def test_chunk_positive():
    assert _CHUNK > 0


def _make_scanner(tmp_path, collectors=None):
    from wafer.core.db.file_db import FileDB
    from wafer.app.indexer.db_writer import DatabaseWriter
    db_path = tmp_path / 'test.db'
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    db.close()
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    scanner = DirectoryScanner(db_path, scheduler, writer, progress, collectors)
    return scanner, scheduler, writer, progress


def test_set_exclude_paths(tmp_path):
    scanner, scheduler, _, _ = _make_scanner(tmp_path)
    scanner.start()
    scanner.set_exclude_paths(['/a/b', '/c/d'])
    assert len(scanner._exclude_paths) == 2
    assert scanner._exclude_paths == sorted(scanner._exclude_paths)
    scanner.stop()


def test_is_excluded(tmp_path):
    scanner, *_ = _make_scanner(tmp_path)
    scanner._exclude_paths = ['/a/b', '/c/d']
    assert scanner._is_excluded('/a/b')
    assert scanner._is_excluded('/a/b/sub/file.png')
    assert not scanner._is_excluded('/a/c')
    assert not scanner._is_excluded('/a')


def test_is_excluded_empty(tmp_path):
    scanner, *_ = _make_scanner(tmp_path)
    scanner._exclude_paths = []
    assert not scanner._is_excluded('/any/path')


def test_request_scan_queues(tmp_path):
    scanner, *_ = _make_scanner(tmp_path)
    scanner.request_scan(['/folder1'])
    assert len(scanner._request_queue) == 1
    assert scanner._request_queue[0] == ('rescan', ['/folder1'])


def test_request_update_queues(tmp_path):
    scanner, *_ = _make_scanner(tmp_path)
    scanner.request_update(['/file.png'])
    assert len(scanner._request_queue) == 1
    assert scanner._request_queue[0] == ('update', ['/file.png'])


def test_backfill_pending_queues(tmp_path):
    scanner, *_ = _make_scanner(tmp_path)
    scanner.backfill_pending()
    assert len(scanner._request_queue) == 1
    assert scanner._request_queue[0] == ('backfill', None)


def test_get_stat():
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as f:
        f.write(b'hello')
        path = f.name
    try:
        st = os.stat(path)
        mtime, size, ctime = _get_stat(st)
        assert size == 5
        assert mtime == st.st_mtime
    finally:
        os.unlink(path)


def test_start_stop(tmp_path):
    scanner, *_ = _make_scanner(tmp_path)
    scanner.start()
    assert scanner._read_conn is not None
    assert scanner._thread is not None
    scanner.stop()
    assert scanner._read_conn is None


def test_load_existing_sources_empty(tmp_path):
    scanner, *_ = _make_scanner(tmp_path)
    scanner.start()
    result = scanner._load_existing_sources()
    assert result == {}
    scanner.stop()


def test_full_scan_with_files(tmp_path):
    import time
    scanner, scheduler, _, progress = _make_scanner(tmp_path)
    scanner.start()
    scan_dir = tmp_path / 'data'
    scan_dir.mkdir()
    (scan_dir / 'a.txt').write_text('x')
    (scan_dir / 'b.txt').write_text('y')
    scanner._do_full_scan([str(scan_dir)])
    assert scheduler.submit.called
    ops = [c[0][0].name for c in scheduler.submit.call_args_list]
    assert 'upsert_sources' in ops
    scanner.stop()


def test_full_scan_empty_dir(tmp_path):
    scanner, scheduler, _, progress = _make_scanner(tmp_path)
    scanner.start()
    scan_dir = tmp_path / 'empty'
    scan_dir.mkdir()
    scanner._do_full_scan([str(scan_dir)])
    ops = [c[0][0].name for c in scheduler.submit.call_args_list]
    assert 'upsert_sources' not in ops
    scanner.stop()


def test_submit_pending_by_extension(tmp_path):
    scanner, scheduler, writer, _ = _make_scanner(tmp_path, collectors=[('exif', ['.jpg', '.png'])])
    scanner._submit_pending_by_extension(['/a.jpg', '/b.png', '/c.txt'])
    assert scheduler.submit.called
    task = scheduler.submit.call_args[0][0]
    assert task.name == 'insert_pending'
    assert task.cancel_token is None


def test_submit_pending_no_collectors(tmp_path):
    scanner, scheduler, _, _ = _make_scanner(tmp_path, collectors=[])
    scanner._submit_pending_by_extension(['/a.jpg'])
    assert not scheduler.submit.called


def test_backfill_tasks_not_cancellable(tmp_path):
    from wafer.core.db.file_db import FileDB
    from wafer.app.indexer.db_writer import DatabaseWriter
    db_path = tmp_path / 'test.db'
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    db.conn.execute("INSERT INTO hash_index (file_hash) VALUES ('h1')")
    db.conn.execute("INSERT INTO sources (source, file_hash, size, modified) VALUES ('/a.jpg', 'h1', 100, 1.0)")
    db.conn.commit()
    db.close()
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    scanner = DirectoryScanner(db_path, scheduler, writer, progress, [('image', ['.jpg'])])
    scanner.start()
    scanner._do_backfill()
    assert scheduler.submit.called
    for call in scheduler.submit.call_args_list:
        task = call[0][0]
        assert task.cancel_token is None
    scanner.stop()

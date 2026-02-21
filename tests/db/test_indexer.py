import py_compile

from pathlib import Path

from source.db.indexer import FileIndexer


def test_compile():
    py_compile.compile('source/db/indexer.py')


def test_fileindexer_exposes_db_path():
    idx = FileIndexer('x.db')
    assert idx.db_path == Path('x.db')


def test_fileindexer_default_empty_collectors():
    idx = FileIndexer('x.db')
    assert idx._collectors == []


def test_fileindexer_custom_collectors():
    collectors = [('image', ('.jpg', '.png'))]
    idx = FileIndexer('x.db', collectors=collectors)
    assert idx._collectors == collectors


def test_fileindexer_context_manager(tmp_path):
    db_path = tmp_path / 'test.db'
    with FileIndexer(db_path) as idx:
        idx.check_init()
        assert idx.db.conn is not None


def test_fileindexer_exclude_paths(tmp_path):
    idx = FileIndexer('x.db')
    a = str(tmp_path / 'a' / 'b')
    c = str(tmp_path / 'c' / 'd')
    from source.common.funcs import normalize_path
    na = normalize_path(a)
    nc = normalize_path(c)
    idx.set_exclude_paths([a, c])
    assert idx.is_path_excluded(na)
    assert idx.is_path_excluded(na + '/sub')
    assert not idx.is_path_excluded(normalize_path(str(tmp_path / 'a')))
    assert not idx.is_path_excluded(normalize_path(str(tmp_path / 'e' / 'f')))


def test_detect_diff():
    idx = FileIndexer('x.db')
    current = {'a': (1.0, 100), 'b': (2.0, 200), 'c': (3.0, 300)}
    previous = {'a': (1.0, 100), 'b': (1.0, 200), 'd': (4.0, 400)}
    added, removed = idx._detect_diff(current, previous)
    assert 'b' in added
    assert 'c' in added
    assert 'a' not in added
    assert 'd' in removed


def test_register_basic_info(tmp_path):
    import os
    img_dir = tmp_path / 'images'
    img_dir.mkdir()
    f1 = img_dir / 'test.bin'
    f1.write_bytes(b'x' * 1024)
    from source.common.funcs import normalize_path
    norm = normalize_path(str(f1))
    st = os.stat(str(f1))
    ctime = st.st_birthtime if hasattr(st, 'st_birthtime') else st.st_ctime
    file_info = {norm: (st.st_mtime, st.st_size, ctime)}

    collectors = [('image', ('.bin',))]
    db_path = tmp_path / 'test.db'
    with FileIndexer(db_path, collectors=collectors) as idx:
        idx.check_init()
        idx._register_basic_info([norm], file_info)

        prev = idx.db.load_previous()
        assert norm in prev

        row = idx.db.read_conn.execute("SELECT status FROM sources WHERE source=?", (norm,)).fetchone()
        assert row[0] == 'indexed'

        file_row = idx.db.read_conn.execute("SELECT aspect_ratio FROM files WHERE path=?", (norm,)).fetchone()
        assert file_row is not None

        pending = idx.db.get_pending_sources('image')
        assert len(pending) == 1
        assert pending[0][0] == norm


def test_register_basic_info_extension_filter(tmp_path):
    import os
    from source.common.funcs import normalize_path
    img_dir = tmp_path / 'mixed'
    img_dir.mkdir()
    jpg = img_dir / 'photo.jpg'
    jpg.write_bytes(b'j' * 512)
    txt = img_dir / 'notes.txt'
    txt.write_bytes(b't' * 512)

    jpg_norm = normalize_path(str(jpg))
    txt_norm = normalize_path(str(txt))

    file_info = {}
    for p, norm in [(jpg, jpg_norm), (txt, txt_norm)]:
        st = os.stat(str(p))
        ctime = st.st_birthtime if hasattr(st, 'st_birthtime') else st.st_ctime
        file_info[norm] = (st.st_mtime, st.st_size, ctime)

    collectors = [('image', ('.jpg', '.png'))]
    db_path = tmp_path / 'test.db'
    with FileIndexer(db_path, collectors=collectors) as idx:
        idx.check_init()
        idx._register_basic_info([jpg_norm, txt_norm], file_info)

        pending_image = idx.db.get_pending_sources('image')
        pending_paths = [r[0] for r in pending_image]
        assert jpg_norm in pending_paths
        assert txt_norm not in pending_paths

        files = idx.db.read_conn.execute("SELECT path FROM files").fetchall()
        assert len(files) == 2


def test_update_meta_and_image_only_registers(tmp_path):
    import os
    from source.common.funcs import normalize_path
    f1 = tmp_path / 'img.bin'
    f1.write_bytes(b'data' * 100)
    norm = normalize_path(str(f1))
    st = os.stat(str(f1))
    ctime = st.st_birthtime if hasattr(st, 'st_birthtime') else st.st_ctime
    file_info = {norm: (st.st_mtime, st.st_size, ctime)}

    collectors = [('image', ('.bin',))]
    db_path = tmp_path / 'test.db'
    with FileIndexer(db_path, collectors=collectors) as idx:
        idx.check_init()
        idx._update_meta_and_image([norm], file_info)

        pending = idx.db.get_pending_sources('image')
        assert len(pending) == 1
        assert pending[0][0] == norm


def test_reentrant_context_manager(tmp_path):
    db_path = tmp_path / 'test.db'
    idx = FileIndexer(db_path)
    with idx:
        idx.check_init()
        assert idx.db.conn is not None
        with idx:
            assert idx.db.conn is not None
        assert idx.db.conn is not None
    assert idx._ref_count == 0

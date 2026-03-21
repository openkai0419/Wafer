import py_compile

from pathlib import Path

from wafer.core.db.indexer import FileIndexer


def test_compile():
    py_compile.compile('wafer/core/db/indexer.py')


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
        idx.initialize()
        assert idx.db.conn is not None


def test_fileindexer_exclude_paths(tmp_path):
    idx = FileIndexer('x.db')
    a = str(tmp_path / 'a' / 'b')
    c = str(tmp_path / 'c' / 'd')
    from wafer.utils.paths import normalize_path
    na = normalize_path(a)
    nc = normalize_path(c)
    idx.set_exclude_paths([a, c])
    assert idx.is_path_excluded(na)
    assert idx.is_path_excluded(na + '/sub')
    assert not idx.is_path_excluded(normalize_path(str(tmp_path / 'a')))
    assert not idx.is_path_excluded(normalize_path(str(tmp_path / 'e' / 'f')))


def test_exclude_paths_uses_sorted_list():
    idx = FileIndexer('x.db')
    idx.set_exclude_paths(['/z/path', '/a/path', '/m/path'])
    assert isinstance(idx.exclude_paths, list)
    assert idx.exclude_paths == sorted(idx.exclude_paths)


def test_is_path_excluded_many_paths():
    from wafer.utils.paths import normalize_path
    idx = FileIndexer('x.db')
    raw_paths = [f'C:/root/dir{i:04d}' for i in range(500)]
    idx.set_exclude_paths(raw_paths)
    target = normalize_path('C:/root/dir0250')
    assert idx.is_path_excluded(target)
    assert idx.is_path_excluded(target + '/sub/file.jpg')
    assert not idx.is_path_excluded(normalize_path('C:/root/other'))
    assert not idx.is_path_excluded(target + 'x')


def test_is_path_excluded_empty():
    idx = FileIndexer('x.db')
    idx.set_exclude_paths([])
    assert not idx.is_path_excluded('C:/any/path')


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
    from wafer.utils.paths import normalize_path
    norm = normalize_path(str(f1))
    st = os.stat(str(f1))
    ctime = st.st_birthtime if hasattr(st, 'st_birthtime') else st.st_ctime
    file_info = {norm: (st.st_mtime, st.st_size, ctime)}

    collectors = [('exif', ('.bin',))]
    db_path = tmp_path / 'test.db'
    with FileIndexer(db_path, collectors=collectors) as idx:
        idx.initialize()
        idx._register_basic_info([norm], file_info)

        prev = idx.db.load_existing_sources()
        assert norm in prev

        file_row = idx.db.read_conn.execute("SELECT aspect_ratio FROM files WHERE path=?", (norm,)).fetchone()
        assert file_row is not None

        pending = idx.db.get_pending_sources('exif')
        assert len(pending) == 1
        assert pending[0][0] == norm


def test_register_basic_info_extension_filter(tmp_path):
    import os
    from wafer.utils.paths import normalize_path
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

    collectors = [('exif', ('.jpg', '.png'))]
    db_path = tmp_path / 'test.db'
    with FileIndexer(db_path, collectors=collectors) as idx:
        idx.initialize()
        idx._register_basic_info([jpg_norm, txt_norm], file_info)

        pending_image = idx.db.get_pending_sources('exif')
        pending_paths = [r[0] for r in pending_image]
        assert jpg_norm in pending_paths
        assert txt_norm not in pending_paths

        files = idx.db.read_conn.execute("SELECT path FROM files").fetchall()
        assert len(files) == 2


def test_register_basic_info_delegates_correctly(tmp_path):
    import os
    from wafer.utils.paths import normalize_path
    f1 = tmp_path / 'img.bin'
    f1.write_bytes(b'data' * 100)
    norm = normalize_path(str(f1))
    st = os.stat(str(f1))
    ctime = st.st_birthtime if hasattr(st, 'st_birthtime') else st.st_ctime
    file_info = {norm: (st.st_mtime, st.st_size, ctime)}

    collectors = [('exif', ('.bin',))]
    db_path = tmp_path / 'test.db'
    with FileIndexer(db_path, collectors=collectors) as idx:
        idx.initialize()
        idx._register_basic_info([norm], file_info)

        pending = idx.db.get_pending_sources('exif')
        assert len(pending) == 1
        assert pending[0][0] == norm


def test_reentrant_context_manager(tmp_path):
    db_path = tmp_path / 'test.db'
    idx = FileIndexer(db_path)
    with idx:
        idx.initialize()
        assert idx.db.conn is not None
        with idx:
            assert idx.db.conn is not None
        assert idx.db.conn is not None
    assert idx._ref_count == 0


def test_rename_by_pairs(tmp_path):
    import os
    from wafer.utils.paths import normalize_path

    src_dir = tmp_path / 'src'
    src_dir.mkdir()
    f1 = src_dir / 'a.bin'
    f1.write_bytes(b'x' * 1024)
    norm_old = normalize_path(str(f1))
    st = os.stat(str(f1))
    ctime = st.st_birthtime if hasattr(st, 'st_birthtime') else st.st_ctime
    file_info = {norm_old: (st.st_mtime, st.st_size, ctime)}

    db_path = tmp_path / 'test.db'
    with FileIndexer(db_path) as idx:
        idx.initialize()
        idx._register_basic_info([norm_old], file_info)

        dst_dir = tmp_path / 'dst'
        dst_dir.mkdir()
        f2 = dst_dir / 'a.bin'
        f1.rename(f2)
        norm_new = normalize_path(str(f2))

        idx.rename_by_pairs([(str(f1), str(f2))])

        prev = idx.db.load_existing_sources()
        assert norm_new in prev
        assert norm_old not in prev

        row = idx.db.read_conn.execute(
            "SELECT value FROM meta_info WHERE path=? AND key='name'", (norm_new,)
        ).fetchone()
        assert row is not None
        assert row[0] == 'a.bin'


def test_rename_by_pairs_skips_same_path(tmp_path):
    db_path = tmp_path / 'test.db'
    with FileIndexer(db_path) as idx:
        idx.initialize()
        idx.rename_by_pairs([('c:/same.jpg', 'c:/same.jpg')])
        assert idx.db.read_conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0


def _register_files(idx, tmp_path, names):
    import os
    from wafer.utils.paths import normalize_path
    d = tmp_path / 'files'
    d.mkdir(exist_ok=True)
    paths = []
    file_info = {}
    for name in names:
        f = d / name
        f.write_bytes(b'x' * 64)
        norm = normalize_path(str(f))
        st = os.stat(str(f))
        ctime = st.st_birthtime if hasattr(st, 'st_birthtime') else st.st_ctime
        file_info[norm] = (st.st_mtime, st.st_size, ctime)
        paths.append(norm)
    idx._register_basic_info(paths, file_info)
    return paths


def test_backfill_pending_adds_missing_entries(tmp_path):
    db_path = tmp_path / 'test.db'
    with FileIndexer(db_path) as idx:
        idx.initialize()
        paths = _register_files(idx, tmp_path, ['a.jpg', 'b.png', 'c.txt'])
        idx._collectors = [('image', ('.jpg', '.png'))]
        idx.backfill_pending_for_collectors()
        pending = idx.db.get_pending_sources('image')
        pending_sources = {r[0] for r in pending}
        assert paths[0] in pending_sources
        assert paths[1] in pending_sources
        assert paths[2] not in pending_sources


def test_backfill_pending_skips_existing(tmp_path):
    db_path = tmp_path / 'test.db'
    collectors = [('image', ('.jpg', '.png'))]
    with FileIndexer(db_path, collectors=collectors) as idx:
        idx.initialize()
        paths = _register_files(idx, tmp_path, ['a.jpg', 'b.png'])
        pending_before = idx.db.get_pending_sources('image')
        assert len(pending_before) == 2
        idx.db.upsert_collection_results([], [], [], [(paths[0], 'image', 'ok', 1.0)])
        idx.backfill_pending_for_collectors()
        row = idx.db.read_conn.execute(
            "SELECT status FROM collection_status WHERE source=? AND collector='image'",
            (paths[0],),
        ).fetchone()
        assert row[0] == 'ok'


def test_backfill_pending_new_collector(tmp_path):
    db_path = tmp_path / 'test.db'
    collectors = [('image', ('.jpg',))]
    with FileIndexer(db_path, collectors=collectors) as idx:
        idx.initialize()
        paths = _register_files(idx, tmp_path, ['a.jpg'])
        pending_image = idx.db.get_pending_sources('image')
        assert len(pending_image) == 1
        idx._collectors.append(('ocr', ('.jpg',)))
        idx.backfill_pending_for_collectors()
        pending_ocr = idx.db.get_pending_sources('ocr')
        assert len(pending_ocr) == 1
        assert pending_ocr[0][0] == paths[0]


def test_backfill_pending_no_collectors(tmp_path):
    db_path = tmp_path / 'test.db'
    with FileIndexer(db_path) as idx:
        idx.initialize()
        _register_files(idx, tmp_path, ['a.jpg'])
        idx.backfill_pending_for_collectors()


def test_backfill_pending_wildcard_extensions(tmp_path):
    db_path = tmp_path / 'test.db'
    with FileIndexer(db_path) as idx:
        idx.initialize()
        paths = _register_files(idx, tmp_path, ['a.jpg', 'b.txt'])
        idx._collectors = [('all', ())]
        idx.backfill_pending_for_collectors()
        pending = idx.db.get_pending_sources('all')
        pending_sources = {r[0] for r in pending}
        assert paths[0] in pending_sources
        assert paths[1] in pending_sources

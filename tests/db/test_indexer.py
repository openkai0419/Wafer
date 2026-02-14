import py_compile

from pathlib import Path

from source.db.indexer import ImageIndexer


def test_compile():
    py_compile.compile('source/db/indexer.py')


def test_imageindexer_exposes_db_path():
    idx = ImageIndexer('x.db')
    assert idx.db_path == Path('x.db')


def test_imageindexer_context_manager(tmp_path):
    db_path = tmp_path / 'test.db'
    with ImageIndexer(db_path) as idx:
        idx.check_init()
        assert idx.db.conn is not None


def test_imageindexer_exclude_paths(tmp_path):
    idx = ImageIndexer('x.db')
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
    idx = ImageIndexer('x.db')
    current = {'a': (1.0, 100), 'b': (2.0, 200), 'c': (3.0, 300)}
    previous = {'a': (1.0, 100), 'b': (1.0, 200), 'd': (4.0, 400)}
    added, removed = idx._detect_diff(current, previous)
    assert 'b' in added
    assert 'c' in added
    assert 'a' not in added
    assert 'd' in removed

import py_compile

from pathlib import Path

from source.db.collector import ImageIndexer


def test_compile():
    py_compile.compile('source/db/collector.py')


def test_imageindexer_exposes_db_path():
    idx = ImageIndexer('x.db')
    assert idx.db_path == Path('x.db')
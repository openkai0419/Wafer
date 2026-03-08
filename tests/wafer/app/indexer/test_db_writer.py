import os
import py_compile
import tempfile

import pytest

from wafer.app.indexer.db_writer import DatabaseWriter
from wafer.app.indexer.write_command import WriteCommand, WritePriority


def test_compile():
    py_compile.compile('wafer/app/indexer/db_writer.py')


@pytest.fixture
def writer(tmp_path):
    db_path = tmp_path / 'test.db'
    w = DatabaseWriter(db_path)
    w.start()
    w.initialize()
    yield w
    w.close()


def test_start_and_close(tmp_path):
    db_path = tmp_path / 'test.db'
    w = DatabaseWriter(db_path)
    w.start()
    assert w.db.conn is not None
    w.close()
    assert w.db.conn is None


def test_initialize_creates_tables(writer):
    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    cur.close()
    assert 'sources' in tables
    assert 'files' in tables
    assert 'collection_status' in tables


def test_execute_unknown_operation(writer):
    cmd = WriteCommand.create('nonexistent_op', data={})
    writer.execute(cmd)


def test_upsert_and_delete_sources(writer):
    source_entries = [('/a.png', 'hash1', 100, 1.0, 1.0, 1.0, 'indexed')]
    image_entries = [('/a.png', '/a.png', 'a.png', 1.5)]

    cmd_upsert = WriteCommand.create(
        'upsert_sources',
        data={'source_entries': source_entries, 'image_entries': image_entries},
    )
    writer.execute(cmd_upsert)

    cur = writer.db.get_reader_cursor()
    cur.execute('SELECT source FROM sources')
    rows = cur.fetchall()
    cur.close()
    assert len(rows) == 1
    assert rows[0][0] == '/a.png'

    cmd_delete = WriteCommand.create(
        'delete_sources',
        priority=WritePriority.REALTIME,
        data={'paths': ['/a.png']},
    )
    writer.execute(cmd_delete)

    cur = writer.db.get_reader_cursor()
    cur.execute('SELECT source FROM sources')
    rows = cur.fetchall()
    cur.close()
    assert len(rows) == 0


def test_rename_paths(writer):
    source_entries = [('/old.png', 'hash1', 100, 1.0, 1.0, 1.0, 'indexed')]
    image_entries = [('/old.png', '/old.png', 'old.png', 1.0)]
    writer.execute(WriteCommand.create(
        'upsert_sources',
        data={'source_entries': source_entries, 'image_entries': image_entries},
    ))

    writer.execute(WriteCommand.create(
        'rename_paths',
        data={'pairs': [('/old.png', '/new.png')]},
    ))

    cur = writer.db.get_reader_cursor()
    cur.execute('SELECT source FROM sources')
    rows = cur.fetchall()
    cur.close()
    assert rows[0][0] == '/new.png'


def test_insert_pending_and_mark_dispatched(writer):
    source_entries = [('/a.png', 'hash1', 100, 1.0, 1.0, 1.0, 'indexed')]
    image_entries = [('/a.png', '/a.png', 'a.png', 1.0)]
    writer.execute(WriteCommand.create(
        'upsert_sources',
        data={'source_entries': source_entries, 'image_entries': image_entries},
    ))

    writer.execute(WriteCommand.create(
        'insert_pending',
        data={'sources': ['/a.png'], 'collectors': ['exif']},
    ))

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT status FROM collection_status WHERE source='/a.png' AND collector='exif'")
    assert cur.fetchone()[0] == 'pending'
    cur.close()

    writer.execute(WriteCommand.create(
        'mark_dispatched',
        data={'sources': ['/a.png'], 'collector': 'exif'},
    ))

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT status FROM collection_status WHERE source='/a.png' AND collector='exif'")
    assert cur.fetchone()[0] == 'dispatched'
    cur.close()


def test_reset_stale(writer):
    source_entries = [('/a.png', 'hash1', 100, 1.0, 1.0, 1.0, 'indexed')]
    image_entries = [('/a.png', '/a.png', 'a.png', 1.0)]
    writer.execute(WriteCommand.create(
        'upsert_sources',
        data={'source_entries': source_entries, 'image_entries': image_entries},
    ))
    writer.execute(WriteCommand.create(
        'insert_pending',
        data={'sources': ['/a.png'], 'collectors': ['exif']},
    ))
    writer.execute(WriteCommand.create(
        'mark_dispatched',
        data={'sources': ['/a.png'], 'collector': 'exif'},
    ))

    writer.execute(WriteCommand.create('reset_stale', data={'collectors': ['exif']}))

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT status FROM collection_status WHERE source='/a.png'")
    assert cur.fetchone()[0] == 'pending'
    cur.close()


def test_upsert_collection_results(writer):
    source_entries = [('/a.png', 'hash1', 100, 1.0, 1.0, 1.0, 'indexed')]
    image_entries = [('/a.png', '/a.png', 'a.png', 1.0)]
    writer.execute(WriteCommand.create(
        'upsert_sources',
        data={'source_entries': source_entries, 'image_entries': image_entries},
    ))
    writer.execute(WriteCommand.create(
        'insert_pending',
        data={'sources': ['/a.png'], 'collectors': ['exif']},
    ))

    writer.execute(WriteCommand.create(
        'upsert_results',
        priority=WritePriority.COLLECTION,
        data={
            'source_updates': [(2.0, 'ok', '/a.png')],
            'image_entries': [],
            'meta_info_entries': [('/a.png', 'width', '1920')],
            'tag_entries': [('hash1', 'rating', '5')],
            'collector_status': [('/a.png', 'exif', 'ok', 2.0)],
        },
    ))

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT status FROM sources WHERE source='/a.png'")
    assert cur.fetchone()[0] == 'ok'
    cur.execute("SELECT value FROM meta_info WHERE path='/a.png' AND key='width'")
    assert cur.fetchone()[0] == '1920'
    cur.execute("SELECT value FROM tags WHERE file_hash='hash1' AND key='rating'")
    assert cur.fetchone()[0] == '5'
    cur.close()


def test_purge_orphans(writer):
    writer.execute(WriteCommand.create('purge_orphans', priority=WritePriority.MAINTENANCE))


def test_checkpoint(writer):
    writer.execute(WriteCommand.create('checkpoint', data={'mode': 'PASSIVE'}))


def test_execute_error_does_not_raise(writer):
    cmd = WriteCommand.create('delete_sources', data={'paths': None})
    writer.execute(cmd)

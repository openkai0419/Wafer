import os
import time
from pathlib import Path

from PIL import Image

from wafer.utils.paths import normalize_path
from wafer.core.db.query import FileSearchEngine, SearchQuery
from wafer.plugin.collector.handler import collector_resolver
from wafer.app.indexer.db_writer import DatabaseWriter
from wafer.app.indexer.scanner import DirectoryScanner
from wafer.app.indexer.scheduler import TaskScheduler
from wafer.app.indexer.watch_folder import FolderWatcher
from wafer.app.indexer.progress_notifier import ProgressAggregator


class _StubNode:
    def __init__(self):
        self.sent = []

    def send(self, *a, **kw):
        self.sent.append(('send', a, kw))

    def send_coalesced(self, *a, **kw):
        self.sent.append(('send_coalesced', a, kw))


def _create_test_image(path, width=100, height=80, fmt='JPEG'):
    img = Image.new('RGB', (width, height), color=(255, 0, 0))
    img.save(str(path), format=fmt)


def _wait_for_condition(predicate, timeout=15.0, interval=0.2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _source_count(db):
    return db.read_conn.execute("SELECT count(*) FROM sources").fetchone()[0]


def _build_watcher_stack(tmp_path):
    db_path = tmp_path / 'test.db'
    collectors = collector_resolver.summary()
    node = _StubNode()
    progress = ProgressAggregator('test', node)
    writer = DatabaseWriter(db_path)
    scheduler = TaskScheduler(writer)
    scanner = DirectoryScanner(db_path, scheduler, progress, collectors)
    watcher = FolderWatcher(scheduler, scanner, progress)
    return db_path, writer, scheduler, scanner, watcher


class TestFsWatchToDb:

    def test_new_file_detected_and_indexed(self, tmp_path):
        img_dir = tmp_path / 'watched'
        img_dir.mkdir()
        _create_test_image(img_dir / 'initial.jpg', 100, 80)

        db_path, writer, scheduler, scanner, watcher = _build_watcher_stack(tmp_path)
        scheduler.start()
        scanner.start()
        try:
            watcher.start([str(img_dir)])
            assert _wait_for_condition(lambda: _source_count(writer.db) >= 1)

            _create_test_image(img_dir / 'new_file.jpg', 200, 100)
            assert _wait_for_condition(lambda: _source_count(writer.db) >= 2, timeout=20.0)

            norm = normalize_path(str(img_dir / 'new_file.jpg'))
            row = writer.db.read_conn.execute(
                "SELECT status FROM sources WHERE source=?", (norm,)
            ).fetchone()
            assert row is not None
            assert row[0] == 'indexed'
        finally:
            watcher.stop()
            scanner.stop()
            scheduler.stop()

    def test_file_deletion_detected(self, tmp_path):
        img_dir = tmp_path / 'watched'
        img_dir.mkdir()
        keep = img_dir / 'keep.jpg'
        remove = img_dir / 'remove.jpg'
        _create_test_image(keep, 100, 80)
        _create_test_image(remove, 100, 80)

        db_path, writer, scheduler, scanner, watcher = _build_watcher_stack(tmp_path)
        scheduler.start()
        scanner.start()
        try:
            watcher.start([str(img_dir)])
            assert _wait_for_condition(lambda: _source_count(writer.db) >= 2)

            remove.unlink()
            assert _wait_for_condition(lambda: _source_count(writer.db) == 1, timeout=20.0)

            engine = FileSearchEngine(str(db_path))
            paths, _, _ = engine.search(SearchQuery(require_keys=False))
            assert len(paths) == 1
            assert paths[0] == normalize_path(str(keep))
        finally:
            watcher.stop()
            scanner.stop()
            scheduler.stop()

    def test_file_rename_tracked(self, tmp_path):
        img_dir = tmp_path / 'watched'
        img_dir.mkdir()
        old_path = img_dir / 'old_name.jpg'
        new_path = img_dir / 'new_name.jpg'
        _create_test_image(old_path, 100, 80)

        db_path, writer, scheduler, scanner, watcher = _build_watcher_stack(tmp_path)
        scheduler.start()
        scanner.start()
        try:
            watcher.start([str(img_dir)])
            assert _wait_for_condition(lambda: _source_count(writer.db) >= 1)

            old_path.rename(new_path)
            old_norm = normalize_path(str(old_path))
            new_norm = normalize_path(str(new_path))

            def rename_reflected():
                row = writer.db.read_conn.execute(
                    "SELECT source FROM sources WHERE source=?", (new_norm,)
                ).fetchone()
                return row is not None

            assert _wait_for_condition(rename_reflected, timeout=20.0)

            engine = FileSearchEngine(str(db_path))
            paths, _, _ = engine.search(SearchQuery(
                keys='__filepath__', keywords='new_name',
            ))
            assert len(paths) >= 1
            assert any('new_name' in p for p in paths)
        finally:
            watcher.stop()
            scanner.stop()
            scheduler.stop()

    def test_file_modification_triggers_reindex(self, tmp_path):
        img_dir = tmp_path / 'watched'
        img_dir.mkdir()
        img_path = img_dir / 'mutable.jpg'
        _create_test_image(img_path, 100, 80)

        db_path, writer, scheduler, scanner, watcher = _build_watcher_stack(tmp_path)
        scheduler.start()
        scanner.start()
        try:
            watcher.start([str(img_dir)])
            assert _wait_for_condition(lambda: _source_count(writer.db) >= 1)

            norm = normalize_path(str(img_path))
            row_before = writer.db.read_conn.execute(
                "SELECT modified, size FROM sources WHERE source=?", (norm,)
            ).fetchone()
            old_mtime = row_before[0]
            old_size = row_before[1]

            time.sleep(1.5)
            _create_test_image(img_path, 300, 200)

            def modification_detected():
                row = writer.db.read_conn.execute(
                    "SELECT modified, size FROM sources WHERE source=?", (norm,)
                ).fetchone()
                if row is None:
                    return False
                return row[0] != old_mtime or row[1] != old_size

            assert _wait_for_condition(modification_detected, timeout=20.0)
        finally:
            watcher.stop()
            scanner.stop()
            scheduler.stop()

    def test_rescan_recovers_full_state(self, tmp_path):
        img_dir = tmp_path / 'watched'
        img_dir.mkdir()
        for i in range(3):
            _create_test_image(img_dir / f'img_{i}.jpg', 100 + i, 80)

        db_path, writer, scheduler, scanner, watcher = _build_watcher_stack(tmp_path)
        scheduler.start()
        scanner.start()
        try:
            watcher.start([str(img_dir)])
            assert _wait_for_condition(lambda: _source_count(writer.db) >= 3)

            watcher.rescan_all()
            time.sleep(3.0)

            count = _source_count(writer.db)
            assert count == 3
        finally:
            watcher.stop()
            scanner.stop()
            scheduler.stop()

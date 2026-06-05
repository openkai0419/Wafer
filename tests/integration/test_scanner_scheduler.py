import os
import threading
import time
from pathlib import Path

from PIL import Image

from wafer.utils.paths import normalize_path
from wafer.core.db.file_db import FileDB
from wafer.core.db.query import FileSearchEngine, SearchQuery
from wafer.plugin.collector.handler import collector_resolver
from wafer.app.indexer.db_writer import DatabaseWriter
from wafer.app.indexer.scanner import DirectoryScanner
from wafer.app.indexer.runtime.scheduler import TaskScheduler
from wafer.app.indexer.runtime.task import Task, TaskPriority
from wafer.app.indexer.runtime.progress_aggregator import ProgressAggregator


class _StubNode:
    def __init__(self):
        self.sent = []

    def send(self, *a, **kw):
        self.sent.append(("send", a, kw))

    def send_coalesced(self, *a, **kw):
        self.sent.append(("send_coalesced", a, kw))


def _create_test_image(path, width=100, height=80, fmt="JPEG"):
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    img.save(str(path), format=fmt)


def _create_test_file(path, content=b"dummy"):
    Path(path).write_bytes(content)


def _wait_for_condition(predicate, timeout=10.0, interval=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class TestScannerSchedulerPipeline:
    def test_full_scan_registers_all_files(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        for i in range(5):
            _create_test_image(img_dir / f"img_{i}.jpg", 100 + i, 80)

        db_path = tmp_path / "test.db"
        collectors = collector_resolver.summary()
        node = _StubNode()
        progress = ProgressAggregator("test", node)
        writer = DatabaseWriter(db_path)
        writer.start()
        writer.initialize()
        scheduler = TaskScheduler()
        scanner = DirectoryScanner(db_path, scheduler, writer, progress, collectors)

        scheduler.start()
        scanner.start()
        try:
            scanner.request_scan([str(img_dir)])
            assert _wait_for_condition(
                lambda: writer.db.read_conn.execute("SELECT count(*) FROM sources").fetchone()[0] >= 5,
                timeout=15.0,
            )

            count = writer.db.read_conn.execute("SELECT count(*) FROM sources").fetchone()[0]
            assert count == 5

            files_count = writer.db.read_conn.execute("SELECT count(*) FROM files").fetchone()[0]
            assert files_count == 5

            for i in range(5):
                norm = normalize_path(str(img_dir / f"img_{i}.jpg"))
                row = writer.db.read_conn.execute("SELECT source FROM sources WHERE source=?", (norm,)).fetchone()
                assert row is not None
        finally:
            scanner.stop()
            scheduler.stop()

    def test_incremental_scan_detects_changes(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        _create_test_image(img_dir / "original.jpg", 100, 80)

        db_path = tmp_path / "test.db"
        collectors = collector_resolver.summary()
        node = _StubNode()
        progress = ProgressAggregator("test", node)
        writer = DatabaseWriter(db_path)
        writer.start()
        writer.initialize()
        scheduler = TaskScheduler()
        scanner = DirectoryScanner(db_path, scheduler, writer, progress, collectors)

        scheduler.start()
        scanner.start()
        try:
            scanner.request_scan([str(img_dir)])
            assert _wait_for_condition(
                lambda: writer.db.read_conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1,
                timeout=10.0,
            )

            _create_test_image(img_dir / "added.jpg", 120, 90)
            scanner.request_scan([str(img_dir)])
            assert _wait_for_condition(
                lambda: writer.db.read_conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 2,
                timeout=10.0,
            )

            (img_dir / "original.jpg").unlink()
            scanner.request_scan([str(img_dir)])
            assert _wait_for_condition(
                lambda: writer.db.read_conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1,
                timeout=10.0,
            )
            remaining = writer.db.read_conn.execute("SELECT source FROM sources").fetchone()[0]
            assert remaining == normalize_path(str(img_dir / "added.jpg"))
        finally:
            scanner.stop()
            scheduler.stop()

    def test_exclude_paths_skip_scanning(self, tmp_path):
        root = tmp_path / "root"
        keep_dir = root / "keep"
        skip_dir = root / "skip"
        keep_dir.mkdir(parents=True)
        skip_dir.mkdir(parents=True)
        _create_test_image(keep_dir / "a.jpg", 100, 80)
        _create_test_image(skip_dir / "b.jpg", 100, 80)

        db_path = tmp_path / "test.db"
        collectors = collector_resolver.summary()
        node = _StubNode()
        progress = ProgressAggregator("test", node)
        writer = DatabaseWriter(db_path)
        writer.start()
        writer.initialize()
        scheduler = TaskScheduler()
        scanner = DirectoryScanner(db_path, scheduler, writer, progress, collectors)
        scanner.set_exclude_paths([str(skip_dir)])

        scheduler.start()
        scanner.start()
        try:
            scanner.request_scan([str(root)])
            assert _wait_for_condition(
                lambda: writer.db.read_conn.execute("SELECT count(*) FROM sources").fetchone()[0] >= 1,
                timeout=10.0,
            )
            time.sleep(1.0)

            count = writer.db.read_conn.execute("SELECT count(*) FROM sources").fetchone()[0]
            assert count == 1

            row = writer.db.read_conn.execute("SELECT source FROM sources").fetchone()
            norm_skip = normalize_path(str(skip_dir))
            assert "keep" in row[0]
            assert not row[0].startswith(norm_skip)
        finally:
            scanner.stop()
            scheduler.stop()

    def test_backfill_pending_creates_collection_tasks(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        _create_test_image(img_dir / "photo.jpg", 200, 100)

        db_path = tmp_path / "test.db"
        collectors = collector_resolver.summary()
        node = _StubNode()
        progress = ProgressAggregator("test", node)
        writer = DatabaseWriter(db_path)
        writer.start()
        writer.initialize()
        scheduler = TaskScheduler()
        scanner = DirectoryScanner(db_path, scheduler, writer, progress, collectors)

        scheduler.start()
        scanner.start()
        try:
            scanner.request_scan([str(img_dir)])
            assert _wait_for_condition(
                lambda: writer.db.read_conn.execute("SELECT count(*) FROM collection_status WHERE status='pending'").fetchone()[0] >= 1,
                timeout=10.0,
            )

            writer.db.conn.execute("DELETE FROM collection_status")
            writer.db.conn.commit()

            assert writer.db.read_conn.execute("SELECT count(*) FROM collection_status").fetchone()[0] == 0

            scanner.backfill_pending()
            assert _wait_for_condition(
                lambda: writer.db.read_conn.execute("SELECT count(*) FROM collection_status WHERE status='pending'").fetchone()[0] >= 1,
                timeout=10.0,
            )
        finally:
            scanner.stop()
            scheduler.stop()

    def test_task_priority_ordering(self, tmp_path):
        db_path = tmp_path / "test.db"
        writer = DatabaseWriter(db_path)
        writer.start()
        writer.initialize()
        scheduler = TaskScheduler()
        scheduler.start()
        time.sleep(0.3)

        executed_ops = []
        barrier = threading.Event()

        scheduler.submit(
            Task.create(
                "blocker",
                priority=TaskPriority.SCAN,
                run=lambda: barrier.wait(5.0),
            )
        )
        time.sleep(0.1)

        for _ in range(3):
            scheduler.submit(
                Task.create(
                    "noop_low",
                    priority=TaskPriority.MAINTENANCE,
                    run=lambda: executed_ops.append("low"),
                )
            )
        done = threading.Event()
        scheduler.submit(
            Task.create(
                "noop_high",
                priority=TaskPriority.SCAN,
                run=lambda: executed_ops.append("high"),
                on_complete=done.set,
            )
        )

        barrier.set()
        done.wait(timeout=5.0)
        time.sleep(1.0)
        scheduler.stop()
        writer.close()

        assert len(executed_ops) >= 2
        high_idx = executed_ops.index("high")
        low_indices = [i for i, x in enumerate(executed_ops) if x == "low"]
        assert any(high_idx < li for li in low_indices)

    def test_scan_result_searchable(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        _create_test_image(img_dir / "findme.jpg", 100, 80)
        _create_test_image(img_dir / "other.png", 64, 64, "PNG")

        db_path = tmp_path / "test.db"
        collectors = collector_resolver.summary()
        node = _StubNode()
        progress = ProgressAggregator("test", node)
        writer = DatabaseWriter(db_path)
        writer.start()
        writer.initialize()
        scheduler = TaskScheduler()
        scanner = DirectoryScanner(db_path, scheduler, writer, progress, collectors)

        scheduler.start()
        scanner.start()
        try:
            scanner.request_scan([str(img_dir)])
            assert _wait_for_condition(
                lambda: writer.db.read_conn.execute("SELECT count(*) FROM files").fetchone()[0] >= 2,
                timeout=10.0,
            )
        finally:
            scanner.stop()
            scheduler.stop()

        engine = FileSearchEngine(str(db_path))
        paths, _, _ = engine.search(
            SearchQuery(
                keys="path",
                keywords="findme",
            )
        )
        assert len(paths) == 1
        assert "findme" in paths[0]

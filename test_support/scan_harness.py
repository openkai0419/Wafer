"""Production indexing stack harness for tests.

Wraps DatabaseWriter + TaskScheduler + DirectoryScanner lifecycle.
Contains only orchestration and waiting glue — no indexing logic.
"""

import time
from pathlib import Path


class _StubNode:
    def send_coalesced(self, *a, **kw):
        pass


class ScanHarness:
    """Context manager that sets up the full production indexing stack.

    Access the live database through the `db` property after scanning.
    """

    def __init__(self, db_path, collectors=None):
        self._db_path = Path(db_path)
        self._collectors = collectors or []
        self.writer = None
        self.scheduler = None
        self.scanner = None

    @property
    def db(self):
        return self.writer.db

    def __enter__(self):
        from wafer.app.indexer.db_writer import DatabaseWriter
        from wafer.app.indexer.progress_notifier import ProgressAggregator
        from wafer.app.indexer.scanner import DirectoryScanner
        from wafer.app.indexer.scheduler import TaskScheduler

        self.writer = DatabaseWriter(self._db_path)
        self.writer.start()
        self.writer.initialize()

        node = _StubNode()
        progress = ProgressAggregator(self._db_path.stem, node)

        self.scheduler = TaskScheduler()
        self.scanner = DirectoryScanner(
            self._db_path, self.scheduler, self.writer, progress, self._collectors
        )

        self.scheduler.start()
        self.scanner.start()
        return self

    def __exit__(self, *_):
        if self.scanner:
            self.scanner.stop()
        if self.scheduler:
            self.scheduler.stop()
        if self.writer:
            self.writer.close()

    def scan(self, folders):
        """Request a full directory scan."""
        if isinstance(folders, (str, Path)):
            folders = [folders]
        self.scanner.request_scan([str(f) for f in folders])

    def update(self, paths):
        """Request a selective file update."""
        if isinstance(paths, (str, Path)):
            paths = [paths]
        self.scanner.request_update([str(p) for p in paths])

    def backfill(self):
        """Request pending collection backfill."""
        self.scanner.backfill_pending()

    def wait_for_idle(self, timeout=10.0):
        """Wait until the scanner has no queued requests and the scheduler is idle."""

        def is_idle():
            if self.scanner:
                with self.scanner._request_lock:
                    if self.scanner._request_queue:
                        return False
            return self.scheduler is not None and self.scheduler.is_idle()

        return self.wait_for(is_idle, timeout=timeout)

    def wait_for(self, predicate, timeout=10.0):
        """Poll until predicate() is True or timeout elapses. Returns True if satisfied."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def scan_and_wait(self, folders, expected, timeout=10.0):
        """Scan directories and wait until sources table has exactly `expected` rows."""
        self.scan(folders)
        ok = self.wait_for(
            lambda: self.db.read_conn.execute("SELECT count(*) FROM sources").fetchone()[0] == expected,
            timeout=timeout,
        )
        assert ok, f"scan_and_wait: timed out waiting for {expected} sources in DB"
        ok = self.wait_for_idle(timeout=timeout)
        assert ok, "scan_and_wait: timed out waiting for scheduler to become idle"

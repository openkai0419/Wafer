import py_compile
import time
from unittest.mock import MagicMock


def test_compile():
    py_compile.compile('wafer/app/indexer/watch_folder.py')


class _FakeIndexer:

    def __init__(self):
        self.rename_calls = []
        self.update_calls = []
        self.remove_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def set_progress_callback(self, cb):
        pass

    def set_update_callback(self, cb):
        pass

    def rename_by_pairs(self, pairs):
        self.rename_calls.append(sorted(pairs))

    def update_by_file_list(self, paths):
        self.update_calls.append(sorted(paths))

    def remove_by_file_list(self, paths):
        self.remove_calls.append(sorted(paths))


def _make_watcher(fake_db):
    from wafer.app.indexer.watch_folder import FolderWatcher
    progress = MagicMock()
    wf = FolderWatcher(fake_db, progress)
    wf.stop()
    return wf


def test_flush_basic_rename():
    db = _FakeIndexer()
    wf = _make_watcher(db)
    changed = set()
    deleted = set()
    moved = {'A': 'B'}
    wf._flush(changed, deleted, moved)
    assert db.rename_calls == [[('A', 'B')]]
    assert db.update_calls == []
    assert db.remove_calls == []


def test_flush_create_then_rename():
    db = _FakeIndexer()
    wf = _make_watcher(db)
    changed = {'A'}
    deleted = set()
    moved = {'A': 'B'}
    wf._flush(changed, deleted, moved)
    assert db.rename_calls == [[('A', 'B')]]
    assert db.update_calls == [['B']]
    assert db.remove_calls == []


def test_flush_rename_then_delete():
    db = _FakeIndexer()
    wf = _make_watcher(db)
    changed = set()
    deleted = {'B'}
    moved = {'A': 'B'}
    wf._flush(changed, deleted, moved)
    assert db.rename_calls == [[('A', 'B')]]
    assert db.remove_calls == [['B']]


def test_flush_delete_then_recreate():
    db = _FakeIndexer()
    wf = _make_watcher(db)
    changed = {'A'}
    deleted = {'A'}
    moved = {}
    wf._flush(changed, deleted, moved)
    assert db.remove_calls == [['A']]
    assert db.update_calls == [['A']]


def test_flush_multiple_independent_renames():
    db = _FakeIndexer()
    wf = _make_watcher(db)
    changed = set()
    deleted = set()
    moved = {'A': 'B', 'C': 'D'}
    wf._flush(changed, deleted, moved)
    assert db.rename_calls == [[('A', 'B'), ('C', 'D')]]


def test_flush_create_rename_with_unrelated_changed():
    db = _FakeIndexer()
    wf = _make_watcher(db)
    changed = {'A', 'X'}
    deleted = set()
    moved = {'A': 'B'}
    wf._flush(changed, deleted, moved)
    assert db.rename_calls == [[('A', 'B')]]
    assert db.update_calls == [sorted(['B', 'X'])]


def test_flush_only_changed():
    db = _FakeIndexer()
    wf = _make_watcher(db)
    changed = {'A', 'B'}
    deleted = set()
    moved = {}
    wf._flush(changed, deleted, moved)
    assert db.rename_calls == []
    assert db.update_calls == [sorted(['A', 'B'])]
    assert db.remove_calls == []


def test_flush_only_deleted():
    db = _FakeIndexer()
    wf = _make_watcher(db)
    changed = set()
    deleted = {'A'}
    moved = {}
    wf._flush(changed, deleted, moved)
    assert db.remove_calls == [['A']]
    assert db.rename_calls == []
    assert db.update_calls == []


def test_flush_empty():
    db = _FakeIndexer()
    wf = _make_watcher(db)
    changed = set()
    deleted = set()
    moved = {}
    wf._flush(changed, deleted, moved)
    assert db.rename_calls == []
    assert db.update_calls == []
    assert db.remove_calls == []


def test_flush_chained_rename():
    db = _FakeIndexer()
    wf = _make_watcher(db)
    changed = set()
    deleted = set()
    moved = {'A': 'B', 'B': 'C'}
    wf._flush(changed, deleted, moved)
    assert db.rename_calls == [[('A', 'B'), ('B', 'C')]]


def test_flush_create_rename_delete_mixed():
    db = _FakeIndexer()
    wf = _make_watcher(db)
    changed = {'new_file'}
    deleted = {'old_file'}
    moved = {'new_file': 'final_name'}
    wf._flush(changed, deleted, moved)
    assert db.rename_calls == [[('new_file', 'final_name')]]
    assert db.remove_calls == [['old_file']]
    assert db.update_calls == [['final_name']]


class TestExtractStable:

    def test_all_stable(self, tmp_path):
        from wafer.app.indexer.watch_folder import _extract_stable, _stat_signature, _STABLE_THRESHOLD
        f1 = tmp_path / 'a.txt'
        f2 = tmp_path / 'b.txt'
        f1.write_text('x')
        f2.write_text('y')
        sig = _stat_signature(str(f1))
        sig2 = _stat_signature(str(f2))
        old = time.monotonic() - _STABLE_THRESHOLD - 1
        pending = {str(f1): (old, sig), str(f2): (old, sig2)}
        stable = _extract_stable(pending)
        assert stable == {str(f1), str(f2)}
        assert pending == {}

    def test_none_stable(self, tmp_path):
        from wafer.app.indexer.watch_folder import _extract_stable, _stat_signature
        f1 = tmp_path / 'a.txt'
        f2 = tmp_path / 'b.txt'
        f1.write_text('x')
        f2.write_text('y')
        now = time.monotonic()
        sig = _stat_signature(str(f1))
        sig2 = _stat_signature(str(f2))
        pending = {str(f1): (now, sig), str(f2): (now, sig2)}
        stable = _extract_stable(pending)
        assert stable == set()
        assert len(pending) == 2

    def test_partial_stable(self, tmp_path):
        from wafer.app.indexer.watch_folder import _extract_stable, _stat_signature, _STABLE_THRESHOLD
        f_old = tmp_path / 'old.txt'
        f_new = tmp_path / 'new.txt'
        f_old.write_text('x')
        f_new.write_text('y')
        now = time.monotonic()
        old_ts = now - _STABLE_THRESHOLD - 1
        pending = {
            str(f_old): (old_ts, _stat_signature(str(f_old))),
            str(f_new): (now, _stat_signature(str(f_new))),
        }
        stable = _extract_stable(pending)
        assert stable == {str(f_old)}
        assert str(f_new) in pending

    def test_empty_pending(self):
        from wafer.app.indexer.watch_folder import _extract_stable
        pending = {}
        stable = _extract_stable(pending)
        assert stable == set()
        assert pending == {}

    def test_file_changed_since_pending_resets_timer(self, tmp_path):
        from wafer.app.indexer.watch_folder import _extract_stable, _stat_signature, _STABLE_THRESHOLD
        f = tmp_path / 'dl.bin'
        f.write_bytes(b'part1')
        old_sig = _stat_signature(str(f))
        old_ts = time.monotonic() - _STABLE_THRESHOLD - 1
        f.write_bytes(b'part1part2')
        pending = {str(f): (old_ts, old_sig)}
        stable = _extract_stable(pending)
        assert stable == set()
        assert str(f) in pending
        _, new_sig = pending[str(f)]
        assert new_sig != old_sig

    def test_deleted_file_stabilizes(self):
        from wafer.app.indexer.watch_folder import _extract_stable, _STABLE_THRESHOLD
        old_ts = time.monotonic() - _STABLE_THRESHOLD - 1
        pending = {'/nonexistent/file.tmp': (old_ts, (12345, 100))}
        stable = _extract_stable(pending)
        assert stable == {'/nonexistent/file.tmp'}


class TestEventAccumulator:

    def _make_accumulator(self):
        from wafer.app.indexer.watch_folder import _EventAccumulator
        return _EventAccumulator()

    def _run_and_flush(self, events, db):
        from wafer.app.indexer.watch_folder import _EventAccumulator
        acc = _EventAccumulator()
        wf = _make_watcher(db)
        now = time.monotonic()
        for ev in events:
            kind, data = ev[0], ev[1]
            if kind == 'created':
                acc.on_created(data)
            elif kind == 'changed':
                acc.on_changed(data, now)
            elif kind == 'deleted':
                acc.on_deleted(data)
            elif kind == 'moved':
                acc.on_moved(*data)
        wf._flush(*acc.drain())
        return db

    def test_changed_then_deleted(self):
        db = self._run_and_flush([
            ('changed', 'a.png'),
            ('deleted', 'a.png'),
        ], _FakeIndexer())
        assert db.remove_calls == [['a.png']]
        assert db.update_calls == []

    def test_changed_then_moved(self):
        db = self._run_and_flush([
            ('changed', 'a.png'),
            ('moved', ('a.png', 'b.png')),
        ], _FakeIndexer())
        assert db.rename_calls == [[('a.png', 'b.png')]]

    def test_first_modified_is_immediate(self):
        db = self._run_and_flush([
            ('changed', 'new.png'),
        ], _FakeIndexer())
        assert db.update_calls == [['new.png']]

    def test_second_modified_stays_ready(self):
        db = self._run_and_flush([
            ('changed', 'dl.png'),
            ('changed', 'dl.png'),
        ], _FakeIndexer())
        assert db.update_calls == [['dl.png']]

    def test_created_is_immediate(self):
        db = self._run_and_flush([
            ('created', 'new.png'),
        ], _FakeIndexer())
        assert db.update_calls == [['new.png']]

    def test_created_then_modified_stays_ready(self):
        db = self._run_and_flush([
            ('created', 'dl.png'),
            ('changed', 'dl.png'),
        ], _FakeIndexer())
        assert db.update_calls == [['dl.png']]

    def test_modified_does_not_override_ready(self):
        db = self._run_and_flush([
            ('created', 'x.png'),
            ('changed', 'x.png'),
            ('changed', 'x.png'),
        ], _FakeIndexer())
        assert db.update_calls == [['x.png']]

    def test_created_then_deleted(self):
        db = self._run_and_flush([
            ('created', 'tmp.png'),
            ('deleted', 'tmp.png'),
        ], _FakeIndexer())
        assert db.remove_calls == [['tmp.png']]
        assert db.update_calls == []

    def test_folder_dirty(self):
        acc = self._make_accumulator()
        assert not acc.consume_folder_dirty()
        acc.on_folder()
        assert acc.consume_folder_dirty()
        assert not acc.consume_folder_dirty()

    def test_drain_all_includes_pending(self):
        acc = self._make_accumulator()
        now = time.monotonic()
        acc.on_changed('a.png', now)
        acc.drain()
        acc.on_changed('a.png', now)
        changed, _, _ = acc.drain_all()
        assert 'a.png' in changed

import py_compile
import time
from unittest.mock import MagicMock, call


def test_compile():
    py_compile.compile('wafer/app/indexer/watch_folder.py')


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def _make_watcher():
    from wafer.app.indexer.watch_folder import FolderWatcher
    scheduler = MagicMock()
    writer = MagicMock()
    scanner = MagicMock()
    progress = MagicMock()
    wf = FolderWatcher(scheduler, writer, scanner, progress)
    wf.stop()
    return wf, scheduler, writer, scanner, progress


def _collect_exec_calls(scheduler, scanner):
    rename_names = []
    delete_names = []
    update_paths = []
    for c in scheduler.submit.call_args_list:
        task = c[0][0]
        if task.name == 'rename_paths':
            rename_names.append(task.name)
        elif task.name == 'delete_sources':
            delete_names.append(task.name)
    for c in scanner.request_update.call_args_list:
        update_paths.append(sorted(c[0][0]))
    return rename_names, update_paths, delete_names


def test_flush_basic_rename():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._flush(set(), set(), {'A': 'B'})
    assert scheduler.submit.called
    task = scheduler.submit.call_args[0][0]
    assert task.name == 'rename_paths'


def test_flush_create_then_rename():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._flush({'A'}, set(), {'A': 'B'})
    rename_names, update_paths, _ = _collect_exec_calls(scheduler, scanner)
    assert len(rename_names) == 1
    assert len(update_paths) == 1
    assert 'B' in update_paths[0]


def test_flush_rename_then_delete(tmp_path):
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._flush(set(), {'B'}, {'A': 'B'})
    rename_names, _, delete_names = _collect_exec_calls(scheduler, scanner)
    assert len(rename_names) == 1


def test_flush_only_changed():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._flush({'A', 'B'}, set(), {})
    assert scanner.request_update.called
    assert not scheduler.submit.called


def test_flush_only_deleted():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._flush(set(), {'/nonexistent/file.png'}, {})
    assert scheduler.submit.called
    task = scheduler.submit.call_args[0][0]
    assert task.name == 'delete_sources'


def test_flush_empty():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._flush(set(), set(), {})
    assert not scheduler.submit.called
    assert not scanner.request_update.called


def test_exec_rescan():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._exec('rescan', ['/some/folder'])
    scanner.request_scan.assert_called_once_with(['/some/folder'])


def test_exec_update():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._exec('update', ['/some/file.png'])
    scanner.request_update.assert_called_once_with(['/some/file.png'])


def test_exec_cleanup():
    wf, scheduler, writer, scanner, progress = _make_watcher()
    wf._exec('cleanup')
    assert scheduler.submit.called
    task = scheduler.submit.call_args[0][0]
    assert task.name == 'purge_orphans'


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

    def _run_and_flush(self, events):
        from wafer.app.indexer.watch_folder import _EventAccumulator
        acc = _EventAccumulator()
        wf, scheduler, writer, scanner, _ = _make_watcher()
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
        return scheduler, scanner

    def test_changed_then_deleted(self):
        scheduler, scanner = self._run_and_flush([
            ('changed', 'a.png'),
            ('deleted', 'a.png'),
        ])
        ops = [c[0][0].name for c in scheduler.submit.call_args_list]
        assert 'delete_sources' in ops
        assert not scanner.request_update.called

    def test_changed_then_moved(self):
        scheduler, scanner = self._run_and_flush([
            ('changed', 'a.png'),
            ('moved', ('a.png', 'b.png')),
        ])
        ops = [c[0][0].name for c in scheduler.submit.call_args_list]
        assert 'rename_paths' in ops

    def test_first_modified_is_immediate(self):
        scheduler, scanner = self._run_and_flush([
            ('changed', 'new.png'),
        ])
        assert scanner.request_update.called

    def test_second_modified_stays_ready(self):
        scheduler, scanner = self._run_and_flush([
            ('changed', 'dl.png'),
            ('changed', 'dl.png'),
        ])
        assert scanner.request_update.called

    def test_created_is_immediate(self):
        scheduler, scanner = self._run_and_flush([
            ('created', 'new.png'),
        ])
        assert scanner.request_update.called

    def test_created_then_modified_stays_ready(self):
        scheduler, scanner = self._run_and_flush([
            ('created', 'dl.png'),
            ('changed', 'dl.png'),
        ])
        assert scanner.request_update.called

    def test_modified_does_not_override_ready(self):
        scheduler, scanner = self._run_and_flush([
            ('created', 'x.png'),
            ('changed', 'x.png'),
            ('changed', 'x.png'),
        ])
        assert scanner.request_update.called

    def test_created_then_deleted(self):
        scheduler, scanner = self._run_and_flush([
            ('created', 'tmp.png'),
            ('deleted', 'tmp.png'),
        ])
        ops = [c[0][0].name for c in scheduler.submit.call_args_list]
        assert 'delete_sources' in ops
        assert not scanner.request_update.called

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

    def test_created_then_moved_triggers_update(self):
        scheduler, scanner = self._run_and_flush([
            ('created', 'a.tmp'),
            ('changed', 'a.tmp'),
            ('moved', ('a.tmp', 'a.png')),
        ])
        ops = [c[0][0].name for c in scheduler.submit.call_args_list]
        assert 'rename_paths' not in ops
        paths = scanner.request_update.call_args[0][0]
        assert any('a.png' in p for p in paths)

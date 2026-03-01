import py_compile
from unittest.mock import MagicMock


def test_compile():
    py_compile.compile('afterimages/app/indexer/watch_folder.py')


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
    from afterimages.app.indexer.watch_folder import FolderWatcher
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
    assert len(changed) == 0
    assert len(moved) == 0


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

import os
from pathlib import Path

from wafer.core.platform.file_operations import (
    FileExecutor,
    OperationResult,
    PastePlanItem,
    PasteDecision,
    _safe_remove,
)


def _write_file(path, content="hello"):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TestFileExecutorCopy:
    def test_copy_single_file(self, tmp_path):
        src = _write_file(tmp_path / "src" / "a.txt", "content_a")
        dst = tmp_path / "dst" / "a.txt"
        plans = [PastePlanItem(index=0, src=src, is_dir=False, action="copy", dst_default=dst, conflict=False, suggested_dst=None)]
        decisions = {0: PasteDecision(mode="create")}
        executor = FileExecutor()
        results = executor.execute_plans(plans, decisions)
        assert len(results) == 1
        assert results[0].status == "ok"
        assert dst.read_text(encoding="utf-8") == "content_a"
        assert src.exists()

    def test_copy_directory(self, tmp_path):
        src_dir = tmp_path / "src" / "mydir"
        _write_file(src_dir / "inner.txt", "inside")
        dst_dir = tmp_path / "dst" / "mydir"
        plans = [PastePlanItem(index=0, src=src_dir, is_dir=True, action="copy", dst_default=dst_dir, conflict=False, suggested_dst=None)]
        decisions = {0: PasteDecision(mode="create")}
        executor = FileExecutor()
        results = executor.execute_plans(plans, decisions)
        assert results[0].status == "ok"
        assert (dst_dir / "inner.txt").read_text(encoding="utf-8") == "inside"
        assert src_dir.exists()


class TestFileExecutorCut:
    def test_cut_moves_file(self, tmp_path):
        src = _write_file(tmp_path / "src" / "move_me.txt", "data")
        dst = tmp_path / "dst" / "move_me.txt"
        plans = [PastePlanItem(index=0, src=src, is_dir=False, action="cut", dst_default=dst, conflict=False, suggested_dst=None)]
        decisions = {0: PasteDecision(mode="create")}
        executor = FileExecutor()
        results = executor.execute_plans(plans, decisions)
        assert results[0].status == "ok"
        assert dst.read_text(encoding="utf-8") == "data"
        assert not src.exists()


class TestFileExecutorConflict:
    def test_skip_decision(self, tmp_path):
        src = _write_file(tmp_path / "src" / "a.txt", "new")
        dst = _write_file(tmp_path / "dst" / "a.txt", "old")
        plans = [PastePlanItem(index=0, src=src, is_dir=False, action="copy", dst_default=dst, conflict=True, suggested_dst=None)]
        decisions = {0: PasteDecision(mode="skip")}
        executor = FileExecutor()
        results = executor.execute_plans(plans, decisions)
        assert results[0].status == "skipped"
        assert dst.read_text(encoding="utf-8") == "old"

    def test_overwrite_decision(self, tmp_path):
        src = _write_file(tmp_path / "src" / "a.txt", "new_content")
        dst = _write_file(tmp_path / "dst" / "a.txt", "old_content")
        plans = [PastePlanItem(index=0, src=src, is_dir=False, action="copy", dst_default=dst, conflict=True, suggested_dst=None)]
        executor = FileExecutor(ask_conflict=lambda conflict: "overwrite")
        results = executor.execute_plans(plans, {})
        assert results[0].status == "ok"
        assert dst.read_text(encoding="utf-8") == "new_content"

    def test_rename_decision(self, tmp_path):
        src = _write_file(tmp_path / "src" / "a.txt", "renamed")
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir(parents=True, exist_ok=True)
        _write_file(dst_dir / "a.txt", "existing")
        new_dst = dst_dir / "a_copy.txt"

        plans = [PastePlanItem(index=0, src=src, is_dir=False, action="copy", dst_default=dst_dir / "a.txt", conflict=True, suggested_dst=None)]
        decisions = {0: PasteDecision(mode="rename", new_name_or_path=str(new_dst))}
        executor = FileExecutor()
        results = executor.execute_plans(plans, decisions)
        assert results[0].status == "ok"
        assert new_dst.read_text(encoding="utf-8") == "renamed"
        assert (dst_dir / "a.txt").read_text(encoding="utf-8") == "existing"

    def test_no_decision_pastes_and_keeps_an_existing_file(self, tmp_path):
        src = _write_file(tmp_path / "src" / "a.txt", "data")
        dst = _write_file(tmp_path / "dst" / "a.txt", "existing")
        plans = [PastePlanItem(index=0, src=src, is_dir=False, action="copy", dst_default=dst, conflict=False, suggested_dst=None)]
        executor = FileExecutor()
        results = executor.execute_plans(plans, decisions={})
        assert results[0].status == "ok"
        assert dst.read_text(encoding="utf-8") == "existing"
        assert Path(results[0].dst).read_text(encoding="utf-8") == "data"


class TestFileExecutorMultiFile:
    def test_multiple_files(self, tmp_path):
        files = []
        for i in range(5):
            src = _write_file(tmp_path / "src" / f"file_{i}.txt", f"content_{i}")
            dst = tmp_path / "dst" / f"file_{i}.txt"
            files.append((src, dst))

        plans = [PastePlanItem(index=i, src=src, is_dir=False, action="copy", dst_default=dst, conflict=False, suggested_dst=None) for i, (src, dst) in enumerate(files)]
        decisions = {i: PasteDecision(mode="create") for i in range(5)}

        executor = FileExecutor()
        results = executor.execute_plans(plans, decisions)
        assert all(r.status == "ok" for r in results)
        for i, (_, dst) in enumerate(files):
            assert dst.read_text(encoding="utf-8") == f"content_{i}"


class TestMergeAsksAtEachConflict:
    def _merge(self, src, dst):
        asked = []

        def ask(conflict):
            asked.append(conflict)
            return "merge" if conflict.folders else "skip"

        plans = [PastePlanItem(index=0, src=src, is_dir=True, action="copy", dst_default=dst, conflict=True, suggested_dst=None)]
        results = FileExecutor(ask_conflict=ask).execute_plans(plans, {})
        return results, asked

    def test_files_without_a_conflict_are_added_without_asking(self, tmp_path):
        src = tmp_path / "src_dir"
        dst = tmp_path / "dst_dir"
        _write_file(src / "a.txt", "a")
        dst.mkdir()
        results, asked = self._merge(src, dst)
        assert results[0].status == "ok"
        assert [c.folders for c in asked] == [True]
        assert (dst / "a.txt").read_text(encoding="utf-8") == "a"

    def test_a_nested_conflict_is_asked_where_it_is_found(self, tmp_path):
        src = tmp_path / "src_dir"
        dst = tmp_path / "dst_dir"
        _write_file(src / "sub" / "nested.txt", "src")
        _write_file(dst / "sub" / "nested.txt", "dst")
        results, asked = self._merge(src, dst)
        assert results[0].status == "ok"
        assert [(c.dst, c.in_merge, c.from_this_paste) for c in asked[1:]] == [(dst / "sub" / "nested.txt", True, False)]
        assert (dst / "sub" / "nested.txt").read_text(encoding="utf-8") == "dst"


class TestSafeRemove:
    def test_remove_file(self, tmp_path):
        f = _write_file(tmp_path / "del.txt")
        _safe_remove(f)
        assert not f.exists()

    def test_remove_directory(self, tmp_path):
        d = tmp_path / "deldir"
        _write_file(d / "inner.txt")
        _safe_remove(d)
        assert not d.exists()

    def test_remove_nonexistent(self, tmp_path):
        _safe_remove(tmp_path / "ghost.txt")

import os
from pathlib import Path

from wafer.core.platform.file_operations import (
    FileExecutor,
    OperationResult,
    PastePlanItem,
    PasteDecision,
    MergeConflictItem,
    scan_merge_conflicts,
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
        decisions = {0: PasteDecision(mode="overwrite")}
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
        decisions = {0: PasteDecision(mode="overwrite")}
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
        decisions = {0: PasteDecision(mode="overwrite")}
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
        decisions = {0: PasteDecision(mode="overwrite")}
        executor = FileExecutor()
        results = executor.execute_plans(plans, decisions)
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

    def test_no_decision_defaults_skip(self, tmp_path):
        src = _write_file(tmp_path / "src" / "a.txt", "data")
        dst = tmp_path / "dst" / "a.txt"
        plans = [PastePlanItem(index=0, src=src, is_dir=False, action="copy", dst_default=dst, conflict=False, suggested_dst=None)]
        executor = FileExecutor()
        results = executor.execute_plans(plans, decisions={})
        assert results[0].status == "skipped"


class TestFileExecutorMultiFile:
    def test_multiple_files(self, tmp_path):
        files = []
        for i in range(5):
            src = _write_file(tmp_path / "src" / f"file_{i}.txt", f"content_{i}")
            dst = tmp_path / "dst" / f"file_{i}.txt"
            files.append((src, dst))

        plans = [PastePlanItem(index=i, src=src, is_dir=False, action="copy", dst_default=dst, conflict=False, suggested_dst=None) for i, (src, dst) in enumerate(files)]
        decisions = {i: PasteDecision(mode="overwrite") for i in range(5)}

        executor = FileExecutor()
        results = executor.execute_plans(plans, decisions)
        assert all(r.status == "ok" for r in results)
        for i, (_, dst) in enumerate(files):
            assert dst.read_text(encoding="utf-8") == f"content_{i}"


class TestScanMergeConflicts:
    def test_no_conflicts(self, tmp_path):
        src = tmp_path / "src_dir"
        dst = tmp_path / "dst_dir"
        _write_file(src / "a.txt", "a")
        dst.mkdir()
        conflicts = scan_merge_conflicts(src, dst)
        assert conflicts == []

    def test_file_conflict_detected(self, tmp_path):
        src = tmp_path / "src_dir"
        dst = tmp_path / "dst_dir"
        _write_file(src / "same.txt", "from_src")
        _write_file(dst / "same.txt", "from_dst")
        conflicts = scan_merge_conflicts(src, dst)
        assert len(conflicts) == 1
        assert conflicts[0].rel_path == "same.txt"
        assert not conflicts[0].is_dir

    def test_nested_conflict(self, tmp_path):
        src = tmp_path / "src_dir"
        dst = tmp_path / "dst_dir"
        _write_file(src / "sub" / "nested.txt", "src")
        _write_file(dst / "sub" / "nested.txt", "dst")
        conflicts = scan_merge_conflicts(src, dst)
        rel_paths = [c.rel_path for c in conflicts]
        assert any("nested.txt" in r for r in rel_paths)


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

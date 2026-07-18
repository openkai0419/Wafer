import hashlib
import shutil
import zipfile

import pytest

from wafer.builtins.updater import stage
from wafer.builtins.updater.plan import plan_path, read_plan
from wafer.builtins.updater.stage import StageCancelled, StageError
from wafer.utils.process_lock import file_lock


ZIP_NAME = "Wafer-v2.0.0.zip"

STAGED_FILES = {
    "python/wafer-pythonw.exe": "new-python",
    "main.py": "new-main",
    "Wafer.exe": "new-launcher",
    "Uninstaller.exe": "new-uninstaller",
    "wafer/_version.py": 'FALLBACK_VERSION = "2.0.0"\n',
    "extensions/image/__init__.py": "new-image",
}


def make_zip(path, files=STAGED_FILES):
    with zipfile.ZipFile(path, "w") as zf:
        for rel, content in files.items():
            zf.writestr(rel, content)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_release(with_manifest=True):
    assets = [{"name": ZIP_NAME, "browser_download_url": f"https://github.com/o/r/releases/download/v2.0.0/{ZIP_NAME}"}]
    if with_manifest:
        assets.insert(0, {"name": "manifest.json", "browser_download_url": "https://github.com/o/r/releases/download/v2.0.0/manifest.json"})
    return {"tag_name": "v2.0.0", "assets": assets}


def make_manifest(sha256, version="2.0.0"):
    return {"schema": 1, "version": version, "assets": [{"name": ZIP_NAME, "kind": "full", "sha256": sha256, "size": 1}]}


@pytest.fixture
def app_root(tmp_path, monkeypatch):
    root = tmp_path / "app"
    root.mkdir()
    (root / "extensions").mkdir()
    monkeypatch.setattr(stage, "get_app_root_dir", lambda: root)
    return root


@pytest.fixture
def fake_network(app_root, tmp_path, monkeypatch):
    zip_src = tmp_path / ZIP_NAME
    sha = make_zip(zip_src)
    manifest = make_manifest(sha)
    monkeypatch.setattr(stage, "read_cached_latest_release", lambda: make_release())
    monkeypatch.setattr(stage, "fetch_json", lambda url, **kw: manifest)

    def fake_download(url, dest, *, expected_sha256=None, on_progress=None, **kw):
        if on_progress:
            on_progress(50, 100)
            on_progress(100, 100)
        shutil.copy(zip_src, dest)
        assert expected_sha256 == sha

    monkeypatch.setattr(stage, "safe_download", fake_download)
    return {"sha": sha, "manifest": manifest, "zip_src": zip_src}


class TestUpdateMode:
    def test_portable(self, app_root, monkeypatch):
        monkeypatch.setattr(stage, "get_launcher_path", lambda: app_root / "Wafer.exe")
        assert stage.update_mode() == "portable"

    def test_git(self, app_root, monkeypatch):
        monkeypatch.setattr(stage, "get_launcher_path", lambda: None)
        (app_root / ".git").mkdir()
        assert stage.update_mode() == "git"

    def test_non_portable_defaults_to_git(self, app_root, monkeypatch):
        monkeypatch.setattr(stage, "get_launcher_path", lambda: None)
        assert stage.update_mode() == "git"


class TestStageUpdate:
    def test_happy_path(self, app_root, fake_network):
        progress = []
        version = stage.stage_update("v2.0.0", "2.0.0", on_progress=lambda d, t: progress.append((d, t)))

        assert version == "2.0.0"
        assert stage.staged_version() == "2.0.0"
        ops = read_plan(plan_path(app_root))
        assert ops
        assert (app_root / ".update/next/main.py").read_text(encoding="utf-8") == "new-main"
        assert not list((app_root / ".update/download").glob("*.zip"))
        assert progress

    def test_no_manifest_raises(self, app_root, monkeypatch):
        monkeypatch.setattr(stage, "read_cached_latest_release", lambda: make_release(with_manifest=False))
        with pytest.raises(StageError, match="does not support"):
            stage.stage_update("v2.0.0", "2.0.0")

    def test_release_cache_mismatch_raises(self, app_root, monkeypatch):
        monkeypatch.setattr(stage, "read_cached_latest_release", lambda: {"tag_name": "v1.5.0", "assets": []})
        with pytest.raises(StageError, match="outdated"):
            stage.stage_update("v2.0.0", "2.0.0")

    def test_manifest_version_mismatch_raises(self, app_root, fake_network, monkeypatch):
        monkeypatch.setattr(stage, "fetch_json", lambda url, **kw: make_manifest(fake_network["sha"], version="9.9.9"))
        with pytest.raises(StageError, match="version mismatch"):
            stage.stage_update("v2.0.0", "2.0.0")

    def test_staged_package_version_mismatch_raises(self, app_root, fake_network, tmp_path, monkeypatch):
        files = dict(STAGED_FILES, **{"wafer/_version.py": 'FALLBACK_VERSION = "9.9.9"\n'})
        zip_src = tmp_path / "bad.zip"
        sha = make_zip(zip_src, files)
        monkeypatch.setattr(stage, "fetch_json", lambda url, **kw: make_manifest(sha))

        def fake_download(url, dest, **kw):
            shutil.copy(zip_src, dest)

        monkeypatch.setattr(stage, "safe_download", fake_download)
        with pytest.raises(StageError, match="version mismatch"):
            stage.stage_update("v2.0.0", "2.0.0")
        assert stage.staged_version() == ""
        assert not (app_root / ".update/next").exists()

    def test_incomplete_package_raises_and_cleans(self, app_root, fake_network, tmp_path, monkeypatch):
        files = {k: v for k, v in STAGED_FILES.items() if k != "main.py"}
        zip_src = tmp_path / "incomplete.zip"
        sha = make_zip(zip_src, files)
        monkeypatch.setattr(stage, "fetch_json", lambda url, **kw: make_manifest(sha))
        monkeypatch.setattr(stage, "safe_download", lambda url, dest, **kw: shutil.copy(zip_src, dest))
        with pytest.raises(StageError, match="incomplete"):
            stage.stage_update("v2.0.0", "2.0.0")
        assert not (app_root / ".update/next").exists()

    def test_cancel_cleans_staging(self, app_root, fake_network):
        with pytest.raises(StageCancelled):
            stage.stage_update("v2.0.0", "2.0.0", is_cancelled=lambda: True)
        assert stage.staged_version() == ""
        assert not (app_root / ".update/next").exists()
        assert not (app_root / ".update/download").exists()

    def test_concurrent_stage_rejected(self, app_root, fake_network):
        lock_path = app_root / ".update" / stage.STAGE_LOCK_FILENAME
        with file_lock(str(lock_path), timeout=1):
            with pytest.raises(StageError, match="already in progress"):
                stage.stage_update("v2.0.0", "2.0.0")

    def test_download_timeout_not_reported_as_concurrent(self, app_root, fake_network, monkeypatch):
        def timing_out_download(url, dest, **kw):
            raise TimeoutError("network timed out")

        monkeypatch.setattr(stage, "safe_download", timing_out_download)
        with pytest.raises(TimeoutError, match="network timed out"):
            stage.stage_update("v2.0.0", "2.0.0")
        assert stage.staged_version() == ""


class TestStagedState:
    def test_empty_without_files(self, app_root):
        assert stage.staged_version() == ""

    def test_discard_staged(self, app_root, fake_network):
        stage.stage_update("v2.0.0", "2.0.0")
        assert stage.staged_version() == "2.0.0"
        stage.discard_staged()
        assert stage.staged_version() == ""
        assert not (app_root / ".update/next").exists()


class TestProcessApplyResults:
    def test_applied_notifies_and_cleans(self, app_root):
        base = app_root / ".update"
        base.mkdir()
        (base / "applied.txt").write_text("2.0.0", encoding="utf-8")
        stage.process_apply_results()
        assert not (base / "applied.txt").exists()

    def test_failed_notifies_and_cleans(self, app_root):
        base = app_root / ".update"
        base.mkdir()
        (base / "failed.txt").write_text("boom", encoding="utf-8")
        stage.process_apply_results()
        assert not (base / "failed.txt").exists()

    def test_stale_ready_discarded(self, app_root, fake_network, monkeypatch):
        stage.stage_update("v2.0.0", "2.0.0")
        monkeypatch.setattr(stage, "effective_current_version", lambda: "2.0.0")
        stage.process_apply_results()
        assert stage.staged_version() == ""

    def test_pending_newer_ready_kept(self, app_root, fake_network, monkeypatch):
        stage.stage_update("v2.0.0", "2.0.0")
        monkeypatch.setattr(stage, "effective_current_version", lambda: "1.0.0")
        stage.process_apply_results()
        assert stage.staged_version() == "2.0.0"

    def test_applied_processed_once_under_concurrency(self, app_root, monkeypatch):
        base = app_root / ".update"
        base.mkdir()
        (base / "applied.txt").write_text("2.0.0", encoding="utf-8")
        notes = []
        monkeypatch.setattr(stage.Notifier, "info", staticmethod(lambda msg: notes.append(msg)))
        stage.process_apply_results()
        stage.process_apply_results()
        assert notes == ["Updated to v2.0.0"]


class TestClaimResultFile:
    def test_claims_content_once(self, tmp_path):
        target = tmp_path / "applied.txt"
        target.write_text("2.0.0", encoding="utf-8")
        assert stage.claim_result_file(target) == "2.0.0"
        assert not target.exists()
        assert stage.claim_result_file(target) is None

    def test_missing_returns_none(self, tmp_path):
        assert stage.claim_result_file(tmp_path / "absent.txt") is None


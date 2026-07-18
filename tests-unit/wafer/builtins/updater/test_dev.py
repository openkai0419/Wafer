import hashlib
import json
import zipfile

import pytest

import wafer._dev as _dev
from wafer.builtins.updater import service, stage


ZIP_NAME = "Wafer-v2.0.0.zip"

STAGED_FILES = {
    "python/wafer-pythonw.exe": "new-python",
    "main.py": "new-main",
    "Wafer.exe": "new-launcher",
    "Uninstaller.exe": "new-uninstaller",
    "wafer/_version.py": 'FALLBACK_VERSION = "2.0.0"\n',
    "extensions/image/__init__.py": "new-image",
}


@pytest.fixture
def source_dir(tmp_path, monkeypatch):
    src = tmp_path / "update_source"
    src.mkdir()
    monkeypatch.setenv(_dev.SOURCE_DIR_ENV, str(src))
    monkeypatch.setattr(_dev, "FORCE_UPDATE_ENABLED", True)
    return src


def write_source(src):
    zip_path = src / ZIP_NAME
    with zipfile.ZipFile(zip_path, "w") as zf:
        for rel, content in STAGED_FILES.items():
            zf.writestr(rel, content)
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    manifest = {"schema": 1, "version": "2.0.0", "assets": [{"name": ZIP_NAME, "kind": "full", "sha256": sha, "size": zip_path.stat().st_size}]}
    (src / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    latest = {"tag_name": "v2.0.0", "assets": [{"name": "manifest.json"}, {"name": ZIP_NAME}]}
    (src / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    return sha


class TestLocalSource:
    def test_fetch_latest_release_reads_local(self, source_dir):
        write_source(source_dir)
        release = service.fetch_latest_release()
        assert release["tag_name"] == "v2.0.0"

    def test_fetch_latest_release_missing_raises(self, source_dir):
        with pytest.raises(ValueError, match="latest.json"):
            service.fetch_latest_release()

    def test_fetch_manifest_reads_local(self, source_dir):
        write_source(source_dir)
        release = {"tag_name": "v2.0.0", "assets": []}
        manifest = stage._fetch_manifest(release)
        assert manifest["version"] == "2.0.0"

    def test_stage_update_copies_local_package(self, source_dir, tmp_path, monkeypatch):
        write_source(source_dir)
        app_root = tmp_path / "app"
        (app_root / "extensions").mkdir(parents=True)
        monkeypatch.setattr(stage, "get_app_root_dir", lambda: app_root)
        monkeypatch.setattr(stage, "read_cached_latest_release", lambda: {"tag_name": "v2.0.0", "assets": []})

        progress = []
        version = stage.stage_update("v2.0.0", "2.0.0", on_progress=lambda d, t: progress.append((d, t)))

        assert version == "2.0.0"
        assert stage.staged_version() == "2.0.0"
        assert (app_root / ".update/next/main.py").read_text(encoding="utf-8") == "new-main"
        assert progress

    def test_stage_update_sha256_mismatch_raises(self, source_dir, tmp_path, monkeypatch):
        write_source(source_dir)
        bad = {"schema": 1, "version": "2.0.0", "assets": [{"name": ZIP_NAME, "kind": "full", "sha256": "0" * 64, "size": 1}]}
        (source_dir / "manifest.json").write_text(json.dumps(bad), encoding="utf-8")
        app_root = tmp_path / "app"
        (app_root / "extensions").mkdir(parents=True)
        monkeypatch.setattr(stage, "get_app_root_dir", lambda: app_root)
        monkeypatch.setattr(stage, "read_cached_latest_release", lambda: {"tag_name": "v2.0.0", "assets": []})

        with pytest.raises(stage.StageError, match="SHA256 mismatch"):
            stage.stage_update("v2.0.0", "2.0.0")
        assert stage.staged_version() == ""

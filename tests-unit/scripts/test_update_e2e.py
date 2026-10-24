import json
import shutil
import zipfile
from pathlib import Path

import pytest

from scripts import update_e2e
from scripts.make_local_update import write_update_source

ROOT = Path(__file__).resolve().parents[2]


def make_release(root: Path) -> Path:
    files = {
        "Wafer.exe": "launcher",
        "main.py": "main",
        "wafer/_version.py": 'FALLBACK_VERSION = "0.7.3.dev4+gabc1234"\n',
        "wafer/__pycache__/x.pyc": "cache",
        "python/Lib/site.py": "site",
        "extensions/ffmpeg/__init__.py": "ffmpeg",
        "extensions/ffmpeg/lib/ffmpeg.exe": "binary",
        "extensions/.packages/numpy/__init__.py": "numpy",
        "extensions/.pending/queue.json": "{}",
        ".update/next/main.py": "staged",
    }
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    shutil.copy(ROOT / "wafer" / "_dev.py", root / "wafer" / "_dev.py")
    return root


def test_next_version_bumps_the_patch_of_a_dev_build():
    assert update_e2e.next_version("0.7.3.dev4+gabc1234") == "0.7.4"
    assert update_e2e.next_version("v1.2.9") == "1.2.10"


def test_next_version_rejects_a_non_release_string():
    with pytest.raises(update_e2e.E2EFailure):
        update_e2e.next_version("dev")


def test_fallback_version_round_trips(tmp_path):
    root = make_release(tmp_path / "app")
    assert update_e2e.read_fallback_version(root) == "0.7.3.dev4+gabc1234"
    update_e2e.set_fallback_version(root, "0.7.4")
    assert update_e2e.read_fallback_version(root) == "0.7.4"


def test_force_local_updates_turns_on_the_real_dev_switch(tmp_path):
    root = make_release(tmp_path / "app")
    update_e2e.force_local_updates(root)
    text = (root / "wafer" / "_dev.py").read_text(encoding="utf-8")
    assert "\nFORCE_UPDATE_ENABLED = True\n" in text
    assert "\nFORCE_UPDATE_ENABLED = False\n" not in text


def test_force_local_updates_fails_loudly_when_the_switch_moved(tmp_path):
    root = make_release(tmp_path / "app")
    (root / "wafer" / "_dev.py").write_text("FORCE = False\n", encoding="utf-8")
    with pytest.raises(update_e2e.E2EFailure):
        update_e2e.force_local_updates(root)


def test_copy_release_leaves_out_what_a_release_never_ships(tmp_path):
    dist = make_release(tmp_path / "dist")
    copy = tmp_path / "copy"
    update_e2e.copy_release(dist, copy)
    assert (copy / "extensions/ffmpeg/__init__.py").is_file()
    assert (copy / "python/Lib/site.py").is_file()
    assert not (copy / "extensions/ffmpeg/lib").exists()
    assert not (copy / "extensions/.packages").exists()
    assert not (copy / "extensions/.pending").exists()
    assert not (copy / "wafer/__pycache__").exists()
    assert not (copy / ".update").exists()


def test_seeded_markers_are_reported_until_they_go_missing(tmp_path):
    root = tmp_path / "app"
    update_e2e.seed_markers(root)
    assert update_e2e.missing_markers(root) == []
    (root / update_e2e.LIB_MARKER).unlink()
    assert update_e2e.missing_markers(root) == [update_e2e.LIB_MARKER]


def test_isolated_env_points_app_data_and_update_source_into_the_work_folder(tmp_path):
    env = update_e2e.isolated_env(tmp_path)
    assert env["WIN_PD_OVERRIDE_LOCAL_APPDATA"] == str(tmp_path / "appdata")
    assert env["WAFER_UPDATE_SOURCE_DIR"] == str(tmp_path / "source")
    assert env["WAFER_UPDATE_BUSY_ACTION"] == "skip"
    assert "QT_QPA_PLATFORM" not in env
    assert Path(env["TEMP"]).is_dir()


def test_write_update_source_produces_what_the_dev_updater_reads(tmp_path):
    dist = make_release(tmp_path / "dist")
    out = tmp_path / "source"
    zip_path = write_update_source(dist, out, "0.7.4")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.7.4"
    assert manifest["assets"][0]["name"] == zip_path.name
    assert latest["tag_name"] == "v0.7.4"
    with zipfile.ZipFile(zip_path) as zf:
        assert "main.py" in zf.namelist()


def test_run_refuses_without_a_build(tmp_path, capsys):
    assert update_e2e.run(tmp_path / "missing", keep=False) == 1
    assert "Run scripts/build.py first" in capsys.readouterr().err


def test_a_driver_that_hangs_is_reported_as_an_e2e_failure(tmp_path, monkeypatch):
    def hang(cmd, **kwargs):
        raise update_e2e.subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(update_e2e.subprocess, "run", hang)
    with pytest.raises(update_e2e.E2EFailure, match="staging did not finish"):
        update_e2e.run_driver(tmp_path, {}, "pass", "staging")

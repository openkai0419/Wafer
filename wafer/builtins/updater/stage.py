from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from contextlib import ExitStack
from pathlib import Path

from ...utils.downloader import fetch_json, safe_download, validate_archive_path
from ...utils.hashes import verify_sha256
from ...utils.json_io import read_json_file, write_json_file
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from ...utils.paths import get_app_root_dir, get_launcher_path
from ...utils.process_lock import file_lock
from ... import _dev
from . import plan as update_plan
from .service import MANIFEST_ASSET_NAME, USER_AGENT, effective_current_version, read_cached_latest_release
from .versioning import is_newer_version, normalize_version


MANIFEST_SCHEMA = 1
STAGE_LOCK_FILENAME = "stage.lock"
_ASSET_HOSTS = ("github.com", "objects.githubusercontent.com")
_MANIFEST_MAX_BYTES = 64 * 1024
_REQUIRED_STAGED_ENTRIES = ("python/wafer-pythonw.exe", "main.py", "wafer/_version.py", "Wafer.exe", "Uninstaller.exe", "extensions")
_FALLBACK_VERSION_RE = re.compile(r'FALLBACK_VERSION\s*=\s*"([^"]+)"')


class StageError(Exception):
    pass


class StageCancelled(Exception):
    pass


def update_mode() -> str:
    if get_launcher_path():
        return "portable"
    return "git"


def ready_path(app_root: str | Path | None = None) -> Path:
    root = Path(app_root) if app_root else get_app_root_dir()
    return update_plan.update_dir(root) / update_plan.READY_FILENAME


def staged_version(app_root: str | Path | None = None) -> str:
    root = Path(app_root) if app_root else get_app_root_dir()
    if not update_plan.plan_path(root).is_file():
        return ""
    data = read_json_file(ready_path(root), default=None)
    if not isinstance(data, dict):
        return ""
    return normalize_version(str(data.get("target_version", "")))


def discard_staged(app_root: str | Path | None = None) -> None:
    root = Path(app_root) if app_root else get_app_root_dir()
    for path in (update_plan.plan_path(root), ready_path(root)):
        path.unlink(missing_ok=True)
    for directory in (update_plan.next_dir(root), update_plan.download_dir(root)):
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)


def stage_update(target_tag: str, target_version: str, *, on_progress=None, is_cancelled=None) -> str:
    root = get_app_root_dir()
    lock_path = update_plan.update_dir(root) / STAGE_LOCK_FILENAME
    stack = ExitStack()
    try:
        stack.enter_context(file_lock(str(lock_path), timeout=0.2))
    except TimeoutError as exc:
        raise StageError("Another update download is already in progress") from exc
    with stack:
        try:
            return _stage_locked(root, target_tag, target_version, on_progress, is_cancelled)
        except Exception:
            discard_staged(root)
            raise


def _check_cancelled(is_cancelled) -> None:
    if is_cancelled is not None and is_cancelled():
        raise StageCancelled("Update download cancelled")


def _stage_locked(root: Path, target_tag: str, target_version: str, on_progress, is_cancelled) -> str:
    release = read_cached_latest_release()
    if not isinstance(release, dict) or normalize_version(str(release.get("tag_name", ""))) != normalize_version(target_tag):
        raise StageError("Cached release info is outdated. Run the update check again")

    manifest = _fetch_manifest(release)
    version = normalize_version(str(manifest.get("version", "")))
    if version != normalize_version(target_version):
        raise StageError(f"Update manifest version mismatch: expected {target_version}, got {manifest.get('version')}")

    full_asset = next((a for a in manifest.get("assets", []) if isinstance(a, dict) and a.get("kind") == "full"), None)
    if not full_asset or not full_asset.get("name") or not full_asset.get("sha256"):
        raise StageError("Update manifest has no downloadable package")

    _check_cancelled(is_cancelled)
    downloads = update_plan.download_dir(root)
    if downloads.is_dir():
        shutil.rmtree(downloads)
    downloads.mkdir(parents=True, exist_ok=True)
    zip_path = downloads / str(full_asset["name"])

    def progress_hook(done: int, total: int) -> None:
        _check_cancelled(is_cancelled)
        if on_progress is not None:
            on_progress(done, total)

    _acquire_package(release, str(full_asset["name"]), zip_path, str(full_asset["sha256"]), version, progress_hook)

    _check_cancelled(is_cancelled)
    staged = update_plan.next_dir(root)
    _extract_zip(zip_path, staged, is_cancelled)
    zip_path.unlink(missing_ok=True)

    _verify_staged(staged, version)
    _check_cancelled(is_cancelled)

    ops = update_plan.generate_plan(root)
    update_plan.write_plan(update_plan.plan_path(root), ops)
    write_json_file(ready_path(root), {"schema": 1, "target_version": version, "staged_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    AppLogger.info(f"[Updater] Update v{version} staged ({len(ops)} plan operations). Restart to apply")
    return version


def _fetch_manifest(release: dict) -> dict:
    if _dev.FORCE_UPDATE_ENABLED:
        manifest = read_json_file(_dev.asset(MANIFEST_ASSET_NAME), default=None)
    else:
        url = _release_asset_url(release, MANIFEST_ASSET_NAME)
        if not url:
            raise StageError("This release does not support in-app update. Use the download page instead")
        manifest = fetch_json(url, allowed_hosts=_ASSET_HOSTS, max_bytes=_MANIFEST_MAX_BYTES, user_agent=USER_AGENT)
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise StageError("Unsupported update manifest schema")
    return manifest


def _acquire_package(release: dict, name: str, dest: Path, sha256: str, version: str, progress_hook) -> None:
    if _dev.FORCE_UPDATE_ENABLED:
        source = _dev.asset(name)
        AppLogger.info(f"[Updater] [DEV] Copying update package v{version} from {source}")
        if not source.is_file():
            raise StageError(f"Local update package not found: {source}")
        shutil.copy(source, dest)
        if not verify_sha256(str(dest), sha256):
            raise StageError(f"SHA256 mismatch for {name}")
        size = dest.stat().st_size
        progress_hook(size, size)
        return
    url = _release_asset_url(release, name)
    if not url:
        raise StageError(f"Release asset not found: {name}")
    AppLogger.info(f"[Updater] Downloading update package v{version} from {url}")
    safe_download(url, str(dest), allowed_hosts=_ASSET_HOSTS, expected_sha256=sha256, on_progress=progress_hook, user_agent=USER_AGENT)


def _release_asset_url(release: dict, name: str) -> str:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return ""
    for asset in assets:
        if isinstance(asset, dict) and asset.get("name") == name:
            return str(asset.get("browser_download_url") or "")
    return ""


def _extract_zip(zip_path: Path, staged: Path, is_cancelled) -> None:
    if staged.is_dir():
        shutil.rmtree(staged)
    staged.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            validate_archive_path(member, str(staged))
        _check_cancelled(is_cancelled)
        zf.extractall(staged)


def _verify_staged(staged: Path, version: str) -> None:
    missing = [entry for entry in _REQUIRED_STAGED_ENTRIES if not (staged / entry).exists()]
    if missing:
        raise StageError(f"Staged update is incomplete, missing: {', '.join(missing)}")
    match = _FALLBACK_VERSION_RE.search((staged / "wafer" / "_version.py").read_text(encoding="utf-8"))
    staged_ver = normalize_version(match.group(1)) if match else ""
    if staged_ver != version:
        raise StageError(f"Staged package version mismatch: expected {version}, got {staged_ver or 'unknown'}")


def claim_result_file(path: Path) -> str | None:
    claimed = path.with_name(path.name + ".claimed")
    try:
        os.replace(path, claimed)
    except OSError:
        return None
    try:
        return claimed.read_text(encoding="utf-8").strip()
    finally:
        claimed.unlink(missing_ok=True)


def process_apply_results() -> None:
    root = get_app_root_dir()
    base = update_plan.update_dir(root)
    version = claim_result_file(base / update_plan.APPLIED_FILENAME)
    if version is not None:
        AppLogger.info(f"[Updater] Update applied successfully: v{version}")
        Notifier.info(f"Updated to v{version}")
        discard_staged(root)
        return
    detail = claim_result_file(base / update_plan.FAILED_FILENAME)
    if detail is not None:
        AppLogger.error(f"[Updater] Update apply failed and was rolled back: {detail}. See {base / update_plan.APPLY_LOG_FILENAME} for details")
        Notifier.error("Update failed. Previous version was restored")
        discard_staged(root)
        return
    version = staged_version(root)
    if version and not is_newer_version(effective_current_version(), version):
        AppLogger.info(f"[Updater] Discarding stale staged update v{version} (current v{effective_current_version()})")
        discard_staged(root)


def restart_into_launcher(main_window) -> bool:
    launcher = get_launcher_path()
    if launcher is None or not staged_version():
        return False
    from ...core.platform.process import AppProcess

    node = getattr(main_window, "_node", None)
    others = []
    if node:
        store = main_window._workspace_store
        active_ids = store.get_active_slot_ids()
        if active_ids:
            store.set_restore_slot_ids(active_ids)
        others = AppProcess.list_viewers()
        for sid in active_ids:
            if sid != main_window.slot_id:
                node.send("slot.shutdown", sid, dst="viewer")

    AppLogger.info("[Updater] Restarting through launcher to apply staged update")
    AppProcess.terminate_cmd("--tray", wait=True)
    AppProcess.wait_procs_then_kill(others)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    subprocess.Popen([str(launcher)], cwd=str(get_app_root_dir()), close_fds=True, creationflags=flags)
    main_window.close()
    return True

import json
import importlib
import os
import shutil
import subprocess
import tempfile
import urllib.request
from urllib.parse import urlparse

from wafer.utils.hashes import verify_sha256
from wafer.utils.logs import AppLogger


_SEVEN_ZR_URL = "https://www.7-zip.org/a/7zr.exe"
_LIB_VERSION_FILE = ".version"


def read_lib_version(marker_dir: str) -> str:
    try:
        with open(os.path.join(marker_dir, _LIB_VERSION_FILE), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def write_lib_version(marker_dir: str, version: str) -> None:
    if not version:
        return
    os.makedirs(marker_dir, exist_ok=True)
    with open(os.path.join(marker_dir, _LIB_VERSION_FILE), "w", encoding="utf-8") as f:
        f.write(version)


def lib_needs_download(marker_dir: str, version: str, *required_files: str) -> bool:
    if not all(os.path.isfile(p) for p in required_files):
        return True
    current = read_lib_version(marker_dir)
    return bool(version) and current != "" and current != version


def validate_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Insecure URL scheme: {parsed.scheme}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")
    if not any(hostname == h or hostname.endswith("." + h) for h in allowed_hosts):
        raise ValueError(f"Untrusted host: {hostname}")
    return url


def safe_download(url: str, dest: str, *, allowed_hosts: tuple[str, ...] | None = None, expected_sha256: str | None = None, on_progress=None, timeout: int = 30, user_agent: str | None = None) -> None:
    if allowed_hosts:
        validate_url(url, allowed_hosts)
    tmp_dest = dest + ".tmp"
    try:
        headers = {"User-Agent": user_agent} if user_agent else {}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp_dest, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if on_progress is not None:
                    on_progress(done, total)
        if expected_sha256 is not None:
            if not verify_sha256(tmp_dest, expected_sha256):
                raise RuntimeError(f"SHA256 mismatch for {os.path.basename(dest)}: expected {expected_sha256.lower()}")
        shutil.move(tmp_dest, dest)
    finally:
        if os.path.isfile(tmp_dest):
            try:
                os.remove(tmp_dest)
            except OSError:
                pass


def fetch_text(url: str, *, allowed_hosts: tuple[str, ...], max_bytes: int, user_agent: str, timeout: int = 30, extra_headers: dict[str, str] | None = None) -> str:
    validate_url(url, allowed_hosts)
    headers = {"User-Agent": user_agent}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise RuntimeError(f"Response too large from {url}: > {max_bytes} bytes")
    return body.decode("utf-8", errors="replace")


def fetch_json(url: str, *, allowed_hosts: tuple[str, ...], max_bytes: int, user_agent: str, timeout: int = 30, extra_headers: dict[str, str] | None = None):
    text = fetch_text(url, allowed_hosts=allowed_hosts, max_bytes=max_bytes, user_agent=user_agent, timeout=timeout, extra_headers=extra_headers)
    return json.loads(text)


def validate_archive_path(name: str, base_dir: str) -> None:
    resolved = os.path.normpath(os.path.join(base_dir, name))
    base = os.path.normpath(base_dir)
    if not resolved.startswith(base + os.sep) and resolved != base:
        raise ValueError(f"Path traversal detected: {name}")


def find_system_7z() -> str | None:
    if shutil.which("7z"):
        return "7z"
    for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
        prog_dir = os.environ.get(env_key, "")
        if prog_dir:
            path = os.path.join(prog_dir, "7-Zip", "7z.exe")
            if os.path.isfile(path):
                return path
    return None


def ensure_7zr(install_dir: str) -> str:
    path = os.path.join(install_dir, "7zr.exe")
    if os.path.isfile(path):
        return path
    os.makedirs(install_dir, exist_ok=True)
    AppLogger.info(f"[downloader] Downloading 7zr.exe from {_SEVEN_ZR_URL}")
    safe_download(_SEVEN_ZR_URL, path)
    AppLogger.info("[downloader] 7zr.exe downloaded")
    return path


def extract_7z_members(archive_path: str, target_dir: str, members: tuple[str, ...]) -> None:
    os.makedirs(target_dir, exist_ok=True)
    members_set = set(members)

    used_fallback = False
    try:
        _extract_7z_py7zr(archive_path, target_dir, members_set)
    except ImportError as e:
        AppLogger.debug(f"[downloader] py7zr unavailable ({e}), using external 7z")
        used_fallback = True
    except Exception as e:
        AppLogger.warning(f"[downloader] py7zr extraction failed ({type(e).__name__}: {e}), falling back to external 7z")
        used_fallback = True

    if used_fallback:
        _extract_7z_external(archive_path, target_dir, members_set)

    missing = [m for m in members if not os.path.isfile(os.path.join(target_dir, m))]
    if missing:
        raise FileNotFoundError(f"Missing after 7z extraction: {', '.join(missing)}")


def _move_members_into(temp_dir: str, target_dir: str, members_set: set[str]) -> None:
    found: set[str] = set()
    for root, _dirs, files in os.walk(temp_dir):
        for fn in files:
            if fn in members_set and fn not in found:
                src = os.path.join(root, fn)
                dst = os.path.join(target_dir, fn)
                if os.path.exists(dst):
                    os.remove(dst)
                shutil.move(src, dst)
                found.add(fn)


def _extract_7z_py7zr(archive_path: str, target_dir: str, members_set: set[str]) -> None:
    py7zr = importlib.import_module("py7zr")

    temp_dir = tempfile.mkdtemp()
    try:
        with py7zr.SevenZipFile(archive_path, "r") as z:
            all_names = z.getnames()
            for name in all_names:
                validate_archive_path(name, temp_dir)
            targets = [n for n in all_names if os.path.basename(n) in members_set]
            if not targets:
                raise FileNotFoundError(f"No matching members in archive: {sorted(members_set)}")
            z.extract(temp_dir, targets)
        _move_members_into(temp_dir, target_dir, members_set)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _extract_7z_external(archive_path: str, target_dir: str, members_set: set[str]) -> None:
    exe = find_system_7z()
    if exe is None:
        exe = ensure_7zr(target_dir)
    temp_dir = tempfile.mkdtemp()
    try:
        for name in members_set:
            result = subprocess.run(
                [exe, "e", archive_path, f"-o{temp_dir}", name, "-r", "-y"],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                raise RuntimeError(f"7z extraction failed for {name} (rc={result.returncode}): {result.stderr.strip()}")
        _move_members_into(temp_dir, target_dir, members_set)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

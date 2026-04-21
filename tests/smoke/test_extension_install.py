"""End-to-end smoke test for the 2-phase extension install flow.

Mirrors what `wafer.plugin.startup_install.run_pending_installs` does in production:
  Phase A: pip-install requirements for ALL extensions (no extension code import).
  Phase B: discover_extension + post_install hooks for ALL extensions (pip never runs).

This guards against the regression where one extension's discover_extension imports
native libs (cv2/numpy/...) and locks DLLs / package files for the next extension's pip.

Tests run sequentially in a single process inside a tmp extensions_dir.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.setup

EXTENSIONS_ROOT = Path(__file__).resolve().parent.parent.parent / "extensions"

LIGHT_EXTENSIONS = ["image", "animated", "video", "ffmpeg", "exiftool"]
HEAVY_EXTENSIONS = ["ai_tagger", "florence"]

VERIFY_IMPORTS: dict[str, list[str]] = {
    "image": ["cv2", "numpy", "PIL"],
    "animated": ["PIL"],
    "video": [],
    "ffmpeg": [],
    "exiftool": [],
    "ai_tagger": ["onnxruntime", "huggingface_hub"],
    "florence": ["torch", "transformers", "safetensors", "timm", "einops", "huggingface_hub"],
}


@dataclass
class _Entry:
    name: str
    plugin_dir: str


def _copy_extension(src_root: Path, dst_root: Path, name: str) -> Path:
    src = src_root / name
    dst = dst_root / name
    shutil.copytree(str(src), str(dst))
    return dst


def _setup_extensions_dir(tmp_path: Path, names: list[str]) -> Path:
    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir()
    for name in names:
        _copy_extension(EXTENSIONS_ROOT, ext_dir, name)
    return ext_dir


def _verify_imports_in_subprocess(packages_dir: Path, extension_name: str) -> tuple[bool, str]:
    modules = VERIFY_IMPORTS.get(extension_name, [])
    if not modules:
        return True, ""
    code = f"import sys\nsys.path.insert(0, r'{packages_dir}')\nimport importlib\nfor m in {modules!r}:\n    importlib.import_module(m)\nprint('OK')\n"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        return False, tail
    return True, ""


def _run_two_phase_install(ext_dir: Path, names: list[str], log_dir: Path) -> dict:
    from wafer.plugin import startup_install

    entries = [_Entry(name=n, plugin_dir=str(ext_dir / n)) for n in names]
    log_dir.mkdir(parents=True, exist_ok=True)

    captured: dict[str, list[str]] = {n: [] for n in names}

    real_a = startup_install._install_one_phase_a
    real_b = startup_install._install_one_phase_b

    def wrap_a(extensions_dir, entry, on_log=None):
        def collect(line):
            captured[entry.name].append(line)

        t0 = time.monotonic()
        ok = real_a(extensions_dir, entry, on_log=collect)
        dt = time.monotonic() - t0
        captured[entry.name].append(f"[phase=A elapsed={dt:.1f}s ok={ok}]")
        return ok

    def wrap_b(extensions_dir, entry, on_log=None):
        def collect(line):
            captured[entry.name].append(line)

        t0 = time.monotonic()
        ok = real_b(extensions_dir, entry, on_log=collect)
        dt = time.monotonic() - t0
        captured[entry.name].append(f"[phase=B elapsed={dt:.1f}s ok={ok}]")
        return ok

    startup_install._install_one_phase_a = wrap_a
    startup_install._install_one_phase_b = wrap_b
    try:
        processed, failed = startup_install._run_installs_blocking(str(ext_dir), entries)
    finally:
        startup_install._install_one_phase_a = real_a
        startup_install._install_one_phase_b = real_b

    for name, lines in captured.items():
        (log_dir / f"install_{name}.log").write_text("\n".join(lines), encoding="utf-8")

    return {"processed": processed, "failed": failed, "captured": captured}


def _has_post_install(name: str) -> bool:
    plugin_dir = EXTENSIONS_ROOT / name
    if not plugin_dir.is_dir():
        return False
    for path in plugin_dir.glob("*.py"):
        if path.name.startswith("_"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "def post_install" in text:
            return True
    return False


def _assert_install_success(ext_dir: Path, names: list[str], result: dict):
    failed = result["failed"]
    if failed:
        details = []
        for name in failed:
            tail = "\n".join(result["captured"].get(name, []))[-3000:]
            details.append(f"\n--- {name} ---\n{tail}")
        pytest.fail(f"Phase A/B failed for: {failed}{''.join(details)}")

    stamps_dir = ext_dir / ".packages" / ".stamps"
    for name in names:
        installed = stamps_dir / f"{name}.installed"
        post = stamps_dir / f"{name}.post_installed"
        req_file = ext_dir / name / "requirements.txt"
        if req_file.is_file() and req_file.stat().st_size > 0:
            assert installed.exists(), f"{name}.installed stamp missing"
        if _has_post_install(name):
            assert post.exists(), f"{name}.post_installed stamp missing"


@pytest.mark.timeout(900)
def test_install_lightweight_extensions(tmp_path):
    log_dir = tmp_path / "logs"
    ext_dir = _setup_extensions_dir(tmp_path, LIGHT_EXTENSIONS)

    result = _run_two_phase_install(ext_dir, LIGHT_EXTENSIONS, log_dir)
    _assert_install_success(ext_dir, LIGHT_EXTENSIONS, result)

    packages_dir = ext_dir / ".packages"
    failures = []
    for name in LIGHT_EXTENSIONS:
        ok, tail = _verify_imports_in_subprocess(packages_dir, name)
        if not ok:
            failures.append(f"\n--- {name} ---\n{tail}")
    if failures:
        pytest.fail("Subprocess import verification failed:" + "".join(failures))


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("WAFER_RUN_HEAVY_INSTALL"),
    reason="Heavy install (downloads torch+transformers, several GB). Set WAFER_RUN_HEAVY_INSTALL=1 to enable.",
)
@pytest.mark.timeout(7200)
def test_install_all_extensions_including_ml(tmp_path):
    log_dir = tmp_path / "logs"
    all_names = LIGHT_EXTENSIONS + HEAVY_EXTENSIONS
    ext_dir = _setup_extensions_dir(tmp_path, all_names)

    result = _run_two_phase_install(ext_dir, all_names, log_dir)
    _assert_install_success(ext_dir, all_names, result)

    packages_dir = ext_dir / ".packages"
    failures = []
    for name in all_names:
        ok, tail = _verify_imports_in_subprocess(packages_dir, name)
        if not ok:
            failures.append(f"\n--- {name} ---\n{tail}")
    if failures:
        pytest.fail("Subprocess import verification failed:" + "".join(failures))

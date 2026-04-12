from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "wafer" / "_version.py"
SPEC_FILE = ROOT / "main.spec"
DIST_NAME = "Wafer"

RUNTIME_PACKAGES = {
    "blake3",
    "comtypes",
    "msgpack",
    "natsort",
    "pillow",
    "platformdirs",
    "psutil",
    "PySide6",
    "pywin32",
    "setproctitle",
    "pyzmq",
    "requests",
    "Send2Trash",
    "shiboken6",
    "watchdog",
    "PySide6-Addons",
    "PySide6-Essentials",
    "certifi",
    "charset-normalizer",
    "idna",
    "urllib3",
}


def generate_third_party_notices(output: Path):
    try:
        result = subprocess.run(
            [sys.executable, "-m", "piplicenses", "--format=plain-vertical", "--with-license-file", "--no-license-path", "--packages", *sorted(RUNTIME_PACKAGES)],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        if result.returncode == 0 and result.stdout.strip():
            output.write_text(result.stdout, encoding="utf-8")
            print(f"Generated: {output.name}")
        else:
            print("Warning: pip-licenses failed, skipping THIRD-PARTY-NOTICES")
    except FileNotFoundError:
        print("Warning: pip-licenses not installed, skipping THIRD-PARTY-NOTICES")


def get_git_version() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--always"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out.startswith("v"):
            out = out[1:]
        m = re.match(r"^(\d+\.\d+\.\d+)$", out)
        if m:
            return m.group(1)
        m = re.match(r"^(\d+\.\d+\.\d+)-(\d+)-g([0-9a-f]+)$", out)
        if m:
            return f"{m.group(1)}.dev{m.group(2)}+g{m.group(3)}"
    except Exception:
        pass
    return None


def read_fallback_version() -> str:
    text = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(r'FALLBACK_VERSION\s*=\s*["\'](.+?)["\']', text)
    return m.group(1) if m else "0.0.0"


def set_fallback_version(version: str) -> str:
    original = VERSION_FILE.read_text(encoding="utf-8")
    new_text = re.sub(
        r'(FALLBACK_VERSION\s*=\s*["\']).+?(["\'])',
        rf"\g<1>{version}\g<2>",
        original,
    )
    VERSION_FILE.write_text(new_text, encoding="utf-8")
    return original


def copy_tree(src: Path, dst: Path, exclude_dirs: set[str] | None = None):
    if dst.exists():
        shutil.rmtree(dst)

    def _ignore(directory, contents):
        ignored = set()
        for c in contents:
            if c in (exclude_dirs or set()) or c == "__pycache__":
                ignored.add(c)
        return ignored

    shutil.copytree(src, dst, ignore=_ignore)


def build():
    version = get_git_version() or read_fallback_version()
    print(f"Building version: {version}")

    original = set_fallback_version(version)
    try:
        for d in ("build", "dist"):
            p = ROOT / d
            if p.exists():
                shutil.rmtree(p)

        result = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC_FILE)],
            cwd=ROOT,
        )
        if result.returncode != 0:
            print("Build failed.")
            sys.exit(1)

        dist_dir = ROOT / "dist" / DIST_NAME
        copy_tree(ROOT / "_resources", dist_dir / "_resources")
        copy_tree(ROOT / "_docs", dist_dir / "_docs")
        copy_tree(
            ROOT / "extensions",
            dist_dir / "extensions",
            exclude_dirs={".packages", ".shared_packages", "lib"},
        )

        for name in ("LICENSE", "README.md", "CHANGELOG.md", "cleanup.bat"):
            src = ROOT / name
            if src.exists():
                shutil.copy2(src, dist_dir / name)

        generate_third_party_notices(dist_dir / "THIRD-PARTY-NOTICES.txt")

        print(f"\nBuild succeeded: {dist_dir / f'{DIST_NAME}.exe'}  (v{version})")
    finally:
        VERSION_FILE.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    build()

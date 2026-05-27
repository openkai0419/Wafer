from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "wafer" / "_version.py"
LAUNCHER_DIR = ROOT / "scripts" / "launcher"
DIST_NAME = "Wafer"
ICON_FILE = ROOT / "_resources" / "icon.ico"
REQUIREMENTS_FILE = ROOT / "requirements.txt"

PYTHON_VERSION = "3.11.9"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_SHA256 = "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
PTH_NAME = f"python{''.join(PYTHON_VERSION.split('.')[:2])}._pth"


def _read_requirement_names(req_file: Path) -> frozenset[str]:
    names: set[str] = set()
    for raw in req_file.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", ";"):
            if sep in line:
                line = line.split(sep, 1)[0].strip()
                break
        if "[" in line:
            line = line.split("[", 1)[0].strip()
        if line:
            names.add(line)
    return frozenset(names)


ROOT_REQUIREMENT_PACKAGES = _read_requirement_names(REQUIREMENTS_FILE)

NOTICE_ONLY_RUNTIME_PACKAGES = frozenset(
    {
        "PySide6-Addons",
        "PySide6-Essentials",
        "backports.zstd",
        "brotli",
        "certifi",
        "charset-normalizer",
        "idna",
        "inflate64",
        "multivolumefile",
        "pybcj",
        "pycryptodomex",
        "pyppmd",
        "shiboken6",
        "texttable",
        "urllib3",
    }
)

RUNTIME_PACKAGES = ROOT_REQUIREMENT_PACKAGES | NOTICE_ONLY_RUNTIME_PACKAGES

SOURCE_ITEMS = [
    "wafer",
    "main.py",
    "conftest.py",
    "pyproject.toml",
]

RESOURCE_ITEMS = [
    "_resources",
    "_docs",
]

META_FILES = [
    "LICENSE",
    "COPYING",
    "COPYING.LESSER",
    "README.md",
    "README.jp.md",
    "RELEASE_NOTES.md",
    "CHANGELOG.md",
    "cleanup.bat",
]


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


_ALLOWED_HOSTS = frozenset({"www.python.org", "bootstrap.pypa.io"})


def download_file(url: str, dest: str):
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Only HTTPS URLs allowed: {url}")
    if parsed.hostname not in _ALLOWED_HOSTS:
        raise ValueError(f"Untrusted host: {parsed.hostname}")
    print(f"  Downloading {url}")
    urllib.request.urlretrieve(url, dest)
    if os.path.getsize(dest) == 0:
        raise ValueError(f"Empty download: {url}")


def get_git_version() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--always"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return None
    if out.startswith("v"):
        out = out[1:]
    m = re.match(r"^(\d+\.\d+\.\d+)$", out)
    if m:
        return m.group(1)
    m = re.match(r"^(\d+\.\d+\.\d+)-(\d+)-g([0-9a-f]+)$", out)
    if m:
        return f"{m.group(1)}.dev{m.group(2)}+g{m.group(3)}"
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
        ignored = {"__pycache__"}
        if exclude_dirs:
            ignored |= exclude_dirs
        return {c for c in contents if c in ignored}

    shutil.copytree(src, dst, ignore=_ignore)


def setup_python(python_dir: Path):
    print("[1/4] Setting up Python environment...")
    python_dir.mkdir(parents=True, exist_ok=True)

    fd, tmp_zip = tempfile.mkstemp(suffix=".zip")
    try:
        os.close(fd)
        download_file(PYTHON_URL, tmp_zip)
        actual = sha256_file(tmp_zip)
        if actual != PYTHON_SHA256:
            raise ValueError(f"Python SHA256 mismatch: expected {PYTHON_SHA256}, got {actual}")
        print("  SHA256 verified")
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            for info in zf.infolist():
                norm = os.path.normpath(info.filename)
                if norm.startswith("..") or os.path.isabs(norm):
                    raise ValueError(f"Path traversal detected: {info.filename}")
            zf.extractall(python_dir)
    finally:
        os.unlink(tmp_zip)

    pth = python_dir / PTH_NAME
    if pth.is_file():
        text = pth.read_text("utf-8")
        if "#import site" in text:
            text = text.replace("#import site", "import site")
        if ".." not in text.splitlines():
            text = text.replace("\n.\n", "\n.\n..\n", 1)
        pth.write_text(text, "utf-8")

    fd, get_pip = tempfile.mkstemp(suffix=".py")
    try:
        os.close(fd)
        download_file(GET_PIP_URL, get_pip)
        python_exe = str(python_dir / "python.exe")
        print("  Installing pip...")
        subprocess.run(
            [python_exe, get_pip, "--no-warn-script-location"],
            check=True,
        )
    finally:
        os.unlink(get_pip)

    print("  Installing runtime dependencies...")
    subprocess.run(
        [python_exe, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"), "--quiet", "--disable-pip-version-check", "--no-cache-dir", "--no-warn-script-location"],
        check=True,
    )
    print("  Python environment ready")


def rename_python_executables(python_dir: Path):
    for old_name, new_name in [("python.exe", "wafer-python.exe"), ("pythonw.exe", "wafer-pythonw.exe")]:
        src = python_dir / old_name
        dst = python_dir / new_name
        if src.is_file():
            src.rename(dst)
            print(f"  Renamed {old_name} -> {new_name}")


def find_csc() -> str:
    fw_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64"
    candidates = sorted(fw_dir.glob("v*/csc.exe"), reverse=True)
    if candidates:
        return str(candidates[0])
    fw32 = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework"
    candidates = sorted(fw32.glob("v*/csc.exe"), reverse=True)
    if candidates:
        return str(candidates[0])
    raise FileNotFoundError("csc.exe not found. .NET Framework is required to build launchers.")


def copy_sources(dist_dir: Path):
    print("[2/4] Copying source code...")
    for item in SOURCE_ITEMS:
        src = ROOT / item
        dst = dist_dir / item
        if src.is_dir():
            copy_tree(src, dst)
        elif src.is_file():
            shutil.copy2(src, dst)

    copy_tree(
        ROOT / "extensions",
        dist_dir / "extensions",
        exclude_dirs={".packages", ".pip_staging", ".pending", "lib"},
    )

    for item in RESOURCE_ITEMS:
        src = ROOT / item
        if src.is_dir():
            copy_tree(src, dst=dist_dir / item)

    for name in META_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, dist_dir / name)


def create_launchers(dist_dir: Path, version: str):
    print("[3/4] Creating launchers...")
    csc = find_csc()
    print(f"  Using {csc}")
    icon_arg = f"/win32icon:{ICON_FILE}" if ICON_FILE.is_file() else ""
    for cs_name, exe_name, target in [
        ("Wafer.cs", "Wafer.exe", "/target:winexe"),
        ("WaferConsole.cs", "WaferConsole.exe", "/target:exe"),
    ]:
        cs_path = LAUNCHER_DIR / cs_name
        exe_path = dist_dir / exe_name
        cmd = [csc, "/nologo", target, "/optimize+", f"/out:{exe_path}"]
        if icon_arg:
            cmd.append(icon_arg)
        cmd.append(str(cs_path))
        subprocess.run(cmd, check=True)
        print(f"  Built {exe_name}")


def generate_third_party_notices(dist_dir: Path):
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "piplicenses", "--format=plain-vertical", "--with-license-file", "--no-license-path", "--packages", *sorted(RUNTIME_PACKAGES)],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=env,
        )
        if result.returncode != 0:
            error_text = (result.stderr or "").strip() or "pip-licenses exited with a non-zero status"
            raise RuntimeError(f"Failed to generate THIRD-PARTY-NOTICES.txt: {error_text}")
        if result.stdout.strip():
            (dist_dir / "THIRD-PARTY-NOTICES.txt").write_text(result.stdout, encoding="utf-8")
            print("  Generated THIRD-PARTY-NOTICES.txt")
    except FileNotFoundError:
        print("  Warning: pip-licenses not installed, skipping THIRD-PARTY-NOTICES")


def build():
    version = get_git_version() or read_fallback_version()
    print(f"Building portable {DIST_NAME} v{version}")
    print(f"Python {PYTHON_VERSION}")

    dist_dir = ROOT / "dist" / DIST_NAME
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True)

    original = set_fallback_version(version)
    try:
        setup_python(dist_dir / "python")
        rename_python_executables(dist_dir / "python")
        copy_sources(dist_dir)
        create_launchers(dist_dir, version)
        print("[4/4] Generating notices...")
        generate_third_party_notices(dist_dir)
    finally:
        VERSION_FILE.write_text(original, encoding="utf-8")

    print(f"\nBuild succeeded: {dist_dir}")
    print(f"  Run: {dist_dir / 'Wafer.exe'}")


if __name__ == "__main__":
    build()

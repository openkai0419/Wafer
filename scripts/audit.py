from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def find_requirements() -> list[Path]:
    files = [ROOT / "requirements.txt"]
    for ext_dir in sorted((ROOT / "extensions").iterdir()):
        if not ext_dir.is_dir():
            continue
        req = ext_dir / "requirements.txt"
        if req.exists():
            files.append(req)
    return files


def find_dynamic_deps() -> list[Path]:
    script = ROOT / "scripts" / "extract_dynamic_deps.py"
    if not script.exists():
        return []
    try:
        out = subprocess.check_output(
            [sys.executable, str(script)],
            text=True,
            cwd=ROOT,
        ).strip()
        return [Path(p) for p in out.splitlines() if p]
    except subprocess.CalledProcessError:
        return []


def audit():
    failed = False
    all_files = find_requirements() + find_dynamic_deps()

    print("=== pip-audit: dependency vulnerability scan ===\n")
    for req in all_files:
        label = req.relative_to(ROOT)
        print(f"--- {label} ---")
        result = subprocess.run(
            [sys.executable, "-m", "pip_audit", "-r", str(req), "--no-deps", "-f", "columns"],
            cwd=ROOT,
        )
        if result.returncode != 0:
            failed = True
        print()

    if failed:
        print("Vulnerabilities found.")
        sys.exit(1)
    print("All clear.")


if __name__ == "__main__":
    audit()

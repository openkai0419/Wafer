from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ["wafer", "extensions", "tests", "scripts"]


def lint(fix: bool = False):
    dirs = [str(ROOT / t) for t in TARGETS if (ROOT / t).exists()]

    print("=== ruff check ===")
    cmd = [sys.executable, "-m", "ruff", "check", *dirs]
    if fix:
        cmd.append("--fix")
    check = subprocess.run(cmd, cwd=ROOT)

    print("\n=== ruff format --check ===")
    fmt_cmd = [sys.executable, "-m", "ruff", "format", "--check", *dirs]
    if fix:
        fmt_cmd = [sys.executable, "-m", "ruff", "format", *dirs]
    fmt = subprocess.run(fmt_cmd, cwd=ROOT)

    if check.returncode != 0 or fmt.returncode != 0:
        if not fix:
            print('\nRun "scripts/lint.bat --fix" to auto-fix.')
        sys.exit(1)

    print("\nAll clear.")


if __name__ == "__main__":
    lint(fix="--fix" in sys.argv)

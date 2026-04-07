from __future__ import annotations

import re
import subprocess
import sys

FALLBACK_VERSION = "0.1.0"


def get_version() -> str:
    if getattr(sys, "frozen", False):
        return FALLBACK_VERSION
    try:
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--always"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return FALLBACK_VERSION
    if out.startswith("v"):
        out = out[1:]
    m = re.match(r"^(\d+\.\d+\.\d+)$", out)
    if m:
        return m.group(1)
    m = re.match(r"^(\d+\.\d+\.\d+)-(\d+)-g([0-9a-f]+)$", out)
    if m:
        return f"{m.group(1)}.dev{m.group(2)}+g{m.group(3)}"
    return FALLBACK_VERSION


__version__ = get_version()

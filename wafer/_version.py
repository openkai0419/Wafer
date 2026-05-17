from __future__ import annotations

import re
import subprocess
import sys

FALLBACK_VERSION = "0.6.13"

_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def get_version() -> str:
    try:
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--always"],
            stderr=subprocess.DEVNULL,
            text=True,
            **_NO_WINDOW,
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
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
#__version__ = "0.6.17"

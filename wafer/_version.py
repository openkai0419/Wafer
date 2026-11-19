from __future__ import annotations

import re
import subprocess
import sys

from . import _dev
from .core.common.paths import get_app_root_dir
from .core.logs import AppLogger

FALLBACK_VERSION = "0.7.3.dev1+g1d36add"
UNKNOWN_VERSION = "unknown"

_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
GIT_DESCRIBE_TIMEOUT = 5


def _unknown_version(reason: str) -> str:
    AppLogger.warning(f"Could not read the Wafer version from git ({reason}). The version is shown as '{UNKNOWN_VERSION}' and updates are not offered in this process.")
    return UNKNOWN_VERSION


def get_version() -> str:
    root = get_app_root_dir()
    if not (root / ".git").exists():
        return FALLBACK_VERSION
    try:
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--always"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=GIT_DESCRIBE_TIMEOUT,
            **_NO_WINDOW,
        ).strip()
    except subprocess.TimeoutExpired:
        return _unknown_version(f"git describe took more than {GIT_DESCRIBE_TIMEOUT}s")
    except (subprocess.CalledProcessError, OSError) as e:
        return _unknown_version(f"git describe failed: {e}")
    if out.startswith("v"):
        out = out[1:]
    m = re.match(r"^(\d+\.\d+\.\d+)$", out)
    if m:
        return m.group(1)
    m = re.match(r"^(\d+\.\d+\.\d+)-(\d+)-g([0-9a-f]+)$", out)
    if m:
        return f"{m.group(1)}.dev{m.group(2)}+g{m.group(3)}"
    return _unknown_version(f"unexpected git describe output {out!r}")


__version__ = get_version()

if _dev.FORCE_UPDATE_ENABLED:
    __version__ = "0.6.2"

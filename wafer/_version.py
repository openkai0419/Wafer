from __future__ import annotations

import re
import subprocess
import sys

from . import _dev
from .core.common.paths import get_app_root_dir

FALLBACK_VERSION = "0.7.3.dev1+g1d36add"
UNKNOWN_VERSION = "unknown"

_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
GIT_DESCRIBE_TIMEOUT = 5


def read_version() -> tuple[str, str]:
    root = get_app_root_dir()
    if not (root / ".git").exists():
        return FALLBACK_VERSION, ""
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
        return UNKNOWN_VERSION, f"git describe took more than {GIT_DESCRIBE_TIMEOUT}s"
    except (subprocess.CalledProcessError, OSError) as e:
        return UNKNOWN_VERSION, f"git describe failed: {e}"
    if out.startswith("v"):
        out = out[1:]
    m = re.match(r"^(\d+\.\d+\.\d+)$", out)
    if m:
        return m.group(1), ""
    m = re.match(r"^(\d+\.\d+\.\d+)-(\d+)-g([0-9a-f]+)$", out)
    if m:
        return f"{m.group(1)}.dev{m.group(2)}+g{m.group(3)}", ""
    return UNKNOWN_VERSION, f"unexpected git describe output {out!r}"


def warn_if_version_unknown() -> None:
    if not VERSION_PROBLEM:
        return
    from .core.logs import AppLogger

    AppLogger.warning(f"Could not read the Wafer version from git ({VERSION_PROBLEM}). The version is shown as '{UNKNOWN_VERSION}' and updates are not offered in this process.")


__version__, VERSION_PROBLEM = read_version()

if _dev.FORCE_UPDATE_ENABLED:
    __version__ = "0.6.2"

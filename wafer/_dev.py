"""Local updater testing switch.

Set ``FORCE_UPDATE_ENABLED = True`` to make the updater read its release info,
manifest and package from a local folder instead of GitHub. This exercises the
full download -> stage -> restart flow offline. Only the download source changes:
sha256 verification, extraction, plan generation and launcher apply all run
through the exact production code paths.

Generate the local source folder with ``scripts/make_local_update.bat`` (writes
``latest.json``, ``manifest.json`` and the package zip). The folder location is
resolved from ``WAFER_UPDATE_SOURCE_DIR`` or the system temp dir, so the same
path works from both the repo and a built portable app on the same machine.

While forcing, ``wafer._version.__version__`` is pinned to ``DEV_VERSION`` so
every check sees an update. Reset FORCE_UPDATE_ENABLED to False before
committing or shipping.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

FORCE_UPDATE_ENABLED = False
# FORCE_UPDATE_ENABLED = True

SOURCE_DIR_ENV = "WAFER_UPDATE_SOURCE_DIR"


def source_dir() -> Path:
    override = os.environ.get(SOURCE_DIR_ENV)
    return Path(override) if override else Path(tempfile.gettempdir()) / "wafer_local_update"


def asset(name: str) -> Path:
    return source_dir() / name

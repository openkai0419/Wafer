import os
import subprocess
import sys
from pathlib import Path

import pytest

from wafer.plugin.imageloader.base import BaseImageLoader
from wafer.plugin.imageloader.handler import ImageLoaderResolver

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("module", "forbidden"),
    [
        ("wafer.plugin.imageloader.handler", ("PySide6", "numpy")),
        ("wafer.plugin.grid.base", ("PySide6",)),
        ("wafer.core.platform.file_operations", ("requests",)),
        ("wafer.builtins.updater.service", ("requests",)),
        ("wafer.qt.widgets.markdown_browser", ("PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore")),
    ],
)
def test_import_does_not_pull(module, forbidden):
    code = f"import sys;import {module};hit = sorted(m for m in sys.modules if m in {forbidden!r});print(hit);sys.exit(1 if hit else 0)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, f"{module} pulled {result.stdout}\n{result.stderr}"


def test_resolver_preload_calls_every_loader():
    calls = []

    class LoaderA(BaseImageLoader):
        NAME = "preload_a"

        @classmethod
        def preload(cls):
            calls.append("a")

    class LoaderB(BaseImageLoader):
        NAME = "preload_b"

        @classmethod
        def preload(cls):
            calls.append("b")

    resolver = ImageLoaderResolver()
    resolver.registry.register(LoaderA)
    resolver.registry.register(LoaderB)
    resolver.preload()
    assert sorted(calls) == ["a", "b"]

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

CHECK_CODE = "import sys;import wafer.web.media;qt = [m for m in sys.modules if m.startswith(('PySide6', 'shiboken6'))];sys.exit(1 if qt else 0)"


def test_web_media_imports_no_qt():
    result = subprocess.run(
        [sys.executable, "-c", CHECK_CODE],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Qt modules leaked into wafer.web.media import chain.\nstdout: {result.stdout}\nstderr: {result.stderr}"


def test_web_media_does_not_depend_on_the_app_layer(tmp_path):
    code = "import sys;from wafer.web import media;media.thumb_cache();app = [m for m in sys.modules if m.startswith('wafer.app')];print(app);sys.exit(1 if app else 0)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "WIN_PD_OVERRIDE_LOCAL_APPDATA": str(tmp_path)},
    )
    assert result.returncode == 0, f"wafer.web reached into wafer.app.\nstdout: {result.stdout}\nstderr: {result.stderr}"

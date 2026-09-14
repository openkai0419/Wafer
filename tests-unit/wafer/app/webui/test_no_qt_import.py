import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

CHECK_CODE = (
    "import sys;"
    "import wafer.app.webui.backend.server, wafer.app.webui.backend.api, wafer.app.webui.backend.media, wafer.app.webui.backend.session;"
    "import wafer.app.webui.entry, wafer.app.webui.state;"
    "qt = [m for m in sys.modules if m.startswith(('PySide6', 'shiboken6'))];"
    "sys.exit(1 if qt else 0)"
)


def test_webui_backend_imports_no_qt():
    result = subprocess.run(
        [sys.executable, "-c", CHECK_CODE],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Qt modules leaked into webui import chain.\nstdout: {result.stdout}\nstderr: {result.stderr}"

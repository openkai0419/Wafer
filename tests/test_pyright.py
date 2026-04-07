import json
import subprocess
import sys

import pytest

def test_pyright_no_errors():
    result = subprocess.run(
        [sys.executable, "-m", "pyright", "wafer/", "--outputjson"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0 and not result.stdout.strip():
        pytest.skip("pyright not available")
    data = json.loads(result.stdout)
    summary = data.get("summary", {})
    errors = summary.get("errorCount", 0)
    if errors > 0:
        lines = []
        for d in data.get("generalDiagnostics", []):
            if d.get("severity") != "error":
                continue
            f = d.get("file", "")
            r = d.get("range", {}).get("start", {})
            rule = d.get("rule", "")
            msg = d.get("message", "")
            lines.append(f"  {f}:{r.get('line', 0) + 1} [{rule}] {msg}")
        detail = "\n".join(lines)
        assert False, f"pyright reported {errors} error(s):\n{detail}"

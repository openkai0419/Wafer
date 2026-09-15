import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from wafer.constants import APP_DATA_DIR_NAME
from wafer.core.platform.process_lock import SafeProcessLock

ROOT = Path(__file__).resolve().parents[2]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_get(url, timeout=5.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


@pytest.fixture
def webui_server():
    lock = SafeProcessLock(f"{APP_DATA_DIR_NAME}_webui")
    if not lock.acquire():
        pytest.skip("another WebUI instance is running")
    lock.release()
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "main.py"), "--webui", "--no-ui", "--no-tray", "--no-browser", "--port", str(port)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        started = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"WebUI exited early with code {proc.returncode}")
            try:
                status, _, _ = http_get(f"http://127.0.0.1:{port}/api/dbs", timeout=2.0)
                if status == 200:
                    started = True
                    break
            except OSError:
                time.sleep(0.2)
        if not started:
            pytest.fail("WebUI did not start in time")
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


class TestSmokeWebUI:
    def test_index_and_api(self, webui_server):
        base = f"http://127.0.0.1:{webui_server}"

        status, ctype, body = http_get(f"{base}/")
        assert status == 200
        assert "text/html" in ctype
        assert b"Wafer" in body

        status, _, body = http_get(f"{base}/api/dbs")
        assert status == 200
        assert isinstance(json.loads(body)["dbs"], list)

        status, _, body = http_get(f"{base}/api/sorts")
        assert status == 200
        assert "name" in json.loads(body)["sorts"]

        status, _, body = http_get(f"{base}/api/filters")
        assert status == 200
        assert json.loads(body)["filters"]

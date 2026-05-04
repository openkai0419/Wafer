from __future__ import annotations

import json
import os
import subprocess
import threading
import psutil

from wafer.core.platform.process import AppProcess
from wafer.utils.logs import AppLogger

_QUERY_TIMEOUT = 30

_SKIP_GROUPS = frozenset({"System", "ExifTool"})
_SKIP_KEYS = frozenset({"SourceFile"})
_WIDTH_TAGS = frozenset({"ImageWidth", "ExifImageWidth"})
_HEIGHT_TAGS = frozenset({"ImageHeight", "ExifImageHeight"})


class ExifToolProcess:
    def __init__(self, exe_path: str):
        self._exe = exe_path
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._seq = 0

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self):
        if self.alive:
            return
        self._proc = subprocess.Popen(
            [
                self._exe,
                "-stay_open",
                "True",
                "-@",
                "-",
                "-common_args",
                "-j",
                "-G1",
                "-charset",
                "filename=utf8",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def stop(self):
        with self._lock:
            proc = self._proc
            if proc is None:
                return
            self._proc = None
        try:
            if proc.stdin:
                proc.stdin.write("-stay_open\nFalse\n")
                proc.stdin.flush()
            proc.wait(timeout=5)
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            self._terminate_proc_tree(proc)
        finally:
            self._close_pipes(proc)

    def query(self, path: str) -> dict | None:
        with self._lock:
            if not self.alive:
                self.start()
            if not self.alive:
                return None
            self._seq += 1
            seq = self._seq
            sentinel = f"{{ready{seq}}}"
            try:
                self._proc.stdin.write(f"{path}\n-execute{seq}\n")
                self._proc.stdin.flush()
            except OSError:
                self._proc = None
                return None
            lines: list[str] = []
            result: dict | None = None
            proc = self._proc

            def _read():
                nonlocal result
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        return
                    stripped = line.rstrip("\r\n")
                    if stripped == sentinel:
                        result = _parse_json_output("\n".join(lines))
                        return
                    lines.append(stripped)

            reader = threading.Thread(target=_read, daemon=True)
            reader.start()
            reader.join(timeout=_QUERY_TIMEOUT)
            if reader.is_alive():
                AppLogger.warning(f"[exiftool] Query timed out for: {path}")
                self._kill_proc()
                return None
            if result is None and not lines:
                self._proc = None
                return None
            return result

    def _kill_proc(self):
        proc = self._proc
        self._proc = None
        if proc:
            self._terminate_proc_tree(proc)
            self._close_pipes(proc)

    @staticmethod
    def _terminate_proc_tree(proc: subprocess.Popen):
        try:
            ps_proc = psutil.Process(proc.pid)
        except psutil.NoSuchProcess:
            return
        AppProcess.terminate_tree([ps_proc], timeout=1, kill_timeout=2)

    @staticmethod
    def _close_pipes(proc: subprocess.Popen):
        for pipe in (proc.stdin, proc.stdout):
            if pipe is None:
                continue
            try:
                pipe.close()
            except OSError:
                pass

    def __del__(self):
        try:
            self.stop()
        except (OSError, RuntimeError):
            pass


def _parse_json_output(raw: str) -> dict | None:
    raw = raw.strip()
    if not raw:
        return None
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
        if isinstance(data, list) and data:
            return data[0]
    except (json.JSONDecodeError, IndexError):
        AppLogger.debug(f"[exiftool] JSON parse failed: {raw[:200]}")
    return None


def flatten(data: dict) -> tuple[dict[str, str], float | None]:
    meta: dict[str, str] = {}
    width: int | None = None
    height: int | None = None
    rotated = False
    has_error = False

    for key, val in data.items():
        if key in _SKIP_KEYS:
            continue
        group, _, tag = key.partition(":")
        if not tag:
            tag = group
            group = ""
        if group in _SKIP_GROUPS:
            if tag == "Error":
                has_error = True
            continue
        if tag in _WIDTH_TAGS and isinstance(val, (int, float)) and width is None:
            width = int(val)
        if tag in _HEIGHT_TAGS and isinstance(val, (int, float)) and height is None:
            height = int(val)
        if tag == "Orientation" and isinstance(val, str):
            rotated = "90" in val or "270" in val
        if val is not None:
            if isinstance(val, list):
                s = ", ".join(str(v) for v in val if v is not None)
            else:
                s = str(val).strip()
            if s:
                meta[key] = s

    if has_error and not meta:
        return {}, None

    aspect: float | None = None
    if width and height:
        if rotated:
            width, height = height, width
        try:
            aspect = width / height
        except ZeroDivisionError:
            pass

    return meta, aspect

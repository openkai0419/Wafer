from __future__ import annotations

import json
import os
import subprocess
import threading
import psutil

from wafer.core.platform.process import AppProcess, kill_with_parent, terminate_pid_tree
from wafer.core.logs import AppLogger
from wafer.core.logs import debug_non_recursive

_QUERY_TIMEOUT = 30

_spawned: dict[int, psutil.Process] = {}
_spawned_lock = threading.Lock()

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
        kill_spawned()
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
        kill_with_parent(self._proc.pid)
        _remember(self._proc.pid)

    def stop(self):
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.write("-stay_open\nFalse\n")
                proc.stdin.flush()
            proc.wait(timeout=5)
        except (BrokenPipeError, OSError, ValueError, subprocess.TimeoutExpired):
            terminate_pid_tree(proc.pid)
        finally:
            _forget(proc.pid)
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
            proc = self._proc
            try:
                proc.stdin.write(f"{path}\n-execute{seq}\n")
                proc.stdin.flush()
            except (OSError, ValueError) as e:
                AppLogger.warning(f"[exiftool] Write failed, restarting process: {e}")
                self._discard(proc)
                return None
            lines: list[str] = []
            completed = False

            def _read():
                nonlocal completed
                try:
                    while True:
                        line = proc.stdout.readline()
                        if not line:
                            return
                        stripped = line.rstrip("\r\n")
                        if stripped == sentinel:
                            completed = True
                            return
                        lines.append(stripped)
                except (OSError, ValueError) as e:
                    debug_non_recursive(f"[exiftool] Reader stopped: {e}")

            reader = threading.Thread(target=_read, daemon=True)
            reader.start()
            reader.join(timeout=_QUERY_TIMEOUT)
            if reader.is_alive():
                AppLogger.warning(f"[exiftool] Query timed out, restarting process: {path}")
                self._discard(proc)
                return None
            if not completed:
                AppLogger.warning(f"[exiftool] Process ended unexpectedly, restarting: {path}")
                self._discard(proc)
                return None
            return _parse_json_output("\n".join(lines))

    def _discard(self, proc: subprocess.Popen):
        if self._proc is proc:
            self._proc = None
        terminate_pid_tree(proc.pid)
        _forget(proc.pid)
        self._close_pipes(proc)

    @staticmethod
    def _close_pipes(proc: subprocess.Popen):
        for pipe in (proc.stdin, proc.stdout):
            if pipe is None:
                continue
            try:
                pipe.close()
            except OSError as e:
                debug_non_recursive(f"[exiftool] Pipe close failed: {e}")

    def __del__(self):
        try:
            self.stop()
        except (OSError, RuntimeError) as e:
            debug_non_recursive(f"[exiftool] Process cleanup failed: {e}")


def _remember(pid: int):
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    with _spawned_lock:
        _spawned[pid] = proc


def _forget(pid: int):
    with _spawned_lock:
        _spawned.pop(pid, None)


def kill_spawned():
    with _spawned_lock:
        tracked = list(_spawned.values())
        _spawned.clear()
    strays = [p for p in tracked if p.is_running()]
    if not strays:
        return 0
    AppLogger.warning(f"[exiftool] Killing {len(strays)} stray process(es) left behind by earlier queries")
    AppProcess.terminate_tree(strays, timeout=1, kill_timeout=2)
    return len(strays)


def kill_orphans(exe_path: str) -> int:
    target = os.path.normcase(os.path.abspath(exe_path))
    name = os.path.basename(target)
    orphans = []
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            if os.path.normcase(proc.info.get("name") or "") != name:
                continue
            exe = proc.info.get("exe")
            if not exe or os.path.normcase(os.path.abspath(exe)) != target:
                continue
            if proc.parent() is not None:
                continue
            orphans.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not orphans:
        return 0
    AppLogger.warning(f"[exiftool] Killing {len(orphans)} orphaned process(es) left by a previous run")
    AppProcess.terminate_tree(orphans, timeout=1, kill_timeout=2)
    return len(orphans)


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

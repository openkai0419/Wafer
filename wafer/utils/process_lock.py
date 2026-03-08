import contextlib
import json
import os
import sys
import time

import psutil

from ..utils.logs import AppLogger
from ..utils.paths import resolve_data_path

_FILE_LOCK_TIMEOUT = 5.0
_FILE_LOCK_RETRY = 0.02


@contextlib.contextmanager
def file_lock(lock_path: str, timeout: float = _FILE_LOCK_TIMEOUT):
    os.makedirs(os.path.dirname(lock_path) or '.', exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if sys.platform == 'win32':
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, IOError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f'file lock timeout: {lock_path}')
                time.sleep(_FILE_LOCK_RETRY)
        yield
    finally:
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)

class SafeProcessLock:

    def __init__(self, name, parent_pid=None):
        self.name = name
        self.lock_file = resolve_data_path(f".temp/{name}.lock")
        self.pid = os.getpid()
        self.create_time = self._get_create_time(self.pid)
        self.parent_pid = parent_pid
        self.parent_create_time = self._get_create_time(parent_pid) if parent_pid else None
        self.acquired = False

    @staticmethod
    def _get_create_time(pid):
        try:
            return psutil.Process(pid).create_time()
        except psutil.Error:
            return None

    def _load_lock_info(self):
        with open(self.lock_file, 'r') as f:
            content = f.read().strip()
        if not content:
            return None
        if content.isdigit():
            return {'pid': int(content), 'create_time': None}
        data = json.loads(content)
        if not isinstance(data, dict):
            return None
        pid = data.get('pid')
        create_time = data.get('create_time')
        if not isinstance(pid, int):
            return None
        if create_time is not None and not isinstance(create_time, (int, float)):
            return None
        result = {'pid': pid, 'create_time': float(create_time) if create_time is not None else None}
        parent_pid = data.get('parent_pid')
        if isinstance(parent_pid, int):
            parent_ct = data.get('parent_create_time')
            result['parent_pid'] = parent_pid
            result['parent_create_time'] = float(parent_ct) if isinstance(parent_ct, (int, float)) else None
        return result

    @staticmethod
    def _is_process_alive(pid, create_time):
        try:
            running_ct = psutil.Process(pid).create_time()
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            return True
        except psutil.Error:
            return True
        if create_time is None:
            return True
        return abs(running_ct - create_time) < 1e-3

    def _is_lock_owner_alive(self, info):
        if not self._is_process_alive(info['pid'], info['create_time']):
            return False
        parent_pid = info.get('parent_pid')
        if parent_pid is not None:
            if not self._is_process_alive(parent_pid, info.get('parent_create_time')):
                self._terminate_process(info['pid'], info['create_time'])
                return False
        return True

    @staticmethod
    def _terminate_process(pid, create_time):
        try:
            proc = psutil.Process(pid)
            if create_time is not None:
                if abs(proc.create_time() - create_time) >= 1e-3:
                    return
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired, psutil.Error):
            pass

    def _try_remove_lock_file(self):
        try:
            os.remove(self.lock_file)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    def _lock_data(self):
        data = {'pid': self.pid, 'create_time': self.create_time}
        if self.parent_pid is not None:
            data['parent_pid'] = self.parent_pid
            data['parent_create_time'] = self.parent_create_time
        return data

    def acquire(self):
        while True:
            try:
                fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, 'w') as f:
                    f.write(json.dumps(self._lock_data()))
                self.acquired = True
                return True
            except FileExistsError:
                try:
                    info = self._load_lock_info()
                    if info is None:
                        if not self._try_remove_lock_file():
                            time.sleep(0.1)
                        continue
                    if self._is_lock_owner_alive(info):
                        return False
                    if not self._try_remove_lock_file():
                        time.sleep(0.1)
                        continue
                except Exception as e:
                    AppLogger.warning(f"SafeProcessLock.acquire failed: {self.lock_file}", exc=e)
                    if not self._try_remove_lock_file():
                        time.sleep(0.1)
                time.sleep(0.1)

    def release(self):
        if self.acquired and os.path.exists(self.lock_file):
            try:
                info = self._load_lock_info()
                if info is None:
                    return
                if info['pid'] != self.pid:
                    return
                if info['create_time'] is not None and self.create_time is not None:
                    if abs(info['create_time'] - self.create_time) >= 1e-3:
                        return
                self._try_remove_lock_file()
            except Exception as e:
                AppLogger.warning(f"SafeProcessLock.release failed: {self.lock_file}", exc=e)

    def __enter__(self):
        if not self.acquire():
            raise FileExistsError(f"Process '{self.name}' already running")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

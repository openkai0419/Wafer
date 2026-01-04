import json
import os
import time

import psutil

from ..common.errors import show_warning
from ..common.funcs import data_path

class SafeProcessLock:

    def __init__(self, name):
        self.name = name
        self.lock_file = data_path(f".temp/{name}.lock")
        self.pid = os.getpid()
        self.create_time = self._get_create_time(self.pid)
        self.acquired = False

    def _get_create_time(self, pid):
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
        return {'pid': pid, 'create_time': float(create_time) if create_time is not None else None}

    def _is_lock_owner_alive(self, pid, create_time):
        try:
            proc = psutil.Process(pid)
            running_ct = proc.create_time()
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            return True
        except psutil.Error:
            return True
        if create_time is None:
            return True
        return abs(running_ct - create_time) < 1e-3

    def _try_remove_lock_file(self):
        try:
            os.remove(self.lock_file)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    def acquire(self):
        while True:
            try:
                fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, 'w') as f:
                    f.write(json.dumps({'pid': self.pid, 'create_time': self.create_time}))
                self.acquired = True
                return True
            except FileExistsError:
                try:
                    info = self._load_lock_info()
                    if info is None:
                        if not self._try_remove_lock_file():
                            time.sleep(0.1)
                        continue
                    if self._is_lock_owner_alive(info['pid'], info['create_time']):
                        return False
                    if not self._try_remove_lock_file():
                        time.sleep(0.1)
                        continue
                except Exception as e:
                    show_warning(None, f"SafeProcessLock.acquire failed: {self.lock_file}", exc=e)
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
                show_warning(None, f"SafeProcessLock.release failed: {self.lock_file}", exc=e)

    def __enter__(self):
        if not self.acquire():
            raise FileExistsError(f"Process '{self.name}' already running")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

import threading

import psutil

from afterimages.utils.logs import AppLogger

_DEFAULT_INTERVAL = 2.0


class ParentProcessChecker:

    def __init__(self, parent_pid, on_orphan, interval=_DEFAULT_INTERVAL):
        self._parent_pid = parent_pid
        self._parent_create_time = self._get_create_time(parent_pid)
        self._on_orphan = on_orphan
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fired = False

    @staticmethod
    def _get_create_time(pid):
        try:
            return psutil.Process(pid).create_time()
        except psutil.Error:
            return None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        AppLogger.info(f'ParentProcessChecker started: monitoring pid={self._parent_pid}')

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self._interval + 1)
            self._thread = None

    def _is_parent_alive(self):
        try:
            proc = psutil.Process(self._parent_pid)
            if self._parent_create_time is not None:
                if abs(proc.create_time() - self._parent_create_time) >= 1e-3:
                    return False
            return proc.is_running()
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            return True
        except psutil.Error:
            return True

    def _watch_loop(self):
        while not self._stop.wait(self._interval):
            if not self._is_parent_alive():
                if self._fired:
                    break
                self._fired = True
                AppLogger.warning(f'ParentProcessChecker: parent pid={self._parent_pid} is dead, triggering shutdown')
                try:
                    self._on_orphan()
                except Exception as e:
                    AppLogger.warning(f'ParentProcessChecker: on_orphan callback failed', exc=e)
                break

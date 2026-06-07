import threading

from ....utils.profiling import profiler
from ....utils.logs import AppLogger


class ProgressAggregator:
    def __init__(self, db_name, node):
        self.db_name = db_name
        self._node = node
        self.current = 0
        self.maximum = 0
        self._lock = threading.Lock()

    def reset(self):
        with self._lock:
            self._reset_unlocked()

    def _reset_unlocked(self):
        self._send_progress()
        self.current = 0
        self.maximum = 0

    @profiler.profile
    def increment(self, current_inc=0, total_inc=0):
        with self._lock:
            changed = False
            if total_inc:
                self.maximum += total_inc
                changed = True
            if current_inc:
                self.current += current_inc
                changed = True
            if not changed:
                return
            if self.current >= self.maximum > 0:
                self._reset_unlocked()
            else:
                self._send_progress()

    def send_event(self, topic, value=""):
        try:
            self._node.send_coalesced(topic, value, dst="viewer", db=self.db_name)
        except Exception as e:
            AppLogger.warning(f"[notify {topic} failed] {e}")

    def _send_progress(self):
        try:
            self._node.send_coalesced("maximum", self.maximum, dst="viewer", db=self.db_name)
            self._node.send_coalesced("progress", self.current, dst="viewer", db=self.db_name)
        except Exception as e:
            AppLogger.warning(f"[progress notify failed] {e}")

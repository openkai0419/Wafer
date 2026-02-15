from ..common.profiling import profiler
from ..common.logs import AppLogger


class ProgressAggregator:

    def __init__(self, tablename, node):
        self.tablename = tablename
        self._node = node
        self.current = 0
        self.maximum = 0

    def reset(self):
        self._send_progress()
        self.current = 0
        self.maximum = 0

    @profiler.profile
    def add(self, current_inc=0, total_inc=0):
        if total_inc:
            self.maximum += total_inc
        if current_inc:
            self.current += current_inc
        if self.current >= self.maximum:
            if self.current != 0 and self.maximum != 0:
                self.reset()
            return
        self._send_progress()

    def notify(self, topic, value=''):
        try:
            self._node.send(topic, value, dst='viewer', db=self.tablename)
        except Exception as e:
            AppLogger.warning(f'[notify {topic} failed] {e}')

    def _send_progress(self):
        try:
            self._node.send('maximum', self.maximum, dst='viewer', db=self.tablename)
            self._node.send('progress', self.current, dst='viewer', db=self.tablename)
        except Exception as e:
            AppLogger.warning(f'[progress notify failed] {e}')

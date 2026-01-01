import threading
from ..common.profiling import logger, profiler
from ..common.helpers import call0
from ..zmq.zmq import Role, ZMQNode
_node = None
_node_lock = threading.Lock()

def set_node(node):
    global _node
    with _node_lock:
        _node = node

@profiler.profile
def _get_node():
    global _node
    with _node_lock:
        if _node is None:
            _node = ZMQNode(Role.COLLECTOR)
            _node.start()
        return _node

def close_publisher():
    global _node
    with _node_lock:
        if _node is not None:
            try:
                call0(_node, 'stop')
            except Exception as e:
                logger.warning(f'[node close failed] {e}')
            finally:
                _node = None

class ProgressAggregator:

    def __init__(self, tablename):
        self.tablename = tablename
        self.current = 0
        self.maximum = 0

    def reset(self):
        self._notify_progress()
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
        self._notify_progress()

    @profiler.profile
    def _notify_progress(self):
        try:
            node = _get_node()
            node.send(targetprocess='viewer', table=self.tablename, topic='maximum', message=str(self.maximum))
            node.send(targetprocess='viewer', table=self.tablename, topic='progress', message=str(self.current))
        except Exception as e:
            logger.warning(f'[progress notify failed] {e}')

    @profiler.profile
    def notify_extra(self, key, value):
        try:
            node = _get_node()
            node.send(targetprocess='viewer', table=self.tablename, topic=key, message=str(value))
            logger.debug(f'[NOTIFY] EXTRA {key} {value}')
        except Exception as e:
            logger.warning(f'[notify failed: {key}={value}] {e}')

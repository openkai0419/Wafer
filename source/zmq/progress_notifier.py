import threading

from .broker import ZMQNode, Role
from ..common.profiling import logger, profiler

_node = None
_node_lock = threading.Lock()

@profiler.profile
def _get_node() -> ZMQNode:
    global _node
    with _node_lock:
        if _node is None:
            _node = ZMQNode(Role.COLLECTOR)
            _node.start()
        return _node

def close_publisher():
    """Close node instance safely"""
    global _node
    with _node_lock:
        if _node is not None:
            try:
                _node.stop()
            except Exception as e:
                logger.warning(f"[node close failed] {e}")
            finally:
                _node = None

def get_viewer_count():
    try:
        node = _get_node()
        return node.get_sub_count()
    except Exception as e:
        logger.warning(f"[viewer count failed] {e}")
        return 1

def send_show_toggle(flag):
    try:
        node = _get_node()
        node.send(targetprocess="viewer", table="*", topic="show_toggle", message="True" if flag else "False")
    except Exception as e:
        logger.warning(f"[toggle notify failed] {e}")

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
            node.send(targetprocess="viewer", table=self.tablename, topic="maximum", message=str(self.maximum))
            node.send(targetprocess="viewer", table=self.tablename, topic="progress", message=str(self.current))
            # logger.debug(f"[NOTIFY] progress {self.current} {self.maximum}")
        except Exception as e:
            logger.warning(f"[progress notify failed] {e}")

    @profiler.profile
    def notify_extra(self, key: str, value: object):
        try:
            node = _get_node()
            node.send(targetprocess="viewer", table=self.tablename, topic=key, message=str(value))
            logger.debug(f"[NOTIFY] EXTRA {key} {value}")
        except Exception as e:
            logger.warning(f"[notify failed: {key}={value}] {e}")

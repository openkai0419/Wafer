import threading

from .zmq import ZMQPublisher
from ..common.profiling import logger, profiler

_publisher = None
_publisher_lock = threading.Lock()

@profiler.profile
def _get_publisher() -> ZMQPublisher:
    global _publisher
    with _publisher_lock:
        if _publisher is None:
            _publisher = ZMQPublisher()
        return _publisher
    
def close_publisher():
    """Close publisher instance safely"""
    global _publisher
    with _publisher_lock:
        if _publisher is not None:
            try:
                _publisher.close()
            except Exception as e:
                logger.warning(f"[publisher close failed] {e}")
            finally:
                _publisher = None

def get_viewer_count():
    try:
        publisher = _get_publisher()
        return publisher.get_sub_count()
    except Exception as e:
        logger.warning(f"[viewer count failed] {e}")
        return 1

def send_show_toggle(flag):
    try:
        publisher = _get_publisher()
        if flag:
            publisher.send("show_toggle", "True", "*")
        else:
            publisher.send("show_toggle", "False", "*")
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
            publisher = _get_publisher()
            publisher.send("maximum", str(self.maximum), self.tablename)
            publisher.send("progress", str(self.current), self.tablename)
            #logger.debug(f"[NOTIFY] progress {self.current} {self.maximum}")
        except Exception as e:
            logger.warning(f"[progress notify failed] {e}")

    @profiler.profile
    def notify_extra(self, key: str, value: object):
        try:
            publisher = _get_publisher()
            publisher.send(key, str(value), self.tablename)
            logger.debug(f"[NOTIFY] EXTRA {key} {value}")
        except Exception as e:
            logger.warning(f"[notify failed: {key}={value}] {e}")

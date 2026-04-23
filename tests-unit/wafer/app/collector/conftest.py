import pytest

from wafer.app.collector.worker import CollectorWorker


@pytest.fixture(autouse=True)
def cleanup_collector_workers():
    instances: list[CollectorWorker] = []
    original_init = CollectorWorker.__init__

    def tracking_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        instances.append(self)

    CollectorWorker.__init__ = tracking_init
    try:
        yield
    finally:
        CollectorWorker.__init__ = original_init
        for worker in instances:
            try:
                worker._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            try:
                worker._node.stop()
            except Exception:
                pass

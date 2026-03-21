import os
import time

import pytest
from PIL import Image

from wafer.core.ipc.broker import Broker
from wafer.utils.paths import normalize_path
from wafer.plugin.collector.handler import collector_resolver


def _create_test_image(path, width=300, height=200):
    Image.new('RGB', (width, height), color=(80, 120, 200)).save(str(path), format='JPEG')


def _poll_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    return predicate()


class TestSmokeCollector:

    def test_worker_registers_with_broker(self):
        broker = Broker()
        broker.start()
        try:
            from wafer.app.collector.worker import CollectorWorker
            worker = CollectorWorker('testdb', 'exif')
            worker.start()
            try:
                assert worker._node.wait_registered(timeout=5.0)
                assert _poll_until(
                    lambda: any(
                        'collector' in role
                        for role in broker.peer_counts()
                    )
                )
            finally:
                worker.stop()
        finally:
            broker.stop()

    def test_worker_processes_batch(self, tmp_path):
        img_dir = tmp_path / 'images'
        img_dir.mkdir()
        for name in ['alpha.jpg', 'beta.jpg']:
            _create_test_image(img_dir / name)

        paths = [
            normalize_path(str(img_dir / 'alpha.jpg')),
            normalize_path(str(img_dir / 'beta.jpg')),
        ]
        file_info = {}
        for p in paths:
            st = os.stat(p)
            file_info[p] = (st.st_mtime, st.st_size)

        broker = Broker()
        broker.start()
        try:
            from wafer.app.collector.worker import CollectorWorker
            worker = CollectorWorker('testdb', 'exif')
            worker.start()
            try:
                assert worker._node.wait_registered(timeout=5.0)

                captured = {}
                orig_send_reliable = worker._node.send_reliable

                def _capture_send(topic, payload=None, **kw):
                    captured['topic'] = topic
                    captured['payload'] = payload

                worker._node.send_reliable = _capture_send
                worker._process_batch(paths, file_info)

                assert captured.get('topic') == 'collect.result'
                results = captured['payload']['results']
                assert len(results) == 2
                for r in results:
                    assert r.get('status') is True or r.get('status') == 1
                    assert r.get('source') is not None
                    assert r.get('aspect') is not None
            finally:
                worker._node.send_reliable = orig_send_reliable
                worker.stop()
        finally:
            broker.stop()

    def test_exif_plugin_processes_image_directly(self, tmp_path):
        img_path = tmp_path / 'test.jpg'
        _create_test_image(img_path, 400, 300)
        norm_path = normalize_path(str(img_path))
        st = os.stat(norm_path)
        info = (st.st_mtime, st.st_size)

        plugin = collector_resolver.registry.get('exif')()
        result = plugin.process(norm_path, info)

        assert result.status is True
        assert result.aspect is not None
        assert abs(result.aspect - 400 / 300) < 0.01

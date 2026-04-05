import py_compile
from unittest.mock import MagicMock, call

import pytest

from wafer.app.indexer.detacher_receiver import (
    trigger_detacher_pending, _build_source_keys,
)
from wafer.plugin.detacher.handler import detacher_resolver
from wafer.plugin.detacher.base import BaseDetacher, DetacherResult


class _FakeDetacherA(BaseDetacher):
    NAME = '_test_det_a'
    PRIORITY = 10
    TRIGGER_KEYS = ('exif.Comment',)

    def process(self, path, file_info, metadata):
        return DetacherResult(source=path, status=True)


class _FakeDetacherB(BaseDetacher):
    NAME = '_test_det_b'
    PRIORITY = 10
    TRIGGER_KEYS = ('wd14.general',)

    def process(self, path, file_info, metadata):
        return DetacherResult(source=path, status=True)


@pytest.fixture(autouse=True)
def _register():
    detacher_resolver.registry.register(_FakeDetacherA)
    detacher_resolver.registry.register(_FakeDetacherB)
    yield
    detacher_resolver.registry._plugins.pop(_FakeDetacherA.NAME, None)
    detacher_resolver.registry._instances.pop(_FakeDetacherA.NAME, None)
    detacher_resolver.registry._plugins.pop(_FakeDetacherB.NAME, None)
    detacher_resolver.registry._instances.pop(_FakeDetacherB.NAME, None)


def test_compile():
    py_compile.compile('wafer/app/indexer/detacher_receiver.py')


def test_trigger_empty_source_keys():
    writer = MagicMock()
    trigger_detacher_pending({}, writer)
    writer.insert_pending.assert_not_called()


def test_trigger_no_matching_keys():
    writer = MagicMock()
    source_keys = {'/a.png': {'exif.Width', 'exif.Height'}}
    trigger_detacher_pending(source_keys, writer)
    writer.insert_pending.assert_not_called()


def test_trigger_filters_sources_by_key():
    writer = MagicMock()
    source_keys = {
        '/a.png': {'exif.Comment', 'exif.Width'},
        '/b.png': {'exif.Width'},
        '/c.png': {'exif.Comment'},
    }
    trigger_detacher_pending(source_keys, writer)
    args = writer.insert_pending.call_args[0]
    sources = sorted(args[0])
    assert sources == ['/a.png', '/c.png']
    assert args[1] == ['_test_det_a']


def test_trigger_multiple_detachers():
    writer = MagicMock()
    source_keys = {
        '/a.png': {'exif.Comment'},
        '/b.png': {'wd14.general'},
        '/c.png': {'exif.Comment', 'wd14.general'},
    }
    trigger_detacher_pending(source_keys, writer)
    assert writer.insert_pending.call_count == 2
    calls = writer.insert_pending.call_args_list
    det_a_call = [c for c in calls if c[0][1] == ['_test_det_a']][0]
    det_b_call = [c for c in calls if c[0][1] == ['_test_det_b']][0]
    assert sorted(det_a_call[0][0]) == ['/a.png', '/c.png']
    assert sorted(det_b_call[0][0]) == ['/b.png', '/c.png']


def test_trigger_calls_request_dispatch():
    writer = MagicMock()
    dispatch = MagicMock()
    source_keys = {'/a.png': {'exif.Comment'}}
    trigger_detacher_pending(source_keys, writer, request_dispatch=dispatch)
    dispatch.assert_called_once()


def test_trigger_no_dispatch_when_no_match():
    writer = MagicMock()
    dispatch = MagicMock()
    source_keys = {'/a.png': {'unrelated.key'}}
    trigger_detacher_pending(source_keys, writer, request_dispatch=dispatch)
    dispatch.assert_not_called()


def test_build_source_keys_meta_info():
    data = {
        'meta_info_entries': [
            ('/a.png', 'exif.Comment', 'val', None),
            ('/a.png', 'exif.Width', '100', 100.0),
            ('/b.png', 'exif.Height', '200', 200.0),
        ],
        'tag_entries': [],
    }
    result = _build_source_keys(data)
    assert result == {
        '/a.png': {'exif.Comment', 'exif.Width'},
        '/b.png': {'exif.Height'},
    }


def test_build_source_keys_with_tags():
    data = {
        'meta_info_entries': [
            ('/a.png', 'exif.Comment', 'val', None),
        ],
        'tag_entries': [
            ('hash1', 'wd14.general', 'tags', None),
        ],
    }
    result = _build_source_keys(data)
    assert result['/a.png'] == {'exif.Comment'}
    assert result['hash1'] == {'wd14.general'}


def test_build_source_keys_empty():
    data = {'meta_info_entries': [], 'tag_entries': []}
    assert _build_source_keys(data) == {}

import pytest
from wafer.plugin.detacher.base import (
    BaseDetacher,
    BaseDetacherPlugin,
    BaseSingletonDetacher,
    DetacherResult,
)


class DummyDetacher(BaseDetacherPlugin):
    NAME = "dummy"
    TRIGGER_KEYS = ("exif.parameters",)
    DEFAULT_ENABLED = True

    def process(self, path, file_info, metadata):
        return DetacherResult(source=path, status=True, meta_info={"sd.prompt": "test"})


class DummySingleton(BaseSingletonDetacher):
    NAME = "dummy_s"
    TRIGGER_KEYS = ("exif.Comment",)
    DEFAULT_ENABLED = True

    def process(self, path, file_info, metadata):
        return DetacherResult(source=path, status=True)


def test_detacher_result_to_dict():
    r = DetacherResult(source="/a.png", status=True, meta_info={"k": "v"})
    d = r.to_dict()
    assert d["source"] == "/a.png"
    assert d["status"] is True
    assert d["meta_info"] == {"k": "v"}
    assert "tags" not in d
    assert "delete_keys" not in d


def test_detacher_result_with_delete_keys():
    r = DetacherResult(source="/a.png", status=True, delete_keys=["exif.parameters"])
    d = r.to_dict()
    assert d["delete_keys"] == ["exif.parameters"]


def test_detacher_result_fail():
    r = DetacherResult(source="/a.png", status=False)
    d = r.to_dict()
    assert d["status"] is False
    assert "meta_info" not in d


def test_base_detacher_plugin_batch_size():
    assert DummyDetacher.BATCH_SIZE == 1200


def test_base_singleton_detacher_batch_size():
    assert DummySingleton.BATCH_SIZE == 300


def test_trigger_keys():
    assert DummyDetacher.TRIGGER_KEYS == ("exif.parameters",)
    assert DummySingleton.TRIGGER_KEYS == ("exif.Comment",)


def test_process():
    d = DummyDetacher()
    result = d.process("/a.png", (0.0, 0), {"exif.parameters": "steps:20"})
    assert result.status is True
    assert result.meta_info == {"sd.prompt": "test"}


def test_inheritance():
    assert issubclass(BaseDetacherPlugin, BaseDetacher)
    assert issubclass(BaseSingletonDetacher, BaseDetacher)
    assert not issubclass(BaseDetacherPlugin, BaseSingletonDetacher)

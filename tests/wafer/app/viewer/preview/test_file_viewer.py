import py_compile
from unittest.mock import MagicMock
from wafer.app.viewer.preview.file_viewer import _format_meta


def test_compile():
    py_compile.compile('wafer/app/viewer/preview/file_viewer.py')


def test_format_meta_strips_status_and_source():
    engine = MagicMock()
    engine.get_all_metadata.return_value = (
        {"path": "/a.png", "status": "active", "size": 1024, "modified": 0, "created": 0, "collected": 0},
        {"source": "/a.png", "width": 100, "height": 200},
        {},
        {},
    )
    result = _format_meta(engine, "/a.png")
    source, image, tags, meta = result
    assert "status" not in source
    assert "source" not in image


def test_format_meta_formats_size_and_timestamps():
    engine = MagicMock()
    engine.get_all_metadata.return_value = (
        {"size": 2048, "modified": 1700000000, "created": 1700000000, "collected": 1700000000},
        {},
        {},
        {},
    )
    result = _format_meta(engine, "/a.png")
    source = result[0]
    assert isinstance(source["size"], str)
    assert isinstance(source["modified"], str)
    assert isinstance(source["created"], str)
    assert isinstance(source["collected"], str)


def test_format_meta_sorts_tags_and_meta():
    engine = MagicMock()
    engine.get_all_metadata.return_value = (
        {"size": 0, "modified": 0, "created": 0, "collected": 0},
        {},
        {"z_tag": "1", "a_tag": "2"},
        {"z_key": "x", "a_key": "y"},
    )
    result = _format_meta(engine, "/a.png")
    tags = result[2]
    meta = result[3]
    assert list(tags.keys()) == ["a_tag", "z_tag"]
    assert list(meta.keys()) == ["a_key", "z_key"]


def test_format_meta_aspect_ratio():
    engine = MagicMock()
    engine.get_all_metadata.return_value = (
        {"size": 0, "modified": 0, "created": 0, "collected": 0},
        {"aspect_ratio": 1.5},
        {},
        {},
    )
    result = _format_meta(engine, "/a.png")
    image = result[1]
    assert isinstance(image["aspect_ratio"], str)

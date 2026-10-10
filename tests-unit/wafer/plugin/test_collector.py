import pytest

from wafer.plugin.collector.handler import collector_resolver
from wafer.plugin.collector.base import CollectorResult
from wafer.plugin.collector.base import BaseCollector, BaseCollectorPlugin, BaseSingletonCollector


def _get_exif_plugin():
    return collector_resolver.registry.get("exiftool")


def test_base_is_abstract():
    for base in (BaseCollector, BaseCollectorPlugin, BaseSingletonCollector):
        with pytest.raises(TypeError):
            base()


def test_exif_plugin_registered():
    names = collector_resolver.names()
    assert "exiftool" in names


def test_exif_plugin_match():
    ExifCollectorPlugin = _get_exif_plugin()
    assert ExifCollectorPlugin.match("photo.jpg")
    assert ExifCollectorPlugin.match("image.png")
    assert not ExifCollectorPlugin.match("video.mp4")


def test_get_collector_summary():
    info = collector_resolver.summary()
    assert len(info) >= 1
    name, exts = info[0]
    assert name == "exiftool"
    assert ".jpg" in exts


def test_collectors_for_path_image():
    assert "exiftool" in collector_resolver.collectors_for_path("photo.jpg")


def test_collectors_for_path_non_image():
    assert "exiftool" not in collector_resolver.collectors_for_path("doc.txt")


def test_exif_plugin_process_success(tmp_path):
    from PIL import Image
    import os
    from wafer.core.common.paths import normalize_path

    img_path = tmp_path / "test.png"
    Image.new("RGB", (100, 200)).save(str(img_path))
    st = os.stat(str(img_path))
    file_info = (st.st_mtime, st.st_size)

    plugin = _get_exif_plugin()()
    result = plugin.process(normalize_path(str(img_path)), file_info)
    assert isinstance(result, CollectorResult)
    assert result.status is True
    assert result.name is None
    assert result.aspect is not None
    assert result.meta_info
    for key in result.meta_info:
        assert "." not in key, f"meta_info key should not have prefix: {key}"
    assert "file_hash" not in result.to_dict()


def test_collector_result_to_dict_omits_none():
    r = CollectorResult(source="test.png", status=True, name="test.png", aspect=1.5)
    d = r.to_dict()
    assert d == {"source": "test.png", "status": True, "name": "test.png", "aspect": 1.5}


def test_collector_result_does_not_accept_file_hash():
    with pytest.raises(TypeError):
        CollectorResult(source="test.png", status=True, file_hash="hash")


def test_notify_to_sends_ipc():
    from unittest.mock import MagicMock, patch

    mock_node = MagicMock()
    mock_registry = MagicMock()
    mock_registry.resolve_node.return_value = mock_node

    with patch("wafer.qt.commands.binding.instance_registry.InstanceRegistry.instance", return_value=mock_registry):
        BaseCollectorPlugin.notify_to("blip", payload={"min_length": 10})

    mock_node.send.assert_called_once_with("plugin.notify", {"min_length": 10}, dst="collector-blip")


def test_notify_to_no_node():
    from unittest.mock import MagicMock, patch

    mock_registry = MagicMock()
    mock_registry.resolve_node.return_value = None

    with patch("wafer.qt.commands.binding.instance_registry.InstanceRegistry.instance", return_value=mock_registry):
        BaseCollectorPlugin.notify_to("exiftool")


def test_singleton_names_excludes_normal():
    singleton_names = collector_resolver.singleton_names()
    per_indexer_names = collector_resolver.per_indexer_names()
    for name in singleton_names:
        assert name not in per_indexer_names
    for name in per_indexer_names:
        assert name not in singleton_names
    assert set(singleton_names + per_indexer_names) == set(collector_resolver.names())


def test_batch_size_for_known_collector():
    for name in collector_resolver.names():
        assert collector_resolver.batch_size(name) > 0
        assert collector_resolver.max_workers(name) >= 1
        assert collector_resolver.batch_timeout(name) > 0


def test_batch_size_for_unknown_collector():
    assert collector_resolver.batch_size("nonexistent") == 1200


def test_execution_settings_for_unknown_collector():
    assert collector_resolver.max_workers("nonexistent") == 1
    assert collector_resolver.batch_timeout("nonexistent") == 300.0


def test_exif_is_per_indexer():
    assert "exiftool" in collector_resolver.per_indexer_names()
    assert "exiftool" not in collector_resolver.singleton_names()


def test_collector_result_to_dict_includes_false_status():
    r = CollectorResult(source="bad.png", status=False, name="bad.png")
    d = r.to_dict()
    assert d["status"] is False
    assert "source" in d


def test_process_failure_to_dict_omits_none(tmp_path):
    plugin = _get_exif_plugin()()
    result = plugin.process(str(tmp_path / "missing.png"), (0.0, 0))
    d = result.to_dict()
    assert d["status"] is False
    for v in d.values():
        assert v is not None

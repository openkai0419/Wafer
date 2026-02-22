import py_compile
import pytest

from source.io.collector import (
    collector_registry,
    get_collector_names,
    get_collector_info,
    get_collectors_for_path,
    CollectorResult,
)
from source.io.collector.base import BaseCollectorPlugin
from source.io.collector.image import ImageCollectorPlugin


def test_compile_base():
    py_compile.compile('source/io/collector/base.py')


def test_compile_image():
    py_compile.compile('source/io/collector/image.py')


def test_compile_init():
    py_compile.compile('source/io/collector/__init__.py')


def test_base_is_abstract():
    with pytest.raises(TypeError):
        BaseCollectorPlugin()


def test_image_plugin_registered():
    names = collector_registry.names()
    assert 'image' in names


def test_image_plugin_priority():
    assert ImageCollectorPlugin.PRIORITY == 100


def test_image_plugin_match():
    assert ImageCollectorPlugin.match('photo.jpg')
    assert ImageCollectorPlugin.match('image.png')
    assert not ImageCollectorPlugin.match('video.mp4')


def test_get_collector_names():
    names = get_collector_names()
    assert 'image' in names


def test_get_collector_info():
    info = get_collector_info()
    assert len(info) >= 1
    name, exts = info[0]
    assert name == 'image'
    assert '.jpg' in exts


def test_get_collectors_for_path_image():
    assert 'image' in get_collectors_for_path('photo.jpg')


def test_get_collectors_for_path_non_image():
    assert 'image' not in get_collectors_for_path('doc.txt')


def test_image_plugin_process_success(tmp_path):
    from PIL import Image
    import os
    from source.common.funcs import normalize_path
    img_path = tmp_path / 'test.png'
    Image.new('RGB', (100, 200)).save(str(img_path))
    st = os.stat(str(img_path))
    ctime = st.st_birthtime if hasattr(st, 'st_birthtime') else st.st_ctime
    file_info = (st.st_mtime, st.st_size, ctime)

    plugin = ImageCollectorPlugin()
    result = plugin.process(normalize_path(str(img_path)), file_info)
    assert isinstance(result, CollectorResult)
    assert result.status is True
    assert result.name == 'test.png'
    assert result.aspect is not None
    assert result.file_hash


def test_image_plugin_process_failure():
    plugin = ImageCollectorPlugin()
    result = plugin.process('nonexistent.png', (0.0, 0, 0.0))
    assert isinstance(result, CollectorResult)
    assert result.status is False


def test_registry_get_by_name():
    assert collector_registry.get('image') is ImageCollectorPlugin
    assert collector_registry.get('nonexistent') is None


def test_collector_result_to_dict_omits_none():
    r = CollectorResult(source='test.png', status=True, name='test.png', aspect=1.5)
    d = r.to_dict()
    assert d == {'source': 'test.png', 'status': True, 'name': 'test.png', 'aspect': 1.5}
    assert 'path' not in d
    assert 'file_hash' not in d
    assert 'meta_info' not in d
    assert 'tags' not in d


def test_collector_result_to_dict_includes_false_status():
    r = CollectorResult(source='bad.png', status=False, name='bad.png')
    d = r.to_dict()
    assert d['status'] is False
    assert 'source' in d


def test_collector_result_to_dict_with_meta():
    r = CollectorResult(
        source='img.png', status=True, name='img.png',
        meta_info={'width': '100'}, tags={'rating': '5'},
    )
    d = r.to_dict()
    assert d['meta_info'] == {'width': '100'}
    assert d['tags'] == {'rating': '5'}


def test_process_success_to_dict(tmp_path):
    from PIL import Image
    import os
    from source.common.funcs import normalize_path
    img_path = tmp_path / 'keys.png'
    Image.new('RGB', (50, 50)).save(str(img_path))
    st = os.stat(str(img_path))
    ctime = st.st_birthtime if hasattr(st, 'st_birthtime') else st.st_ctime
    file_info = (st.st_mtime, st.st_size, ctime)

    plugin = ImageCollectorPlugin()
    result = plugin.process(normalize_path(str(img_path)), file_info)
    d = result.to_dict()
    assert d['status'] is True
    for v in d.values():
        assert v is not None


def test_process_failure_to_dict_omits_none(tmp_path):
    plugin = ImageCollectorPlugin()
    result = plugin.process(str(tmp_path / 'missing.png'), (0.0, 0, 0.0))
    d = result.to_dict()
    assert d['status'] is False
    for v in d.values():
        assert v is not None

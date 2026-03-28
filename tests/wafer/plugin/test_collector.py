import py_compile
import pytest

from wafer.plugin.collector.handler import collector_resolver
from wafer.plugin.collector.base import CollectorResult
from wafer.plugin.collector.base import BaseCollector, BaseCollectorPlugin, BaseSingletonCollector


def _get_exif_plugin():
    return collector_resolver.registry.get('exif')


def test_compile_base():
    py_compile.compile('wafer/plugin/collector/base.py')


def test_compile_handler():
    py_compile.compile('wafer/plugin/collector/handler.py')


def test_base_is_abstract():
    with pytest.raises(TypeError):
        BaseCollectorPlugin()


def test_exif_plugin_registered():
    names = collector_resolver.names()
    assert 'exif' in names


def test_exif_plugin_priority():
    assert _get_exif_plugin().PRIORITY == 100


def test_exif_plugin_match():
    ExifCollectorPlugin = _get_exif_plugin()
    assert ExifCollectorPlugin.match('photo.jpg')
    assert ExifCollectorPlugin.match('image.png')
    assert not ExifCollectorPlugin.match('video.mp4')


def test_get_collector_names():
    names = collector_resolver.names()
    assert 'exif' in names


def test_get_collector_summary():
    info = collector_resolver.summary()
    assert len(info) >= 1
    name, exts = info[0]
    assert name == 'exif'
    assert '.jpg' in exts


def test_collectors_for_path_image():
    assert 'exif' in collector_resolver.collectors_for_path('photo.jpg')


def test_collectors_for_path_non_image():
    assert 'exif' not in collector_resolver.collectors_for_path('doc.txt')


def test_exif_plugin_process_success(tmp_path):
    from PIL import Image
    import os
    from wafer.utils.paths import normalize_path
    img_path = tmp_path / 'test.png'
    Image.new('RGB', (100, 200)).save(str(img_path))
    st = os.stat(str(img_path))
    file_info = (st.st_mtime, st.st_size)

    plugin = _get_exif_plugin()()
    result = plugin.process(normalize_path(str(img_path)), file_info)
    assert isinstance(result, CollectorResult)
    assert result.status is True
    assert result.name is None
    assert result.file_hash is None
    assert result.aspect is not None
    if result.meta_info:
        for key in result.meta_info:
            assert key.startswith('exif.'), f'meta_info key missing prefix: {key}'


def test_exif_plugin_process_failure():
    plugin = _get_exif_plugin()()
    result = plugin.process('nonexistent.png', (0.0, 0))
    assert isinstance(result, CollectorResult)
    assert result.status is False


def test_registry_get_by_name():
    ExifCollectorPlugin = _get_exif_plugin()
    assert collector_resolver.registry.get('exif') is ExifCollectorPlugin
    assert collector_resolver.registry.get('nonexistent') is None


def test_collector_result_to_dict_omits_none():
    r = CollectorResult(source='test.png', status=True, name='test.png', aspect=1.5)
    d = r.to_dict()
    assert d == {'source': 'test.png', 'status': True, 'name': 'test.png', 'aspect': 1.5}


def test_base_collector_is_abstract():
    with pytest.raises(TypeError):
        BaseCollector()


def test_base_singleton_is_abstract():
    with pytest.raises(TypeError):
        BaseSingletonCollector()


def test_base_collector_hierarchy():
    assert issubclass(BaseCollectorPlugin, BaseCollector)
    assert issubclass(BaseSingletonCollector, BaseCollector)


def test_base_collector_defaults():
    assert not issubclass(BaseCollectorPlugin, BaseSingletonCollector)
    assert BaseCollectorPlugin.BATCH_SIZE == 1200
    assert issubclass(BaseSingletonCollector, BaseCollector)
    assert BaseSingletonCollector.BATCH_SIZE == 32


def test_concrete_collector_plugin():
    class MyCollector(BaseCollectorPlugin):
        NAME = 'test_concrete'
        EXTENSIONS = ('.test',)
        def process(self, path, file_info):
            return CollectorResult(source=path, status=True)

    assert not issubclass(MyCollector, BaseSingletonCollector)
    assert MyCollector.BATCH_SIZE == 1200
    inst = MyCollector()
    r = inst.process('file.test', (0.0, 0))
    assert r.status is True


def test_concrete_singleton_collector():
    class MySingleton(BaseSingletonCollector):
        NAME = 'test_singleton'
        EXTENSIONS = ('.jpg', '.png')
        BATCH_SIZE = 16
        def process(self, path, file_info):
            return CollectorResult(source=path, status=True)

    assert issubclass(MySingleton, BaseSingletonCollector)
    assert MySingleton.BATCH_SIZE == 16
    inst = MySingleton()
    r = inst.process('photo.jpg', (0.0, 0))
    assert r.status is True


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
        bs = collector_resolver.batch_size(name)
        assert bs > 0


def test_batch_size_for_unknown_collector():
    assert collector_resolver.batch_size('nonexistent') == 1200


def test_exif_is_per_indexer():
    assert 'exif' in collector_resolver.per_indexer_names()
    assert 'exif' not in collector_resolver.singleton_names()


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
    from wafer.utils.paths import normalize_path
    img_path = tmp_path / 'keys.png'
    Image.new('RGB', (50, 50)).save(str(img_path))
    st = os.stat(str(img_path))
    file_info = (st.st_mtime, st.st_size)

    plugin = _get_exif_plugin()()
    result = plugin.process(normalize_path(str(img_path)), file_info)
    d = result.to_dict()
    assert d['status'] is True
    assert 'name' not in d
    assert 'file_hash' not in d
    assert 'aspect' in d


def test_process_failure_to_dict_omits_none(tmp_path):
    plugin = _get_exif_plugin()()
    result = plugin.process(str(tmp_path / 'missing.png'), (0.0, 0))
    d = result.to_dict()
    assert d['status'] is False
    for v in d.values():
        assert v is not None

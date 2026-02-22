import py_compile

from source.image_collector.plugin import (
    BaseCollectorPlugin, ImageCollectorPlugin, BUILTIN_PLUGINS,
    get_collector_names, get_collector_info, get_collectors_for_path,
)


def test_compile():
    py_compile.compile('source/image_collector/plugin.py')


def test_base_plugin_is_abstract():
    import pytest
    with pytest.raises(TypeError):
        BaseCollectorPlugin()


def test_image_plugin_name_and_extensions():
    assert ImageCollectorPlugin.NAME == 'image'
    assert '.jpg' in ImageCollectorPlugin.EXTENSIONS
    assert '.png' in ImageCollectorPlugin.EXTENSIONS


def test_builtin_plugins_contains_image():
    assert 'image' in BUILTIN_PLUGINS
    assert BUILTIN_PLUGINS['image'] is ImageCollectorPlugin


def test_image_plugin_process_success(tmp_path):
    from PIL import Image
    img_path = tmp_path / 'test.png'
    Image.new('RGB', (100, 200)).save(str(img_path))
    import os
    st = os.stat(str(img_path))
    ctime = st.st_birthtime if hasattr(st, 'st_birthtime') else st.st_ctime
    file_info = (st.st_mtime, st.st_size, ctime)

    from source.common.funcs import normalize_path
    norm = normalize_path(str(img_path))
    plugin = ImageCollectorPlugin()
    result = plugin.process(norm, file_info)

    assert result['status'] == 'ok'
    assert result['source'] == norm
    assert result['info']['name'] == 'test.png'
    assert result['info']['aspect'] is not None
    assert isinstance(result['meta_info'], dict)


def test_image_plugin_process_failure(tmp_path):
    bad_path = tmp_path / 'nonexistent.png'
    plugin = ImageCollectorPlugin()
    result = plugin.process(str(bad_path), (0.0, 0, 0.0))

    assert result['status'] == 'fail'
    assert result['info']['aspect'] is None
    assert result['meta_info'] == {}


def test_get_collector_names():
    names = get_collector_names()
    assert 'image' in names
    assert isinstance(names, list)


def test_get_collector_info():
    info = get_collector_info()
    assert isinstance(info, list)
    assert len(info) >= 1
    name, exts = info[0]
    assert name == 'image'
    assert '.jpg' in exts


def test_get_collectors_for_path_image():
    collectors = get_collectors_for_path('photo.jpg')
    assert 'image' in collectors


def test_get_collectors_for_path_non_image():
    collectors = get_collectors_for_path('document.txt')
    assert 'image' not in collectors

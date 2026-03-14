import py_compile
from unittest.mock import MagicMock, patch, PropertyMock
from wafer.app.viewer.preview.file_viewer import _format_meta, FileViewerWidget, _DEFAULT_WIDGET_NAME
from wafer.plugin.viewer.base import WidgetViewerPlugin, ImageViewerPlugin


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


class _StubWidgetPlugin(WidgetViewerPlugin):
    NAME = 'stub_widget'
    EXTENSIONS = ('.mp4',)
    PRIORITY = 100
    WIDGET_CLASS = MagicMock


def _make_viewer_stub():
    viewer = MagicMock(spec=FileViewerWidget)
    viewer._pending_meta = None
    viewer._pending_content = None
    viewer._loading_path = None
    viewer._target_plugin = None
    viewer._current_plugin_name = _DEFAULT_WIDGET_NAME

    stub_widget = MagicMock()
    default_widget = MagicMock()
    viewer.image_viewer = default_widget
    viewer.meta_viewer = MagicMock()
    viewer._stack = MagicMock()
    viewer._widget_map = {
        _DEFAULT_WIDGET_NAME: default_widget,
        'stub_widget': stub_widget,
    }

    viewer._try_show = lambda: FileViewerWidget._try_show(viewer)
    viewer._switch_to = lambda name: FileViewerWidget._switch_to(viewer, name)
    viewer._on_path_changed = lambda path: FileViewerWidget._on_path_changed(viewer, path)
    viewer._load_and_show_content = lambda path: FileViewerWidget._load_and_show_content(viewer, path)
    viewer._update_meta = MagicMock()
    return viewer


def test_try_show_does_not_switch_when_content_missing():
    viewer = _make_viewer_stub()
    viewer._target_plugin = _DEFAULT_WIDGET_NAME
    viewer._pending_meta = [{'size': '0'}, {}, {}, {}]
    viewer._pending_content = None
    viewer._try_show()
    assert viewer._pending_meta is not None


def test_try_show_does_not_switch_when_meta_missing():
    viewer = _make_viewer_stub()
    viewer._target_plugin = _DEFAULT_WIDGET_NAME
    viewer._pending_content = ('/a.png', MagicMock())
    viewer._pending_meta = None
    viewer._try_show()
    assert viewer._pending_content is not None


def test_try_show_switches_after_both_ready_for_image():
    viewer = _make_viewer_stub()
    viewer._target_plugin = _DEFAULT_WIDGET_NAME
    img = MagicMock()
    viewer._pending_content = ('/a.png', img)
    viewer._pending_meta = [{'size': '0'}, {}, {}, {}]

    viewer._try_show()

    assert viewer._current_plugin_name == _DEFAULT_WIDGET_NAME
    viewer.image_viewer.set_image.assert_called_once_with(img, '/a.png')
    viewer.meta_viewer.set_data.assert_called_once()
    assert viewer._pending_content is None
    assert viewer._pending_meta is None


def test_try_show_switches_after_both_ready_for_widget_plugin():
    viewer = _make_viewer_stub()
    viewer._target_plugin = 'stub_widget'
    viewer._pending_content = ('/a.mp4', None)
    viewer._pending_meta = [{'size': '0'}, {}, {}, {}]

    call_order = []
    with patch('wafer.app.viewer.preview.file_viewer.viewer_resolver') as mock_resolver:
        mock_resolver.render = lambda w, p: call_order.append('render')

        def tracking_switch(name):
            call_order.append('switch')
            FileViewerWidget._switch_to(viewer, name)
        viewer._switch_to = tracking_switch
        viewer._try_show = lambda: FileViewerWidget._try_show(viewer)

        viewer._try_show()

    assert call_order == ['render', 'switch']
    assert viewer._current_plugin_name == 'stub_widget'


def test_on_path_changed_widget_does_not_switch_immediately():
    viewer = _make_viewer_stub()
    viewer._dispatcher = MagicMock()
    viewer._meta_cancel = MagicMock()
    viewer._content_cancel = MagicMock()
    viewer.model = MagicMock()
    viewer.model.dbpath = None

    initial_plugin = viewer._current_plugin_name
    with patch('wafer.app.viewer.preview.file_viewer.viewer_resolver') as mock_resolver:
        mock_resolver.resolve.return_value = _StubWidgetPlugin
        viewer._on_path_changed('/test.mp4')

    assert viewer._current_plugin_name == initial_plugin
    assert viewer._target_plugin == 'stub_widget'


def test_on_path_changed_image_does_not_switch_immediately():
    viewer = _make_viewer_stub()
    viewer._dispatcher = MagicMock()
    viewer._meta_cancel = MagicMock()
    viewer._content_cancel = MagicMock()
    viewer.image_cache = MagicMock()
    viewer.image_cache.get.return_value = None
    viewer.model = MagicMock()
    viewer.model.dbpath = None

    initial_plugin = viewer._current_plugin_name
    with patch('wafer.app.viewer.preview.file_viewer.viewer_resolver') as mock_resolver:
        mock_resolver.resolve.return_value = None
        viewer._on_path_changed('/test.png')

    assert viewer._current_plugin_name == initial_plugin
    assert viewer._target_plugin == _DEFAULT_WIDGET_NAME

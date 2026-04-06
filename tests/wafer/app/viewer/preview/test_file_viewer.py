import py_compile
from unittest.mock import MagicMock, patch, PropertyMock
from wafer.app.viewer.preview.file_viewer import _format_meta, FileViewerController, _DEFAULT_WIDGET_NAME
from wafer.app.viewer.preview.content_viewer import ContentViewerWidget
from wafer.plugin.viewer.base import WidgetViewerPlugin, ImageViewerPlugin


def _mock_engine(**overrides):
    engine = MagicMock()
    defaults = {
        'get_all_metadata': (
            {"path": "/a.png", "source": "/a.png", "name": "a.png", "aspect_ratio": None},
            {},
            {},
        ),
        'get_collection_status': [],
    }
    defaults.update(overrides)
    engine.get_all_metadata.return_value = defaults['get_all_metadata']
    engine.get_collection_status.return_value = defaults['get_collection_status']
    return engine


def test_compile():
    py_compile.compile('wafer/app/viewer/preview/file_viewer.py')


def test_format_meta_source_same_as_path():
    engine = _mock_engine()
    meta_items = _format_meta(engine, "/a.png")
    file_rec = meta_items[0]
    assert "path" not in file_rec
    assert file_rec["source"] == "/a.png"


def test_format_meta_source_differs_from_path():
    engine = _mock_engine(get_all_metadata=(
        {"path": "/a.png", "source": "/other/a.png", "name": "a.png", "aspect_ratio": None},
        {},
        {},
    ))
    meta_items = _format_meta(engine, "/a.png")
    file_rec = meta_items[0]
    assert "path" not in file_rec
    assert file_rec["source"] == "/other/a.png"


def test_format_meta_formats_size_and_timestamps():
    engine = _mock_engine(get_all_metadata=(
        {"path": "/a.png", "source": "/a.png", "name": "a.png", "aspect_ratio": None},
        {},
        {"created": "1700000000", "collected": "1700000000", "modified": "1700000000", "size": "2048"},
    ))
    meta_items = _format_meta(engine, "/a.png")
    standard = meta_items[1]
    assert isinstance(standard["created"], str)
    assert isinstance(standard["collected"], str)
    assert isinstance(standard["modified"], str)
    assert isinstance(standard["size"], str)


def test_format_meta_sorts_tags_and_meta():
    engine = _mock_engine(get_all_metadata=(
        {"path": "/a.png", "source": "/a.png", "name": "a.png", "aspect_ratio": None},
        {"z_tag": "1", "a_tag": "2"},
        {"name": "a.png", "size": "1024", "exif.width": "100"},
    ))
    meta_items = _format_meta(engine, "/a.png")
    tags = meta_items[2]
    standard = meta_items[1]
    assert list(tags.keys()) == ["a_tag", "z_tag"]
    assert "name" in standard
    assert "size" in standard


def test_format_meta_aspect_ratio():
    engine = _mock_engine(get_all_metadata=(
        {"path": "/a.png", "source": "/a.png", "name": "a.png", "aspect_ratio": 1.5},
        {},
        {},
    ))
    meta_items = _format_meta(engine, "/a.png")
    file_rec = meta_items[0]
    assert isinstance(file_rec["aspect_ratio"], str)


def test_format_meta_splits_prefixed_meta():
    engine = _mock_engine(get_all_metadata=(
        {"path": "/a.png", "source": "/a.png", "name": "a.png", "aspect_ratio": None},
        {},
        {"name": "a.png", "size": "1024", "exif.width": "100", "exif.height": "200"},
    ))
    meta_items = _format_meta(engine, "/a.png")
    standard = meta_items[1]
    prefixed = meta_items[3]
    assert "name" in standard
    assert "size" in standard
    assert "exif.width" not in standard
    assert "exif.width" in prefixed
    assert "exif.height" in prefixed


def test_format_meta_embeds_collector_html():
    engine = _mock_engine(get_collection_status=[('exif', 'ok'), ('animated', 'fail')])
    meta_items = _format_meta(engine, "/a.png")
    file_rec = meta_items[0]
    assert 'collected by' in file_rec
    assert '\u25cf' in file_rec['collected by']
    assert 'animated' in file_rec['collected by']
    assert 'exif' in file_rec['collected by']


class TestAutoplayState:

    def _make_controller(self, qtbot):
        from wafer.app.viewer.preview.file_model import FileViewModel
        from wafer.app.viewer.preview.meta_panel import MetaViewerWidget
        model = FileViewModel()
        cv = ContentViewerWidget()
        mv = MetaViewerWidget()
        qtbot.addWidget(cv)
        qtbot.addWidget(mv)
        w = FileViewerController(model, cv, mv)
        return w, model

    def test_save_state_includes_autoplay(self, qtbot):
        w, _ = self._make_controller(qtbot)
        w._autoplay_interval = 5000
        w._autoplay_loop = False
        state = w._save_state()
        assert state['autoplay_interval'] == 5000
        assert state['autoplay_loop'] is False
        assert 'autoplay_active' not in state

    def test_restore_state_sets_autoplay_fields(self, qtbot):
        w, _ = self._make_controller(qtbot)
        w._restore_state({
            'autoplay_interval': 7000,
            'autoplay_loop': True,
        })
        assert w._autoplay_interval == 7000
        assert w._autoplay_loop is True
        assert w._autoplay_active is False

    def test_restore_state_resets_slideshow_checkbox(self, qtbot):
        w, _ = self._make_controller(qtbot)
        with patch('wafer.app.viewer.preview.file_viewer.Command') as mock_cmd:
            w._restore_state({'autoplay_interval': 3000})
            mock_cmd.set_checked.assert_called_with('fv.toggle_slideshow', False)

    def test_start_stop_autoplay(self, qtbot):
        w, _ = self._make_controller(qtbot)
        w.start_autoplay(interval_ms=2000, loop=False)
        assert w.autoplay_active is True
        assert w._autoplay_interval == 2000
        assert w._autoplay_loop is False
        w.stop_autoplay()
        assert w.autoplay_active is False

    def test_toggle_autoplay(self, qtbot):
        w, _ = self._make_controller(qtbot)
        w.toggle_autoplay(interval_ms=4000)
        assert w.autoplay_active is True
        w.toggle_autoplay()
        assert w.autoplay_active is False

    def test_arm_autoplay_starts_timer_for_default_plugin(self, qtbot):
        w, _ = self._make_controller(qtbot)
        w._autoplay_active = True
        w._autoplay_interval = 1000
        w.content_viewer._current_plugin_name = _DEFAULT_WIDGET_NAME
        w._arm_autoplay()
        assert w._autoplay_timer.isActive()
        assert not w._autoplay_held
        w.stop_autoplay()

    def test_arm_autoplay_holds_for_plugin_returning_true(self, qtbot):
        w, _ = self._make_controller(qtbot)

        class HoldPlugin(WidgetViewerPlugin):
            NAME = '_test_hold'
            EXTENSIONS = ('.test',)
            PRIORITY = 1
            def set_autoplay(self, advance):
                self._advance = advance
                return advance is not None

        from wafer.plugin.viewer.handler import viewer_resolver
        plugin = HoldPlugin()
        viewer_resolver.registry._instances['_test_hold'] = plugin

        w._autoplay_active = True
        w.content_viewer._current_plugin_name = '_test_hold'
        w._arm_autoplay()
        assert w._autoplay_held is True
        assert not w._autoplay_timer.isActive()

        del viewer_resolver.registry._instances['_test_hold']
        w.stop_autoplay()

    def test_generation_guards_stale_advance(self, qtbot):
        from wafer.app.viewer.preview.file_model import FileViewModel
        from wafer.app.viewer.preview.meta_panel import MetaViewerWidget
        model = FileViewModel()
        model.set_items(["a", "b", "c"], None)
        model.set_current_index(0)
        cv = ContentViewerWidget()
        mv = MetaViewerWidget()
        qtbot.addWidget(cv)
        qtbot.addWidget(mv)
        w = FileViewerController(model, cv, mv)
        old_gen = w._autoplay_generation
        w._autoplay_active = True
        w._autoplay_generation += 1
        w._on_plugin_advance(old_gen)
        assert model.current_index() == 0
        w.stop_autoplay()

    def test_interval_min_clamp(self, qtbot):
        w, _ = self._make_controller(qtbot)
        w.start_autoplay(interval_ms=100)
        assert w._autoplay_interval == 500
        w.stop_autoplay()


def test_format_meta_no_collectors_omits_key():
    engine = _mock_engine(get_collection_status=[])
    meta_items = _format_meta(engine, "/a.png")
    file_rec = meta_items[0]
    assert 'collected by' not in file_rec


class _StubWidgetPlugin(WidgetViewerPlugin):
    NAME = 'stub_widget'
    EXTENSIONS = ('.mp4',)
    PRIORITY = 100
    WIDGET_CLASS = MagicMock


def _make_viewer_stub():
    content_viewer = MagicMock(spec=ContentViewerWidget)
    default_widget = MagicMock()
    content_viewer.image_viewer = default_widget
    content_viewer._current_plugin_name = _DEFAULT_WIDGET_NAME
    content_viewer._stack = MagicMock()
    content_viewer._widget_map = {
        _DEFAULT_WIDGET_NAME: default_widget,
        'stub_widget': MagicMock(),
    }

    def switch_to(name):
        content_viewer._current_plugin_name = name
    content_viewer.switch_to = switch_to

    meta_viewer = MagicMock()

    viewer = MagicMock(spec=FileViewerController)
    viewer._pending_meta = None
    viewer._pending_content = None
    viewer._loading_path = None
    viewer._target_plugin = None
    viewer.content_viewer = content_viewer
    viewer.meta_viewer = meta_viewer
    viewer.image_viewer = default_widget

    viewer._flush = lambda: FileViewerController._flush(viewer)
    viewer._switch_to = lambda name: FileViewerController._switch_to(viewer, name)
    viewer._on_path_changed = lambda path: FileViewerController._on_path_changed(viewer, path)
    viewer._load_content = lambda path: FileViewerController._load_content(viewer, path)
    viewer._update_meta = MagicMock()
    return viewer


def test_flush_does_not_switch_when_content_missing():
    viewer = _make_viewer_stub()
    viewer._target_plugin = _DEFAULT_WIDGET_NAME
    viewer._pending_meta = [{'size': '0'}, {}, {}, {}]
    viewer._pending_content = None
    viewer._flush()
    assert viewer._pending_meta is not None


def test_flush_does_not_switch_when_meta_missing():
    viewer = _make_viewer_stub()
    viewer._target_plugin = _DEFAULT_WIDGET_NAME
    viewer._pending_content = ('/a.png', MagicMock())
    viewer._pending_meta = None
    viewer._flush()
    assert viewer._pending_content is not None


def test_flush_shows_image_for_default():
    viewer = _make_viewer_stub()
    viewer._target_plugin = _DEFAULT_WIDGET_NAME
    img = MagicMock()
    viewer._pending_content = ('/a.png', img)
    viewer._pending_meta = [{'size': '0'}, {}, {}, {}]

    viewer._flush()

    assert viewer.content_viewer._current_plugin_name == _DEFAULT_WIDGET_NAME
    viewer.image_viewer.set_image.assert_called_once_with(img, '/a.png')
    viewer.image_viewer.clear.assert_not_called()
    viewer.meta_viewer.set_data.assert_called_once()
    assert viewer._pending_content is None
    assert viewer._pending_meta is None


def test_flush_shows_error_image_when_content_none_for_default():
    viewer = _make_viewer_stub()
    viewer._target_plugin = _DEFAULT_WIDGET_NAME
    viewer._pending_content = ('/a.zip', None)
    viewer._pending_meta = [{'size': '0'}, {}, {}, {}]

    with patch('wafer.app.viewer.preview.file_viewer.PixmapFactory') as mock_factory:
        mock_error_img = MagicMock()
        mock_factory.create_viewer_error_placeholder.return_value = mock_error_img
        viewer._flush = lambda: FileViewerController._flush(viewer)
        viewer._flush()

    viewer.image_viewer.set_image.assert_called_once_with(mock_error_img, '/a.zip')
    viewer.image_viewer.clear.assert_not_called()
    viewer.meta_viewer.set_data.assert_called_once()


def test_flush_renders_widget_plugin():
    viewer = _make_viewer_stub()
    viewer._target_plugin = 'stub_widget'
    viewer._pending_content = ('/a.mp4', None)
    viewer._pending_meta = [{'size': '0'}, {}, {}, {}]

    call_order = []
    with patch('wafer.app.viewer.preview.file_viewer.viewer_resolver') as mock_resolver:
        mock_resolver.render = lambda p: call_order.append('render')
        mock_resolver.deactivate = MagicMock()
        mock_resolver.activate = MagicMock()

        def tracking_switch(name):
            call_order.append('switch')
            viewer.content_viewer._current_plugin_name = name
        viewer.content_viewer.switch_to = tracking_switch
        viewer._switch_to = lambda name: FileViewerController._switch_to(viewer, name)
        viewer._flush = lambda: FileViewerController._flush(viewer)

        viewer._flush()

    assert call_order == ['switch', 'render']
    assert viewer.content_viewer._current_plugin_name == 'stub_widget'


def test_on_path_changed_dispatches_both_pipelines():
    viewer = _make_viewer_stub()
    viewer._dispatcher = MagicMock()
    viewer._meta_cancel = MagicMock()
    viewer._content_cancel = MagicMock()
    viewer.image_cache = MagicMock()
    viewer.image_cache.get.return_value = None
    viewer.model = MagicMock()
    viewer.model.dbpath = None

    with patch('wafer.app.viewer.preview.file_viewer.viewer_resolver') as mock_resolver:
        mock_resolver.resolve.return_value = None
        viewer._on_path_changed('/test.png')

    viewer._update_meta.assert_called_once_with('/test.png')
    assert viewer._target_plugin == _DEFAULT_WIDGET_NAME


def test_on_path_changed_widget_sets_target():
    viewer = _make_viewer_stub()
    viewer._dispatcher = MagicMock()
    viewer._meta_cancel = MagicMock()
    viewer._content_cancel = MagicMock()
    viewer.model = MagicMock()
    viewer.model.dbpath = None

    initial_plugin = viewer.content_viewer._current_plugin_name
    with patch('wafer.app.viewer.preview.file_viewer.viewer_resolver') as mock_resolver:
        mock_resolver.resolve.return_value = _StubWidgetPlugin
        viewer._on_path_changed('/test.mp4')

    assert viewer.content_viewer._current_plugin_name == initial_plugin
    assert viewer._target_plugin == 'stub_widget'


def test_switch_to_deactivates_previous_widget_plugin():
    viewer = _make_viewer_stub()
    viewer.content_viewer._current_plugin_name = 'stub_widget'

    with patch('wafer.app.viewer.preview.content_viewer.viewer_resolver') as mock_resolver:
        from wafer.app.viewer.preview.content_viewer import ContentViewerWidget
        viewer.content_viewer.switch_to = lambda name: ContentViewerWidget.switch_to(viewer.content_viewer, name)
        viewer._switch_to = lambda name: FileViewerController._switch_to(viewer, name)
        viewer._switch_to(_DEFAULT_WIDGET_NAME)

        mock_resolver.deactivate.assert_called_once_with('stub_widget')

    assert viewer.content_viewer._current_plugin_name == _DEFAULT_WIDGET_NAME


def test_switch_to_activates_new_widget_plugin():
    viewer = _make_viewer_stub()
    viewer.content_viewer._current_plugin_name = _DEFAULT_WIDGET_NAME

    with patch('wafer.app.viewer.preview.content_viewer.viewer_resolver') as mock_resolver:
        from wafer.app.viewer.preview.content_viewer import ContentViewerWidget
        viewer.content_viewer.switch_to = lambda name: ContentViewerWidget.switch_to(viewer.content_viewer, name)
        viewer._switch_to = lambda name: FileViewerController._switch_to(viewer, name)
        viewer._switch_to('stub_widget')

        mock_resolver.activate.assert_called_once_with('stub_widget')
    viewer.image_viewer.clear.assert_called_once()
    assert viewer.content_viewer._current_plugin_name == 'stub_widget'


def test_switch_to_deactivates_and_activates_between_plugins():
    viewer = _make_viewer_stub()
    viewer.content_viewer._widget_map['other_plugin'] = MagicMock()
    viewer.content_viewer._current_plugin_name = 'stub_widget'

    with patch('wafer.app.viewer.preview.content_viewer.viewer_resolver') as mock_resolver:
        from wafer.app.viewer.preview.content_viewer import ContentViewerWidget
        viewer.content_viewer.switch_to = lambda name: ContentViewerWidget.switch_to(viewer.content_viewer, name)
        viewer._switch_to = lambda name: FileViewerController._switch_to(viewer, name)
        viewer._switch_to('other_plugin')

        mock_resolver.deactivate.assert_called_once_with('stub_widget')
        mock_resolver.activate.assert_called_once_with('other_plugin')


def test_switch_to_default_does_not_activate():
    viewer = _make_viewer_stub()
    viewer.content_viewer._current_plugin_name = 'stub_widget'

    with patch('wafer.app.viewer.preview.content_viewer.viewer_resolver') as mock_resolver:
        from wafer.app.viewer.preview.content_viewer import ContentViewerWidget
        viewer.content_viewer.switch_to = lambda name: ContentViewerWidget.switch_to(viewer.content_viewer, name)
        viewer._switch_to = lambda name: FileViewerController._switch_to(viewer, name)
        viewer._switch_to(_DEFAULT_WIDGET_NAME)

        mock_resolver.activate.assert_not_called()

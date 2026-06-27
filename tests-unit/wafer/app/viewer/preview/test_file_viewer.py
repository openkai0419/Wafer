import py_compile
from unittest.mock import MagicMock, patch, PropertyMock
from PySide6 import QtGui
from wafer.app.viewer.preview.file_viewer import _format_meta, FileViewerController, ViewerBatch
from wafer.app.viewer.preview.content_viewer import ContentViewerWidget
from wafer.plugin.viewer.base import ViewerContext, WidgetViewerPlugin
from wafer.builtins.image_viewer.viewer import ImageViewer

_IMAGE_VIEWER_NAME = ImageViewer.NAME


def _save_image(path, width: int, height: int):
    image = QtGui.QImage(width, height, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor("white"))
    assert image.save(str(path))


def _context(path: str, *, source: str | None = None, render_path: str | None = None) -> ViewerContext:
    return ViewerContext(path=path, source=source or path, render_path=render_path or path)


def _image_viewer(controller):
    return controller.viewer_plugin(_IMAGE_VIEWER_NAME)


def _mock_engine(**overrides):
    engine = MagicMock()
    if "get_all_metadata" in overrides:
        file_rec, tags, meta = overrides.pop("get_all_metadata")
        overrides.setdefault("file_record", file_rec)
        overrides.setdefault("meta_info_with_lock", {k: (v, False) for k, v in meta.items()})
        overrides.setdefault("tags_with_lock", {k: (v, False) for k, v in tags.items()})
    defaults = {
        "source_record": {"source": "/a.png", "size": None, "modified": None, "created": None, "collected": None},
        "file_record": {"path": "/a.png", "source": "/a.png", "name": "a.png", "aspect_ratio": None, "source_extension": None},
        "meta_info_with_lock": {},
        "tags_with_lock": {},
        "file_hash": "h1",
        "get_collection_status": [],
    }
    defaults.update(overrides)
    if "size" in defaults["file_record"] or "modified" in defaults["file_record"] or "created" in defaults["file_record"] or "collected" in defaults["file_record"]:
        for k in ("size", "modified", "created", "collected"):
            if k in defaults["file_record"]:
                defaults["source_record"][k] = defaults["file_record"].pop(k)
    defaults["source_record"].setdefault("file_hash", defaults["file_hash"])
    engine.get_all_metadata_with_locks.return_value = (
        defaults["source_record"],
        defaults["file_record"],
        defaults["file_hash"],
        defaults["tags_with_lock"],
        defaults["meta_info_with_lock"],
    )
    engine.get_collection_status.return_value = defaults["get_collection_status"]
    return engine


def test_compile():
    py_compile.compile("wafer/app/viewer/preview/file_viewer.py")


def test_format_meta_source_same_as_path():
    engine = _mock_engine()
    result = _format_meta(engine, "/a.png", "")
    source_section = result["source"]
    file_section = result["file"]
    assert source_section["source"] == "/a.png"
    assert file_section["path"] == "/a.png"


def test_format_meta_source_differs_from_path():
    engine = _mock_engine(
        source_record={"source": "/other/a.png", "file_hash": "h1", "size": None, "modified": None, "created": None, "collected": None},
        file_record={"path": "/a.png", "source": "/other/a.png", "name": "a.png", "aspect_ratio": None, "source_extension": None},
    )
    result = _format_meta(engine, "/a.png", "")
    assert result["source"]["source"] == "/other/a.png"
    assert result["file"]["path"] == "/a.png"


def test_format_meta_includes_resolved_file_hash_in_source():
    engine = _mock_engine(file_hash="resolved_hash")
    result = _format_meta(engine, "/a.png", "")
    assert result["source"]["file_hash"] == "resolved_hash"


def test_format_meta_formats_size_and_timestamps():
    engine = _mock_engine(
        source_record={"source": "/a.png", "file_hash": "h1", "size": "2048", "modified": "1700000000", "created": "1700000000", "collected": "1700000000"},
    )
    result = _format_meta(engine, "/a.png", "")
    source_section = result["source"]
    assert isinstance(source_section["created"], str)
    assert isinstance(source_section["collected"], str)
    assert isinstance(source_section["modified"], str)
    assert isinstance(source_section["size"], str)
    assert source_section["size"] != "2048"


def test_format_meta_sorts_tags_and_meta():
    engine = _mock_engine(
        tags_with_lock={"z_tag": ("1", False), "a_tag": ("2", False)},
        meta_info_with_lock={"exif.width": ("100", False)},
    )
    result = _format_meta(engine, "/a.png", "")
    tags = result["tag"]
    file_section = result["file"]
    assert list(tags.keys()) == ["a_tag", "z_tag"]
    assert "name" in file_section
    assert "exif" in result["prefixed"]


def test_format_meta_aspect_ratio():
    engine = _mock_engine(
        file_record={"path": "/a.png", "source": "/a.png", "name": "a.png", "aspect_ratio": 1.5, "source_extension": None},
    )
    result = _format_meta(engine, "/a.png", "")
    assert isinstance(result["file"]["aspect_ratio"], str)


def test_format_meta_source_extension_only_when_set():
    engine_without = _mock_engine()
    assert "source_extension" not in _format_meta(engine_without, "/a.png", "")["file"]
    engine_with = _mock_engine(
        file_record={"path": "/a.png", "source": "/a.png", "name": "a.png", "aspect_ratio": None, "source_extension": "zip"},
    )
    assert _format_meta(engine_with, "/a.png", "")["file"]["source_extension"] == "zip"


def test_format_meta_splits_prefixed_meta():
    engine = _mock_engine(
        tags_with_lock={"rating": ("5", False)},
        meta_info_with_lock={"exif.width": ("100", False), "exif.height": ("200", False)},
    )
    result = _format_meta(engine, "/a.png", "")
    file_section = result["file"]
    root_meta = result["meta"]
    prefixed = result["prefixed"]
    assert "name" in file_section
    assert root_meta == {}
    assert result["tag"] == {"rating": "5"}
    assert "exif" in prefixed
    assert "width" in prefixed["exif"]
    assert "height" in prefixed["exif"]


def test_format_meta_embeds_collector_html():
    engine = _mock_engine(get_collection_status=[("exif", "ok"), ("animated", "fail")])
    result = _format_meta(engine, "/a.png", "")
    source_section = result["source"]
    assert "collected by" in source_section
    assert "\u25cf" in source_section["collected by"]
    assert "animated" in source_section["collected by"]
    assert "exif" in source_section["collected by"]


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
        if _image_viewer(w) is not None:
            _image_viewer(w).set_image_spread(pages=1)
        return w, model

    def test_save_state_includes_autoplay(self, qtbot):
        w, _ = self._make_controller(qtbot)
        w._autoplay_interval = 5000
        w._autoplay_loop = False
        state = w._save_state()
        assert state["autoplay_interval"] == 5000
        assert state["autoplay_loop"] is False
        assert "autoplay_active" not in state

    def test_restore_state_sets_autoplay_fields(self, qtbot):
        w, _ = self._make_controller(qtbot)
        w._restore_state(
            {
                "autoplay_interval": 7000,
                "autoplay_loop": True,
            }
        )
        assert w._autoplay_interval == 7000
        assert w._autoplay_loop is True
        assert w._autoplay_active is False

    def test_state_includes_file_list_provider(self, qtbot):
        from wafer.app.viewer.preview.file_list_provider import FileListProvider, ListMode
        from wafer.app.viewer.preview.file_model import FileViewModel
        from wafer.app.viewer.grid.items import GridItemModel
        from wafer.app.viewer.preview.meta_panel import MetaViewerWidget

        model = FileViewModel()
        grid_items = GridItemModel()
        provider = FileListProvider(model, grid_items)
        cv = ContentViewerWidget()
        mv = MetaViewerWidget()
        qtbot.addWidget(cv)
        qtbot.addWidget(mv)
        w = FileViewerController(model, cv, mv, provider)

        provider.set_mode(ListMode.DIR)
        provider.set_open_contained_files_as_list(True)
        state = w._save_state()
        provider.restore_ui_state({"list_mode": "sync", "open_contained_files_as_list": False})
        w._restore_state({**state, "list_mode": "fv.list_fix"})

        assert state["list_mode"] == "dir"
        assert state["open_contained_files_as_list"] is True
        assert provider.mode == ListMode.FIX
        assert provider.open_contained_files_as_list is True

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
        w.content_viewer._current_plugin_name = _IMAGE_VIEWER_NAME
        w._arm_autoplay()
        assert w._autoplay_timer.isActive()
        assert not w._autoplay_held
        w.stop_autoplay()

    def test_arm_autoplay_holds_for_plugin_returning_true(self, qtbot):
        w, _ = self._make_controller(qtbot)

        class HoldPlugin(WidgetViewerPlugin):
            NAME = "_test_hold"
            EXTENSIONS = (".test",)
            PRIORITY = 1

            def set_autoplay(self, advance):
                self._advance = advance
                return advance is not None

        from wafer.plugin.viewer.handler import viewer_resolver

        plugin = HoldPlugin()
        viewer_resolver.registry._instances["_test_hold"] = plugin

        w._autoplay_active = True
        w.content_viewer._current_plugin_name = "_test_hold"
        w._arm_autoplay()
        assert w._autoplay_held is True
        assert not w._autoplay_timer.isActive()

        del viewer_resolver.registry._instances["_test_hold"]
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


class TestViewerBatchNavigation:
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

    def test_navigate_next_prev_defaults_to_single_item(self, qtbot):
        w, model = self._make_controller(qtbot)
        model.set_items(["a", "b", "c"], None)
        model.set_current_index(0)

        assert w.navigate_next() == "b"
        assert model.current_index() == 1
        assert w.navigate_prev() == "a"
        assert model.current_index() == 0

    def test_navigate_default_step_one_ignores_display_count(self, qtbot):
        w, model = self._make_controller(qtbot)
        model.set_items(["a", "b", "c", "d", "e"], None)
        model.set_current_index(0)
        w._set_target_contexts((_context("a"), _context("b")))

        assert w.navigate_next() == "b"
        assert model.current_index() == 1

    def test_navigate_by_display_count_advances_by_target_contexts(self, qtbot):
        w, model = self._make_controller(qtbot)
        model.set_items(["a", "b", "c", "d", "e"], None)
        model.set_current_index(0)
        w._set_target_contexts((_context("a"), _context("b")))

        assert w.navigate_next(by_display_count=True) == "c"
        assert model.current_index() == 2

    def test_navigate_prev_by_display_count_steps_back_by_target_contexts(self, qtbot):
        w, model = self._make_controller(qtbot)
        model.set_items(["a", "b", "c", "d", "e", "f"], None)
        model.set_current_index(4)
        w._set_target_contexts((_context("e"), _context("f")))

        assert w.navigate_prev(by_display_count=True) == "c"
        assert model.current_index() == 2

    def test_navigate_step_multiplies_display_count(self, qtbot):
        w, model = self._make_controller(qtbot)
        model.set_items([str(i) for i in range(8)], None)
        model.set_current_index(0)
        w._set_target_contexts((_context("0"), _context("1")))

        assert w.navigate_next(step=2, by_display_count=True) == "4"
        assert model.current_index() == 4

    def test_navigate_step_without_display_count_is_plain_multiplier(self, qtbot):
        w, model = self._make_controller(qtbot)
        model.set_items(["a", "b", "c", "d", "e"], None)
        model.set_current_index(0)

        assert w.navigate_next(step=2) == "c"
        assert model.current_index() == 2

    def test_navigate_single_viewer_by_display_count_advances_one(self, qtbot):
        w, model = self._make_controller(qtbot)
        model.set_items(["a", "b", "c"], None)
        model.set_current_index(0)
        w._set_target_contexts((_context("a"),))

        assert w.navigate_next(by_display_count=True) == "b"
        assert model.current_index() == 1

    def test_navigate_loop_wraps_with_default_step(self, qtbot):
        w, model = self._make_controller(qtbot)
        model.set_items(["a", "b", "c", "d", "e"], None)
        model.set_current_index(0)

        assert w.navigate_prev(loop=True) == "e"
        assert model.current_index() == 4
        assert w.navigate_next(loop=True) == "a"
        assert model.current_index() == 0

    def test_autoplay_advance_uses_display_count(self, qtbot):
        w, model = self._make_controller(qtbot)
        model.set_items(["a", "b", "c", "d"], None)
        model.set_current_index(0)
        w._set_target_contexts((_context("a"), _context("b")))
        w._autoplay_active = True

        w._do_advance()

        assert model.current_index() == 2

    def test_autoplay_advance_single_viewer_advances_one(self, qtbot):
        w, model = self._make_controller(qtbot)
        model.set_items(["a", "b", "c"], None)
        model.set_current_index(0)
        w._set_target_contexts((_context("a"),))
        w._autoplay_active = True

        w._do_advance()

        assert model.current_index() == 1

    def test_image_display_count_uses_declared_max_without_orientation_probe(self, qtbot, tmp_path):
        first = tmp_path / "first.png"
        spread = tmp_path / "spread.png"
        last = tmp_path / "last.png"
        _save_image(first, 100, 200)
        _save_image(spread, 300, 150)
        _save_image(last, 100, 200)
        w, model = self._make_controller(qtbot)
        model.set_items([str(first), str(spread), str(last)], None)
        _image_viewer(w).set_image_spread(pages=3)

        assert _image_viewer(w).display_count(0, model.paths) == 3
        assert len(w._resolve_viewer_batch(0).contexts) == 3

    def test_image_display_count_can_group_multiple_images(self, qtbot, tmp_path):
        paths = [tmp_path / f"{i}.png" for i in range(4)]
        for path in paths:
            _save_image(path, 100, 200)
        w, model = self._make_controller(qtbot)
        model.set_items([str(path) for path in paths], None)
        _image_viewer(w).set_image_spread(pages=3)

        assert _image_viewer(w).display_count(0, model.paths) == 3
        assert len(w._resolve_viewer_batch(0).contexts) == 3

    def test_single_widget_viewer_does_not_expand_display_count(self, qtbot):
        class GreedySingleViewer(WidgetViewerPlugin):
            NAME = "_test_single_display_count_ignored"
            EXTENSIONS = (".singleview",)
            PRIORITY = 1

            def display_count(self, current_index, paths):
                return 3

        from wafer.plugin.viewer.handler import viewer_resolver

        viewer_resolver.registry.register(GreedySingleViewer)
        w, model = self._make_controller(qtbot)
        model.set_items(["a.singleview", "b.singleview", "c.singleview"], None)

        assert w._display_count(GreedySingleViewer.NAME, 0) == 1


def test_format_meta_no_collectors_omits_key():
    engine = _mock_engine(get_collection_status=[])
    result = _format_meta(engine, "/a.png", "")
    file_rec = result["source"]
    assert "collected by" not in file_rec


class TestPathChangedClear:
    def _make_controller(self, qtbot):
        from wafer.app.viewer.preview.file_model import FileViewModel
        from wafer.app.viewer.preview.meta_panel import MetaViewerWidget

        model = FileViewModel()
        cv = ContentViewerWidget()
        mv = MetaViewerWidget()
        qtbot.addWidget(cv)
        qtbot.addWidget(mv)
        w = FileViewerController(model, cv, mv)
        return w, model, cv, mv

    def test_path_none_clears_viewers(self, qtbot):
        w, model, cv, mv = self._make_controller(qtbot)
        from wafer.app.viewer.preview.content_viewer import _PLACEHOLDER_PAGE

        w._on_path_changed(None)
        assert cv._current_plugin_name == _PLACEHOLDER_PAGE
        assert not mv._placeholder.isHidden()
        assert w._loading_path is None
        assert w._pending_meta is None
        assert w._pending_content is None


class _StubWidgetPlugin(WidgetViewerPlugin):
    NAME = "stub_widget"
    EXTENSIONS = (".mp4",)
    PRIORITY = 100
    WIDGET_CLASS = MagicMock


def _make_viewer_stub():
    content_viewer = MagicMock(spec=ContentViewerWidget)
    image_widget = MagicMock()
    placeholder = MagicMock()
    content_viewer._placeholder = placeholder
    content_viewer._current_plugin_name = _IMAGE_VIEWER_NAME
    content_viewer._stack = MagicMock()
    content_viewer._widget_map = {
        _IMAGE_VIEWER_NAME: image_widget,
        "stub_widget": MagicMock(),
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
    viewer._target_contexts = ()
    viewer._target_paths = ()
    viewer._target_render_path = None
    viewer._target_render_paths = ()
    viewer.content_viewer = content_viewer
    viewer.meta_viewer = meta_viewer
    viewer.image_cache = MagicMock()
    viewer.image_cache.get.return_value = None

    viewer._flush = lambda: FileViewerController._flush(viewer)
    viewer._switch_to = lambda name: FileViewerController._switch_to(viewer, name)
    viewer._on_path_changed = lambda path: FileViewerController._on_path_changed(viewer, path)
    viewer._load_content = lambda path: FileViewerController._load_content(viewer, path)
    viewer._set_target_contexts = lambda contexts: FileViewerController._set_target_contexts(viewer, contexts)
    viewer.current_viewer_contexts = lambda: FileViewerController.current_viewer_contexts(viewer)
    viewer.current_paths = lambda: FileViewerController.current_paths(viewer)
    viewer._update_meta = MagicMock()
    return viewer


def test_flush_does_not_switch_when_content_missing():
    viewer = _make_viewer_stub()
    viewer._target_plugin = _IMAGE_VIEWER_NAME
    viewer._pending_meta = [{"size": "0"}, {}, {}, {}]
    viewer._pending_content = None
    viewer._flush()
    assert viewer._pending_meta is not None


def test_flush_does_not_switch_when_meta_missing():
    viewer = _make_viewer_stub()
    viewer._target_plugin = _IMAGE_VIEWER_NAME
    viewer._pending_content = (ViewerBatch(_IMAGE_VIEWER_NAME, "/a.png", (_context("/a.png"),)), MagicMock())
    viewer._pending_meta = None
    viewer._flush()
    assert viewer._pending_content is not None


def test_flush_shows_image_for_default():
    viewer = _make_viewer_stub()
    viewer._target_plugin = _IMAGE_VIEWER_NAME
    batch = ViewerBatch(_IMAGE_VIEWER_NAME, "/a.png", (_context("/a.png"),))
    viewer._pending_content = (batch, None)
    viewer._pending_meta = [{"size": "0"}, {}, {}, {}]

    with patch("wafer.app.viewer.preview.file_viewer.viewer_resolver") as mock_resolver:
        viewer._flush()

    assert viewer.content_viewer._current_plugin_name == _IMAGE_VIEWER_NAME
    mock_resolver.render.assert_called_once_with(batch.contexts, plugin_name=_IMAGE_VIEWER_NAME)
    viewer.meta_viewer.set_data.assert_called_once()
    assert viewer._pending_content is None
    assert viewer._pending_meta is None


def test_flush_shows_error_image_when_content_none_for_default():
    viewer = _make_viewer_stub()
    viewer._target_plugin = _IMAGE_VIEWER_NAME
    viewer._pending_content = (ViewerBatch(_IMAGE_VIEWER_NAME, "/a.zip", (_context("/a.zip"),)), None)
    viewer._pending_meta = [{"size": "0"}, {}, {}, {}]

    batch = viewer._pending_content[0]
    with patch("wafer.app.viewer.preview.file_viewer.viewer_resolver") as mock_resolver:
        viewer._flush()

    mock_resolver.render.assert_called_once_with(batch.contexts, plugin_name=_IMAGE_VIEWER_NAME)
    viewer.meta_viewer.set_data.assert_called_once()


def test_flush_renders_widget_plugin():
    viewer = _make_viewer_stub()
    viewer._target_plugin = "stub_widget"
    context = ViewerContext(path="/archive.zip::a.mp4", source="/archive.zip", render_path="/cache/a.mp4")
    viewer._pending_content = (ViewerBatch("stub_widget", "/archive.zip::a.mp4", (context,)), None)
    viewer._pending_meta = [{"size": "0"}, {}, {}, {}]

    call_order = []
    rendered = {}
    with patch("wafer.app.viewer.preview.file_viewer.viewer_resolver") as mock_resolver:
        def render(contexts, plugin_name=None):
            rendered["contexts"] = contexts
            rendered["plugin_name"] = plugin_name
            call_order.append("render")

        mock_resolver.render = render
        mock_resolver.deactivate = MagicMock()
        mock_resolver.activate = MagicMock()

        def tracking_switch(name):
            call_order.append("switch")
            viewer.content_viewer._current_plugin_name = name

        viewer.content_viewer.switch_to = tracking_switch
        viewer._switch_to = lambda name: FileViewerController._switch_to(viewer, name)
        viewer._flush = lambda: FileViewerController._flush(viewer)

        viewer._flush()

    assert call_order == ["switch", "render"]
    assert rendered["contexts"] == (context,)
    assert rendered["plugin_name"] == "stub_widget"
    assert viewer.content_viewer._current_plugin_name == "stub_widget"


def test_on_path_changed_dispatches_both_pipelines():
    viewer = _make_viewer_stub()
    viewer._dispatcher = MagicMock()
    viewer._meta_cancel = MagicMock()
    viewer._content_cancel = MagicMock()
    viewer.image_cache = MagicMock()
    viewer.image_cache.get.return_value = None
    viewer.model = MagicMock()
    viewer.model.dbpath = None
    viewer.model.current_index.return_value = 0
    viewer.model.path_at.return_value = "/test.mp4"
    viewer.model.paths = ["/test.mp4"]
    viewer.model.count.return_value = 1

    with patch("wafer.app.viewer.preview.file_viewer.viewer_resolver") as mock_resolver:
        mock_resolver.resolve.return_value = None
        viewer._on_path_changed("/test.png")

    viewer._update_meta.assert_called_once_with("/test.png")
    assert viewer._target_plugin is None


def test_on_path_changed_widget_sets_target():
    viewer = _make_viewer_stub()

    class _SyncDispatcher:
        def post(self, task, cancel=None, priority=None):
            task()
        def invoke(self, callback):
            callback()

    viewer._dispatcher = _SyncDispatcher()
    viewer._meta_cancel = MagicMock()
    cancel_token = MagicMock()
    cancel_token.is_cancelled.return_value = False
    viewer._content_cancel = MagicMock()
    viewer._content_cancel.renew.return_value = cancel_token
    viewer.model = MagicMock()
    viewer.model.dbpath = None
    viewer.model.current_index.return_value = 0
    viewer.model.path_at.return_value = "/test.mp4"
    viewer.model.paths = ["/test.mp4"]
    viewer.model.count.return_value = 1
    viewer._resolve_viewer_batch = lambda index, cancel=None: ViewerBatch("stub_widget", "/test.mp4", (_context("/test.mp4"),))
    viewer._on_content_ready = lambda cancel, batch: FileViewerController._on_content_ready(viewer, cancel, batch)

    initial_plugin = viewer.content_viewer._current_plugin_name
    with patch("wafer.app.viewer.preview.file_viewer.viewer_resolver") as mock_resolver:
        viewer._on_path_changed("/test.mp4")

    assert viewer.content_viewer._current_plugin_name == initial_plugin
    assert viewer._target_plugin == "stub_widget"


def test_switch_to_deactivates_previous_widget_plugin():
    viewer = _make_viewer_stub()
    viewer.content_viewer._current_plugin_name = "stub_widget"

    with patch("wafer.app.viewer.preview.content_viewer.viewer_resolver") as mock_resolver:
        from wafer.app.viewer.preview.content_viewer import ContentViewerWidget

        viewer.content_viewer.switch_to = lambda name: ContentViewerWidget.switch_to(viewer.content_viewer, name)
        viewer._switch_to = lambda name: FileViewerController._switch_to(viewer, name)
        viewer._switch_to(_IMAGE_VIEWER_NAME)

        mock_resolver.deactivate.assert_called_once_with("stub_widget")

    assert viewer.content_viewer._current_plugin_name == _IMAGE_VIEWER_NAME


def test_switch_to_activates_new_widget_plugin():
    viewer = _make_viewer_stub()
    viewer.content_viewer._current_plugin_name = _IMAGE_VIEWER_NAME

    with patch("wafer.app.viewer.preview.content_viewer.viewer_resolver") as mock_resolver:
        from wafer.app.viewer.preview.content_viewer import ContentViewerWidget

        viewer.content_viewer.switch_to = lambda name: ContentViewerWidget.switch_to(viewer.content_viewer, name)
        viewer._switch_to = lambda name: FileViewerController._switch_to(viewer, name)
        viewer._switch_to("stub_widget")

        mock_resolver.activate.assert_called_once_with("stub_widget")
    assert viewer.content_viewer._current_plugin_name == "stub_widget"


def test_switch_to_deactivates_and_activates_between_plugins():
    viewer = _make_viewer_stub()
    viewer.content_viewer._widget_map["other_plugin"] = MagicMock()
    viewer.content_viewer._current_plugin_name = "stub_widget"

    with patch("wafer.app.viewer.preview.content_viewer.viewer_resolver") as mock_resolver:
        from wafer.app.viewer.preview.content_viewer import ContentViewerWidget

        viewer.content_viewer.switch_to = lambda name: ContentViewerWidget.switch_to(viewer.content_viewer, name)
        viewer._switch_to = lambda name: FileViewerController._switch_to(viewer, name)
        viewer._switch_to("other_plugin")

        mock_resolver.deactivate.assert_called_once_with("stub_widget")
        mock_resolver.activate.assert_called_once_with("other_plugin")


def test_switch_to_image_plugin_activates_image():
    viewer = _make_viewer_stub()
    viewer.content_viewer._current_plugin_name = "stub_widget"

    with patch("wafer.app.viewer.preview.content_viewer.viewer_resolver") as mock_resolver:
        from wafer.app.viewer.preview.content_viewer import ContentViewerWidget

        viewer.content_viewer.switch_to = lambda name: ContentViewerWidget.switch_to(viewer.content_viewer, name)
        viewer._switch_to = lambda name: FileViewerController._switch_to(viewer, name)
        viewer._switch_to(_IMAGE_VIEWER_NAME)

        mock_resolver.deactivate.assert_called_once_with("stub_widget")
        mock_resolver.activate.assert_called_once_with(_IMAGE_VIEWER_NAME)


def test_switch_to_unknown_plugin_uses_placeholder():
    viewer = _make_viewer_stub()
    viewer.content_viewer._current_plugin_name = "stub_widget"

    with patch("wafer.app.viewer.preview.content_viewer.viewer_resolver") as mock_resolver:
        from wafer.app.viewer.preview.content_viewer import ContentViewerWidget

        viewer.content_viewer.switch_to = lambda name: ContentViewerWidget.switch_to(viewer.content_viewer, name)
        viewer._switch_to = lambda name: FileViewerController._switch_to(viewer, name)
        viewer._switch_to("missing_plugin")

        viewer.content_viewer._stack.setCurrentWidget.assert_called_once_with(viewer.content_viewer._placeholder)
        mock_resolver.activate.assert_not_called()


def test_image_viewer_settings_change_reloads_from_current_batch_anchor():
    viewer = _make_viewer_stub()
    viewer.model = MagicMock()
    viewer.model.path.return_value = "/archive.zip::second.png"
    viewer._set_target_contexts(
        (
            _context("/archive.zip::first.png", source="/archive.zip", render_path="/cache/first.png"),
            _context("/archive.zip::second.png", source="/archive.zip", render_path="/cache/second.png"),
        )
    )
    viewer._on_viewer_settings_changed = lambda: FileViewerController._on_viewer_settings_changed(viewer)

    viewer._on_viewer_settings_changed()

    viewer.model.set_path.assert_called_once_with("/archive.zip::first.png")


def test_image_viewer_settings_change_forces_reload_when_anchor_matches_current_path():
    viewer = _make_viewer_stub()
    viewer.model = MagicMock()
    viewer.model.path.return_value = "/archive.zip::first.png"
    viewer._set_target_contexts(
        (
            _context("/archive.zip::first.png", source="/archive.zip", render_path="/cache/first.png"),
            _context("/archive.zip::second.png", source="/archive.zip", render_path="/cache/second.png"),
        )
    )
    viewer._on_path_changed = MagicMock()
    viewer._on_viewer_settings_changed = lambda: FileViewerController._on_viewer_settings_changed(viewer)

    viewer._on_viewer_settings_changed()

    viewer.model.set_path.assert_not_called()
    viewer._on_path_changed.assert_called_once_with("/archive.zip::first.png")

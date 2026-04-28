import pytest
from unittest.mock import MagicMock, patch


mpv_mock = MagicMock()
mpv_mock.MpvGlGetProcAddressFn = MagicMock(return_value=MagicMock())


@pytest.fixture(autouse=True)
def _patch_mpv(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "mpv", mpv_mock)
    from extensions.video.widget import MpvGLOverlay

    monkeypatch.setattr(MpvGLOverlay, "_mpv", mpv_mock)
    monkeypatch.setattr(MpvGLOverlay, "_init_attempted", True)


def test_video_grid_plugin_attributes():
    from extensions.video.grid import VideoGridPlugin

    assert VideoGridPlugin.NAME == "video"
    assert ".mp4" in VideoGridPlugin.EXTENSIONS
    assert ".mkv" in VideoGridPlugin.EXTENSIONS
    assert ".webm" in VideoGridPlugin.EXTENSIONS
    assert VideoGridPlugin.WIDGET_CLASS is not None
    assert VideoGridPlugin.REQUIRE_THUMBNAIL is True


def test_video_grid_plugin_match():
    from extensions.video.grid import VideoGridPlugin

    assert VideoGridPlugin.match("test.mp4")
    assert VideoGridPlugin.match("test.MKV")
    assert not VideoGridPlugin.match("test.jpg")
    assert not VideoGridPlugin.match("test.png")


def test_video_grid_plugin_is_widget_plugin():
    from extensions.video.grid import VideoGridPlugin
    from wafer.plugin.grid.base import WidgetGridPlugin

    assert issubclass(VideoGridPlugin, WidgetGridPlugin)


def test_video_grid_plugin_render_calls_load():
    from extensions.video.grid import VideoGridPlugin
    from PySide6 import QtCore

    plugin = VideoGridPlugin()
    widget = MagicMock()
    plugin.render(widget, "test.mp4", QtCore.QSize())
    widget.load.assert_called_once_with("test.mp4", QtCore.QSize())


def test_video_grid_plugin_render_passes_size():
    from extensions.video.grid import VideoGridPlugin
    from PySide6 import QtCore

    plugin = VideoGridPlugin()
    widget = MagicMock()
    size = QtCore.QSize(320, 240)
    plugin.render(widget, "test.mp4", size)
    widget.load.assert_called_once_with("test.mp4", size)


def test_video_grid_plugin_release_calls_suspend():
    from extensions.video.grid import VideoGridPlugin

    plugin = VideoGridPlugin()
    widget = MagicMock()
    plugin.release(widget)
    widget.suspend.assert_called_once()


def test_post_install_calls_ensure_mpv_dll():
    from extensions.video.grid import VideoGridPlugin

    with patch("extensions.video._downloader.ensure_mpv_dll") as mock_dl:
        VideoGridPlugin.post_install("/fake/dir")
        mock_dl.assert_called_once()


def test_video_grid_plugin_select_calls_on_selected():
    from extensions.video.grid import VideoGridPlugin

    plugin = VideoGridPlugin()
    widget = MagicMock()
    plugin.select(widget)
    widget.on_selected.assert_called_once()


def test_video_grid_plugin_appear_calls_on_appeared():
    from extensions.video.grid import VideoGridPlugin

    plugin = VideoGridPlugin()
    widget = MagicMock()
    plugin.appear(widget)
    widget.on_appeared.assert_called_once()


def test_video_grid_plugin_disappear_calls_on_disappeared():
    from extensions.video.grid import VideoGridPlugin

    plugin = VideoGridPlugin()
    widget = MagicMock()
    plugin.disappear(widget)
    widget.on_disappeared.assert_called_once()


def test_video_grid_plugin_deselect_calls_on_deselected():
    from extensions.video.grid import VideoGridPlugin

    plugin = VideoGridPlugin()
    widget = MagicMock()
    plugin.deselect(widget)
    widget.on_deselected.assert_called_once()


def test_video_grid_plugin_on_thumb_loaded_calls_set_thumbnail():
    from extensions.video.grid import VideoGridPlugin

    plugin = VideoGridPlugin()
    widget = MagicMock()
    image = MagicMock()
    plugin.on_thumb_loaded(widget, image)
    widget.set_thumbnail.assert_called_once_with(image)


def test_configure_sets_default_surface_format():
    from extensions.video.grid import VideoGridPlugin

    with patch("PySide6.QtGui.QSurfaceFormat") as MockFmt:
        mock_instance = MagicMock()
        MockFmt.return_value = mock_instance
        VideoGridPlugin.configure()
        mock_instance.setSwapBehavior.assert_called_once()
        MockFmt.setDefaultFormat.assert_called_once_with(mock_instance)


def test_save_state_returns_empty_when_no_slot_manager():
    from extensions.video.grid import VideoGridPlugin
    from extensions.video.widget import MpvCellWidget

    old = MpvCellWidget._slot_manager
    old_pending = MpvCellWidget._pending_grid_state
    MpvCellWidget._slot_manager = None
    MpvCellWidget._pending_grid_state = None
    try:
        plugin = VideoGridPlugin()
        assert plugin.save_ui_state() == {}
    finally:
        MpvCellWidget._slot_manager = old
        MpvCellWidget._pending_grid_state = old_pending


def test_save_state_returns_pending_when_no_slot_manager():
    from extensions.video.grid import VideoGridPlugin
    from extensions.video.widget import MpvCellWidget

    old = MpvCellWidget._slot_manager
    old_pending = MpvCellWidget._pending_grid_state
    MpvCellWidget._slot_manager = None
    MpvCellWidget._pending_grid_state = {"volume": 75, "hover_autoplay": False}
    try:
        plugin = VideoGridPlugin()
        assert plugin.save_ui_state() == {"volume": 75, "hover_autoplay": False}
    finally:
        MpvCellWidget._slot_manager = old
        MpvCellWidget._pending_grid_state = old_pending


def test_save_state_returns_slot_manager_values():
    from extensions.video.grid import VideoGridPlugin
    from extensions.video.widget import MpvCellWidget

    sm = MagicMock()
    sm.volume = 75
    sm.hover_autoplay = False
    sm.appear_autoplay = True
    sm.select_autoplay = True
    sm._max_selected = 5
    sm.pause_in_background = False
    old = MpvCellWidget._slot_manager
    MpvCellWidget._slot_manager = sm
    try:
        plugin = VideoGridPlugin()
        state = plugin.save_ui_state()
        assert state == {
            "volume": 75,
            "hover_autoplay": False,
            "appear_autoplay": True,
            "select_autoplay": True,
            "max_selected": 5,
            "pause_in_background": False,
        }
    finally:
        MpvCellWidget._slot_manager = old


def test_restore_ui_state_applies_values():
    from extensions.video.grid import VideoGridPlugin
    from extensions.video.widget import MpvCellWidget

    sm = MagicMock()
    old = MpvCellWidget._slot_manager
    MpvCellWidget._slot_manager = sm
    try:
        plugin = VideoGridPlugin()
        with patch("wafer.core.commands.bridge.Command") as mock_cmd:
            plugin.restore_ui_state(
                {
                    "volume": 60,
                    "hover_autoplay": False,
                    "appear_autoplay": True,
                    "select_autoplay": False,
                    "max_selected": 4,
                    "pause_in_background": True,
                }
            )
        sm.set_volume.assert_called_once_with(60)
        sm.set_max_selected.assert_called_once_with(4)
        assert sm.hover_autoplay == False
        assert sm.appear_autoplay == True
        assert sm.select_autoplay == False
        assert sm.pause_in_background == True
    finally:
        MpvCellWidget._slot_manager = old


def test_restore_ui_state_noop_when_no_slot_manager():
    from extensions.video.grid import VideoGridPlugin
    from extensions.video.widget import MpvCellWidget

    old = MpvCellWidget._slot_manager
    old_pending = MpvCellWidget._pending_grid_state
    MpvCellWidget._slot_manager = None
    MpvCellWidget._pending_grid_state = None
    try:
        plugin = VideoGridPlugin()
        plugin.restore_ui_state({"volume": 80})
        assert MpvCellWidget._pending_grid_state == {"volume": 80}
    finally:
        MpvCellWidget._slot_manager = old
        MpvCellWidget._pending_grid_state = old_pending


def test_deferred_restore_applied_on_init_shared(qtbot):
    from extensions.video.grid import VideoGridPlugin
    from extensions.video.widget import MpvCellWidget, PlaybackSlotManager

    old_sm = MpvCellWidget._slot_manager
    old_init = MpvCellWidget._shared_initialized
    old_pending = MpvCellWidget._pending_grid_state
    MpvCellWidget._slot_manager = None
    MpvCellWidget._shared_initialized = False
    MpvCellWidget._pending_grid_state = None
    try:
        plugin = VideoGridPlugin()
        plugin.restore_ui_state(
            {
                "volume": 55,
                "hover_autoplay": False,
                "appear_autoplay": False,
                "select_autoplay": False,
                "max_selected": 7,
                "pause_in_background": True,
            }
        )
        assert MpvCellWidget._pending_grid_state is not None
        sm = MagicMock(spec=PlaybackSlotManager)
        MpvCellWidget._slot_manager = sm
        MpvCellWidget._shared_initialized = False
        with patch("extensions.video.widget.PlaybackSlotManager", return_value=sm):
            with patch("wafer.core.commands.bridge.UI"):
                with patch("wafer.core.commands.bridge.Command"):
                    from PySide6.QtWidgets import QWidget

                    parent = QWidget()
                    qtbot.addWidget(parent)
                    MpvCellWidget._init_shared(parent)
        sm.set_volume.assert_called_once_with(55)
        sm.set_max_selected.assert_called_once_with(7)
        assert sm.hover_autoplay is False
        assert sm.appear_autoplay is False
        assert sm.select_autoplay is False
        assert sm.pause_in_background is True
        assert MpvCellWidget._pending_grid_state is None
    finally:
        MpvCellWidget._slot_manager = old_sm
        MpvCellWidget._shared_initialized = old_init
        MpvCellWidget._pending_grid_state = old_pending

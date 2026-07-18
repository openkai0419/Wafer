from wafer.plugin import WidgetGridPlugin
from wafer.utils.profiling import profiler
from .widget import MpvCellWidget, DEFAULT_VOLUME

POST_INSTALL_VERSION = "1"


class VideoGridPlugin(WidgetGridPlugin):
    NAME = "video"
    EXTENSIONS = (
        ".mp4",
        ".mkv",
        ".webm",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".m4v",
        ".ts",
        ".mpg",
        ".mpeg",
    )
    PRIORITY = 100
    DEFAULT_ENABLED = True
    WIDGET_CLASS = MpvCellWidget
    REQUIRE_THUMBNAIL = True

    @classmethod
    def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None, on_log=None):
        from ._downloader import ensure_mpv_dll

        ensure_mpv_dll(version=POST_INSTALL_VERSION)

    @classmethod
    def configure(cls):
        from PySide6.QtGui import QSurfaceFormat

        fmt = QSurfaceFormat()
        fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
        QSurfaceFormat.setDefaultFormat(fmt)

    @profiler.profile
    def render(self, widget, path, size):
        widget.load(path, size)

    @profiler.profile
    def on_thumb_loaded(self, widget, image):
        widget.set_thumbnail(image)

    @profiler.profile
    def release(self, widget):
        widget.suspend()

    @profiler.profile
    def appear(self, widget):
        widget.on_appeared()

    @profiler.profile
    def disappear(self, widget):
        widget.on_disappeared()

    @profiler.profile
    def select(self, widget):
        widget.on_selected()

    @profiler.profile
    def deselect(self, widget):
        widget.on_deselected()

    def save_ui_state(self):
        sm = MpvCellWidget._slot_manager
        if sm is None:
            return MpvCellWidget._pending_grid_state or {}
        return {
            "volume": sm.volume,
            "hover_autoplay": sm.hover_autoplay,
            "appear_autoplay": sm.appear_autoplay,
            "select_autoplay": sm.select_autoplay,
            "max_selected": sm._max_selected,
            "pause_in_background": sm.pause_in_background,
        }

    def restore_ui_state(self, state):
        sm = MpvCellWidget._slot_manager
        if sm is None:
            MpvCellWidget._pending_grid_state = state
            return
        self._apply_state(sm, state)

    @staticmethod
    def _apply_state(sm, state):
        sm.set_volume(state.get("volume", DEFAULT_VOLUME))
        sm.set_max_selected(state.get("max_selected", 3))
        sm.hover_autoplay = state.get("hover_autoplay", True)
        sm.appear_autoplay = state.get("appear_autoplay", True)
        sm.select_autoplay = state.get("select_autoplay", True)
        sm.pause_in_background = state.get("pause_in_background", False)

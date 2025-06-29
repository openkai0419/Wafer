from PySide6 import QtCore
from .loader import ImageLoaderRunnable
from ..thread import main_thread
from ...profiling import init_env

logger, profiler = init_env()


def _size_mismatch(a: QtCore.QSize, b: QtCore.QSize, tolerance: int = 1):
    return abs(a.width() - b.width()) > tolerance or abs(a.height() - b.height()) > tolerance

class SizeMismatchChecker(QtCore.QTimer):
    def __init__(self, target_widget, debug=False):
        super().__init__()
        self.target_widget = target_widget
        self.debug = debug
        self.setInterval(400)
        self.timeout.connect(self.check)
        self._active = False
        self._idle_timer = QtCore.QTimer()
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(1200)
        self._idle_timer.timeout.connect(self._on_idle)

    def trigger(self):
        self._active = True
        self._idle_timer.start()
        if not self.isActive():
            self.start()

    def _on_idle(self):
        self._active = False

    @profiler.profile
    def check(self):
        if not self._active:
            return
        max_index = len(self.target_widget.image_paths)
        for i, label in self.target_widget.widgets.items():
            if i >= max_index:
                continue
            pixmap = label.pixmap()
            if pixmap is None:
                continue
            if _size_mismatch(pixmap.size(), label.size()):
                if i not in self.target_widget.active_threads:
                    runnable = ImageLoaderRunnable(i, self.target_widget.image_paths[i], label.size(), self.target_widget)
                    self.target_widget.active_threads[i] = runnable
                    main_thread.start(runnable, 5)
        logger.debug("SizeMismatchChecker: check")

class ScrollManager(QtCore.QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.widget = widget
        self._scroll_last_time = 0
        self._scroll_throttle_ms = 100
        self._scrolling = False
        self.scroll_timer = QtCore.QTimer(self)
        self.scroll_timer.setInterval(100)
        self.scroll_timer.timeout.connect(self._on_scroll_timer)
        self.scroll_timer.start()
        self._scroll_idle_timer = QtCore.QTimer(self)
        self._scroll_idle_timer.setSingleShot(True)
        self._scroll_idle_timer.setInterval(100)
        self._scroll_idle_timer.timeout.connect(self._on_scroll_idle)
        widget.parent_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_bar_changed)

    @profiler.profile
    def _on_scroll_bar_changed(self):
        self._scrolling = True
        self._scroll_idle_timer.start()

    @profiler.profile
    def _on_scroll_timer(self):
        if self._scrolling:
            self._throttled_update()

    @profiler.profile
    def _throttled_update(self):
        now = QtCore.QTime.currentTime().msecsSinceStartOfDay()
        if now - self._scroll_last_time >= self._scroll_throttle_ms:
            self._scroll_last_time = now
            self.widget._update_visible_items()

    @profiler.profile
    def _on_scroll_idle(self):
        self._scrolling = False
        self.widget._update_visible_items()

    @staticmethod
    def calculate_visible_indices(rects, view_rect):
        def find_start():
            low, high = 0, len(rects) - 1
            while low <= high:
                mid = (low + high) // 2
                if rects[mid].bottom() < view_rect.top():
                    low = mid + 1
                else:
                    high = mid - 1
            return low

        def find_end():
            low, high = 0, len(rects) - 1
            while low <= high:
                mid = (low + high) // 2
                if rects[mid].top() > view_rect.bottom():
                    high = mid - 1
                else:
                    low = mid + 1
            return high

        start = find_start()
        end = find_end()
        return range(start, end + 1)

    @staticmethod
    def expand_prefetch_range(rects, visible_range):
        if not visible_range:
            return range(0, 0)
        prefetch = len(visible_range) + 3
        start = max(0, visible_range.start - prefetch)
        end = min(len(rects), visible_range.stop + prefetch)
        return range(start, end)


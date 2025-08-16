from PySide6 import QtCore
from ...common.profiling import logger
from .loader import ImageLoaderRunnable
from ...qt.thread import main_thread

def _size_mismatch(a, b, tolerance=1):
    return abs(a.width() - b.width()) > tolerance or abs(a.height() - b.height()) > tolerance

class SizeMismatchChecker(QtCore.QTimer):

    def __init__(self, target_widget, debug=False):
        super().__init__()
        self.target_widget = target_widget
        self.debug = debug
        self.setInterval(500)
        self.timeout.connect(self.check)
        self._active = False
        self._idle_timer = QtCore.QTimer()
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(3000)
        self._idle_timer.timeout.connect(self._on_idle)

    def trigger(self):
        self._active = True
        self._idle_timer.start()
        if not self.isActive():
            self.start()

    def _on_idle(self):
        self._active = False

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
        logger.debug('SizeMismatchChecker: check')

from PySide6.QtCore import QEvent, QObject, QTimer, Signal


class WidgetVisibilityWatcher(QObject):
    changed = Signal(bool)

    _TRIGGERS = (QEvent.Show, QEvent.Hide, QEvent.Resize, QEvent.Move)

    def __init__(self, widget):
        super().__init__(widget)
        self._widget = widget
        self._visible = not widget.visibleRegion().isEmpty()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._evaluate)
        widget.installEventFilter(self)

    def is_visible(self):
        return self._visible

    def eventFilter(self, obj, event):
        if obj is self._widget and event.type() in self._TRIGGERS:
            self._timer.start(0)
        return False

    def _evaluate(self):
        visible = not self._widget.visibleRegion().isEmpty()
        if visible != self._visible:
            self._visible = visible
            self.changed.emit(visible)

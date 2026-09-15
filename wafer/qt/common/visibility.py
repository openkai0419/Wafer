from PySide6.QtCore import QEvent, QObject, Signal

from .rate_limit import qt_debounce


class WidgetVisibilityWatcher(QObject):
    changed = Signal(bool)

    _TRIGGERS = (QEvent.Show, QEvent.Hide, QEvent.Resize, QEvent.Move)

    def __init__(self, widget):
        super().__init__(widget)
        self._widget = widget
        self._visible = not widget.visibleRegion().isEmpty()
        widget.installEventFilter(self)

    def is_visible(self):
        return self._visible

    def eventFilter(self, obj, event):
        if obj is self._widget and event.type() in self._TRIGGERS:
            self._evaluate()
        return False

    @qt_debounce(0)
    def _evaluate(self):
        visible = not self._widget.visibleRegion().isEmpty()
        if visible != self._visible:
            self._visible = visible
            self.changed.emit(visible)

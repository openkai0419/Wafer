from PySide6.QtCore import QObject, QTimer, Slot
from functools import wraps

class QtDebounceManager(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._timers = {}  # key: function identity -> QTimer

    def debounce(self, key, delay_ms, callback, *args, **kwargs):
        """個別キーでデバウンス実行"""
        if key in self._timers:
            self._timers[key].stop()
            self._timers[key].deleteLater()

        timer = QTimer(self)
        timer.setSingleShot(True)

        @Slot()
        def on_timeout():
            callback(*args, **kwargs)
            timer.deleteLater()
            self._timers.pop(key, None)

        timer.timeout.connect(on_timeout)
        timer.start(delay_ms)
        self._timers[key] = timer

# グローバルに1つだけインスタンス生成（使い回し可）
_qt_debounce_manager = QtDebounceManager()

def qt_debounce(delay_ms: int):
    """任意の関数をデバウンス実行するデコレータ"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = id(func)  # 関数ごとに独立して管理
            _qt_debounce_manager.debounce(key, delay_ms, func, *args, **kwargs)
        return wrapper
    return decorator

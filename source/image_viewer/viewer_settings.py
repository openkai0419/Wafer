import json
from pathlib import Path
from typing import Any, Optional, Type

from PySide6 import QtCore

from ..common.funcs import data_path


class AsyncSaver(QtCore.QObject):
    finished = QtCore.Signal()

    def __init__(self, ini_path: Path):
        super().__init__()
        self.ini_path = ini_path
        self.queue: dict[str, Any] = {}
        self.mutex = QtCore.QMutex()

    @QtCore.Slot(dict)
    def set_buffer(self, buffer: dict[str, Any]):
        self.mutex.lock()
        self.queue.update(buffer)
        self.mutex.unlock()

    @QtCore.Slot()
    def flush(self):
        self.mutex.lock()
        updates = self.queue.copy()
        self.queue.clear()
        self.mutex.unlock()

        settings = QtCore.QSettings(str(self.ini_path), QtCore.QSettings.IniFormat)
        for key, value in updates.items():
            settings.setValue(key, self._prepare_for_save(value))
        settings.sync()
        self.finished.emit()

    def _prepare_for_save(self, value: Any) -> Any:
        try:
            if isinstance(value, (dict, list, tuple, set)):
                return json.dumps(value)
            return value
        except Exception:
            return str(value)


class SettingManager(QtCore.QObject):
    send_buffer = QtCore.Signal(dict)
    request_flush = QtCore.Signal()

    def __init__(self, ini_filename="viewer_settings.ini"):
        super().__init__()
        self.ini_path = data_path(ini_filename)
        self.settings = QtCore.QSettings(str(self.ini_path), QtCore.QSettings.IniFormat)
        self._buffer: dict[str, Any] = {}
        self._seen_keys: set[str] = set()

        self._thread = QtCore.QThread()
        self._saver = AsyncSaver(self.ini_path)
        self.send_buffer.connect(self._saver.set_buffer)
        self.request_flush.connect(self._saver.flush)
        self._saver.moveToThread(self._thread)
        self._thread.start()

    def get(self, key: str, default: Any = None, value_type: Optional[Type] = None) -> Any:
        if key in self._buffer:
            return self._decode_value(self._buffer[key], value_type, default)
        value = self.settings.value(key, defaultValue=default)
        return self._decode_value(value, value_type, default)

    def is_first_time(self, key: str) -> bool:
        if key in self._seen_keys:
            return False
        self._seen_keys.add(key)
        return True

    def _decode_value(self, value: Any, value_type: Optional[Type], default: Any) -> Any:
        if value is None:
            return default
        if value_type is not None:
            try:
                return value_type(value)
            except Exception:
                return default
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return value
        return value

    def save_important(self, key: str, value: Any):
        if isinstance(value, (dict, list, tuple, set)):
            value = json.dumps(value)
        self.settings.setValue(key, value)
        self.settings.sync()

    def set(self, key: str, value: Any):
        self._buffer[key] = value

    def commit(self):
        self.send_buffer.emit(self._buffer.copy())
        self.request_flush.emit()
        self._buffer.clear()

    def close(self):
        if self._buffer:
            self.commit()
        self.request_flush.emit()
        self._thread.quit()
        self._thread.wait()

    def discard(self):
        self._buffer.clear()

    def clear(self):
        self.settings.clear()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

main_setting = SettingManager()

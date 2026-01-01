import atexit
import json
from pathlib import Path
import weakref
from PySide6 import QtCore
from ..common.funcs import data_path
from ..common.helpers import try_call0, try_cast, try_json_loads

class AsyncSaver(QtCore.QObject):
    finished = QtCore.Signal()

    def __init__(self, ini_path):
        super().__init__()
        self.ini_path = ini_path
        self.queue = {}
        self.mutex = QtCore.QMutex()

    @QtCore.Slot(dict)
    def set_buffer(self, buffer):
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

    def _prepare_for_save(self, value):
        try:
            if isinstance(value, (dict, list, tuple, set)):
                return json.dumps(value)
            return value
        except (TypeError, ValueError):
            return str(value)

class SettingManager(QtCore.QObject):
    send_buffer = QtCore.Signal(dict)
    request_flush = QtCore.Signal()

    def __init__(self, ini_filename='viewer_settings.ini'):
        super().__init__()
        self.ini_path = data_path(ini_filename)
        self.settings = QtCore.QSettings(str(self.ini_path), QtCore.QSettings.IniFormat)
        self._buffer = {}
        self._seen_keys = set()
        self._thread = QtCore.QThread()
        self._saver = AsyncSaver(self.ini_path)
        self.send_buffer.connect(self._saver.set_buffer)
        self.request_flush.connect(self._saver.flush)
        self._saver.moveToThread(self._thread)
        self._thread.start()

    def get(self, key, default=None, value_type=None):
        if key in self._buffer:
            return self._decode_value(self._buffer[key], value_type, default)
        value = self.settings.value(key, defaultValue=default)
        return self._decode_value(value, value_type, default)

    def is_first_time(self, key):
        if key in self._seen_keys:
            return False
        self._seen_keys.add(key)
        return True

    def _decode_value(self, value, value_type, default):
        if value is None:
            return default
        if value_type is not None:
            return try_cast(value_type, value, default)
        if isinstance(value, str):
            v = try_json_loads(value, None)
            return value if v is None else v
        return value

    def save_important(self, key, value):
        if isinstance(value, (dict, list, tuple, set)):
            value = json.dumps(value)
        self.settings.setValue(key, value)
        self.settings.sync()

    def set(self, key, value):
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
        try_call0(self, 'close', None, 'SettingManager.__del__ close failed')

def _shutdown_setting_manager(ref):
    mgr = ref()
    if mgr is None:
        return
    try_call0(mgr, 'close', None, 'SettingManager shutdown close failed')

main_setting = SettingManager()
atexit.register(_shutdown_setting_manager, weakref.ref(main_setting))

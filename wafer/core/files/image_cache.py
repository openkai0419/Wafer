from collections import OrderedDict
import threading

from ...utils.decorators import singleton
from ...utils.profiling import profiler


def fullsize_key(path: str):
    return ("orig", path)


@singleton
class MemoryLimitedImageCache:
    def __init__(self, max_mbytes=100):
        self.max_bytes = max_mbytes * 1024 * 1024
        self.current_bytes = 0
        self.cache = OrderedDict()
        self._lock = threading.Lock()

    @profiler.profile
    def _estimate_image_size(self, image):
        size = image.size()
        return size.width() * size.height() * 4

    @profiler.profile
    def __setitem__(self, key, image):
        with self._lock:
            if key in self.cache:
                self.current_bytes -= self._estimate_image_size(self.cache[key])
                del self.cache[key]
            image_size = self._estimate_image_size(image)
            self.cache[key] = image
            self.cache.move_to_end(key)
            self.current_bytes += image_size
            while self.current_bytes > self.max_bytes and self.cache:
                _old_key, old_image = self.cache.popitem(last=False)
                self.current_bytes -= self._estimate_image_size(old_image)

    @profiler.profile
    def __getitem__(self, key):
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            raise KeyError(key)

    @profiler.profile
    def __contains__(self, key):
        with self._lock:
            return key in self.cache

    @profiler.profile
    def __delitem__(self, key):
        with self._lock:
            if key in self.cache:
                self.current_bytes -= self._estimate_image_size(self.cache[key])
                del self.cache[key]

    def clear(self):
        with self._lock:
            self.cache.clear()
            self.current_bytes = 0

    def get(self, key, default=None):
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return default

    def get_if_sufficient(self, key, size, default=None):
        with self._lock:
            image = self.cache.get(key)
            if image is not None and image.width() >= size.width() and image.height() >= size.height():
                self.cache.move_to_end(key)
                return image
            return default

    def peek(self, key, default=None):
        with self._lock:
            return self.cache.get(key, default)

    def peek_if_sufficient(self, key, size, default=None):
        with self._lock:
            image = self.cache.get(key)
            if image is not None and image.width() >= size.width() and image.height() >= size.height():
                return image
            return default

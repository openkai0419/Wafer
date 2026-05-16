from __future__ import annotations
from ...core.app_settings import app_settings
from ...core.qt.dispatcher import CancelSlot, Dispatcher
from ...core.qt.image_cache import MemoryLimitedImageCache, fullsize_key
from ...core.qt.pixmap import PixmapFactory
from ...core.qt.thread import utility_pool
from ...plugin.imageloader.handler import image_loader_resolver
from ...plugin.viewer.base import MultiWidgetViewerPlugin, ViewerContext
from ...utils.logs import AppLogger
from .widget import ImageDisplayWidget

_IMAGE_SPREAD_DIRECTIONS = {"left-to-right", "right-to-left", "top-to-bottom", "bottom-to-top"}


class CallbackSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self):
        for callback in tuple(self._callbacks):
            callback()


class ImageViewer(MultiWidgetViewerPlugin):
    NAME = "image"
    EXTENSIONS = ()
    PRIORITY = -100
    DEFAULT_ENABLED = True
    WIDGET_CLASS = ImageDisplayWidget

    def __init__(self):
        MultiWidgetViewerPlugin.__init__(self)
        self.settingsChanged = CallbackSignal()
        self._dispatcher = Dispatcher(utility_pool)
        self._render_cancel = CancelSlot()
        self._image_cache = MemoryLimitedImageCache(app_settings.get("window/cache_size", 500))
        self._display_count = 1
        self._direction = "right-to-left"

    @property
    def image_spread_pages(self) -> int:
        return self._display_count

    @property
    def image_spread_enabled(self) -> bool:
        return self._display_count > 1

    @property
    def image_spread_direction(self) -> str:
        return self._direction

    def navigation_cache_key(self) -> tuple[int, str]:
        return (self._display_count, self._direction)

    def set_image_spread(self, pages: int = 1, direction: str = "right-to-left"):
        pages = max(1, min(int(pages), 16))
        direction = direction if direction in _IMAGE_SPREAD_DIRECTIONS else "right-to-left"
        changed = pages != self._display_count or direction != self._direction
        self._display_count = pages
        self._direction = direction
        if changed:
            self.settingsChanged.emit()

    def display_count(self, current_index: int, paths) -> int:
        return self._display_count

    def render_contexts(self, contexts: list[ViewerContext] | tuple[ViewerContext, ...]):
        contexts = tuple(contexts or ())
        if not contexts:
            return
        cancel = self._render_cancel.renew()
        render_paths = tuple(context.render_path for context in contexts)

        def task():
            images = self.load_images(render_paths, cancel)
            if cancel.is_cancelled() or images is None:
                return
            self._dispatcher.invoke(lambda: self._show_rendered(cancel, images))

        self._dispatcher.post(task, cancel=cancel)

    def _show_rendered(self, cancel, images):
        if cancel.is_cancelled():
            return
        if images:
            self.show_images(images)
        else:
            self.show_error()

    def load_images(self, paths, cancel=None):
        images = []
        for path in paths:
            if cancel is not None and cancel.is_cancelled():
                return None
            key = fullsize_key(path)
            image = self._image_cache.get(key)
            if image is None or image.isNull():
                try:
                    image = image_loader_resolver.load_qimage(path)
                except Exception as exc:
                    AppLogger.warning(f"[ImageViewer] Failed to load image: {path}", exc=exc)
                    image = None
                if image is not None and not image.isNull():
                    self._image_cache[key] = image
                else:
                    image = None
            images.append((path, image))
        return images

    def show_images(self, images):
        rendered = [image or PixmapFactory.create_viewer_error_placeholder() for _, image in images]
        self.widget.set_images(rendered, direction=self._direction)

    def show_error(self):
        self.widget.set_images([PixmapFactory.create_viewer_error_placeholder()], direction=self._direction)

    def clear(self):
        self._render_cancel.renew()
        self.widget.clear()

    def deactivate(self):
        self.clear()

    def save_ui_state(self) -> dict:
        return {
            "fit_mode": "contain" if self.widget.is_contain_mode() else "cover",
            "image_spread_pages": self._display_count,
            "image_spread_direction": self._direction,
        }

    def restore_ui_state(self, state: dict) -> None:
        if "fit_mode" in state:
            self.widget.set_contain_mode(state["fit_mode"] == "contain")
        if "image_spread_pages" in state or "image_spread_direction" in state:
            self.set_image_spread(
                pages=state.get("image_spread_pages", self._display_count),
                direction=state.get("image_spread_direction", self._direction),
            )

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from ...core.files.render_target import RenderPlan, ResolveContext
from ..registry import BasePlugin


@dataclass(frozen=True)
class ViewerContext:
    path: str
    source: str
    render_path: str


def viewer_context_values(contexts: Sequence[ViewerContext] | None) -> dict[str, object]:
    contexts = tuple(contexts or ())
    if not contexts:
        return {"path": None, "paths": [], "source": None, "sources": [], "render_path": None, "render_paths": []}
    paths = [context.path for context in contexts]
    sources = list(dict.fromkeys(context.source for context in contexts if context.source))
    render_paths = [context.render_path for context in contexts]
    return {
        "path": paths[0],
        "paths": paths,
        "source": sources[0] if sources else None,
        "sources": sources,
        "render_path": render_paths[0] if render_paths else None,
        "render_paths": render_paths,
    }


class WidgetViewerPlugin(BasePlugin):
    WIDGET_CLASS = None

    def __init__(self):
        self._widget = None

    @property
    def widget(self):
        if self._widget is None and self.WIDGET_CLASS is not None:
            self._widget = self.WIDGET_CLASS()
        return self._widget

    @widget.setter
    def widget(self, value):
        self._widget = value

    def render(self, context: ViewerContext):
        pass

    def resolve(self, path: str, context: ResolveContext) -> RenderPlan | None:
        if not type(self).can_handle(path):
            return None
        return RenderPlan(source=context.source, path=context.path, resolved_path=path, handler=self)

    def clear(self):
        pass

    def activate(self):
        pass

    def deactivate(self):
        pass

    def set_autoplay(self, advance: Callable[[], None] | None) -> bool:
        return False

    def save_ui_state(self) -> dict[str, Any]:
        return {}

    def restore_ui_state(self, state: dict[str, Any]) -> None:
        pass


class MultiWidgetViewerPlugin(WidgetViewerPlugin):
    def display_count(self, current_index: int, paths: Sequence[str]) -> int:
        return 1

    def render_contexts(self, contexts: Sequence[ViewerContext]):
        pass

from __future__ import annotations

from typing import Dict, List, Optional
from weakref import WeakSet

from PySide6 import QtWidgets

from source.common.errors import show_warning


class WidgetRegistry:
    _instance: Optional["WidgetRegistry"] = None

    def __init__(self):
        self._widgets_by_name: Dict[str, WeakSet[QtWidgets.QWidget]] = {}

    def is_valid(self, widget: QtWidgets.QWidget) -> bool:
        if widget is None:
            return False
        try:
            import shiboken6

            return bool(shiboken6.isValid(widget))
        except (ImportError, ModuleNotFoundError):
            pass
        except Exception as e:
            show_warning(None, "WidgetRegistry.is_valid shiboken6 failed", exc=e)
        try:
            widget.objectName()
            return True
        except (RuntimeError, ReferenceError):
            return False
        except Exception as e:
            show_warning(None, "WidgetRegistry.is_valid failed", exc=e)
            return False

    def _get_valid(self, name: str) -> List[QtWidgets.QWidget]:
        ws = self._widgets_by_name.get(name)
        if not ws:
            return []
        out: List[QtWidgets.QWidget] = []
        dead: List[QtWidgets.QWidget] = []
        for w in list(ws):
            if self.is_valid(w):
                out.append(w)
            else:
                dead.append(w)
        if dead:
            for w in dead:
                try:
                    ws.discard(w)
                except Exception:
                    pass
        return out

    @classmethod
    def instance(cls) -> "WidgetRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def infer_name(self, widget: QtWidgets.QWidget) -> Optional[str]:
        if widget is None:
            return None
        if hasattr(widget, "binding_scope") and callable(getattr(widget, "binding_scope")):
            try:
                n = widget.binding_scope()
                if n:
                    return str(n)
            except Exception as e:
                show_warning(None, "WidgetRegistry.infer_name binding_scope failed", exc=e)
        n = getattr(widget, "name", None)
        return str(n) if n else None

    def register(self, name: str, widget: QtWidgets.QWidget) -> None:
        if not name:
            raise ValueError("name is required")
        if widget is None:
            raise ValueError("widget is required")
        try:
            k = str(name)
            ws = self._widgets_by_name.get(k)
            if ws is None:
                ws = WeakSet()
                self._widgets_by_name[k] = ws
            ws.add(widget)
        except Exception as e:
            show_warning(None, "WidgetRegistry.register failed", exc=e)

    def register_inferred(self, widget: QtWidgets.QWidget) -> None:
        n = self.infer_name(widget)
        if n:
            self.register(n, widget)

    def has(self, name: str) -> bool:
        if not name:
            return False
        try:
            return bool(self._get_valid(str(name)))
        except Exception as e:
            show_warning(None, "WidgetRegistry.has failed", exc=e)
            return False

    def get_all(self, name: str) -> List[QtWidgets.QWidget]:
        if not name:
            return []
        try:
            return self._get_valid(str(name))
        except Exception as e:
            show_warning(None, "WidgetRegistry.get_all failed", exc=e)
            return []

    def get_one(self, name: str) -> Optional[QtWidgets.QWidget]:
        xs = self.get_all(name)
        return xs[0] if xs else None

    def names(self) -> List[str]:
        try:
            return sorted(list(self._widgets_by_name.keys()))
        except Exception as e:
            show_warning(None, "WidgetRegistry.names failed", exc=e)
            return []

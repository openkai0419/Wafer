from __future__ import annotations

from typing import Any, Dict, List, Optional
import weakref

from PySide6 import QtCore, QtWidgets

from source.common.errors import show_warning


class InstanceRegistry:
    _instance: Optional["InstanceRegistry"] = None

    def __init__(self):
        self._by_name: Dict[str, List[Any]] = {}

    @classmethod
    def instance(cls) -> "InstanceRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def infer_name(self, instance: Any) -> Optional[str]:
        if instance is None:
            return None
        if hasattr(instance, "binding_scope") and callable(getattr(instance, "binding_scope")):
            try:
                n = instance.binding_scope()
                if n:
                    return str(n)
            except Exception as e:
                show_warning(None, "InstanceRegistry.infer_name binding_scope failed", exc=e)
        n = getattr(instance, "name", None)
        return str(n) if n else None

    def is_valid(self, instance: Any) -> bool:
        if instance is None:
            return False
        if isinstance(instance, QtCore.QObject):
            try:
                import shiboken6

                return bool(shiboken6.isValid(instance))
            except (ImportError, ModuleNotFoundError):
                pass
            except Exception as e:
                show_warning(None, "InstanceRegistry.is_valid shiboken6 failed", exc=e)
            try:
                if isinstance(instance, QtWidgets.QWidget):
                    instance.objectName()
                else:
                    instance.objectName()
                return True
            except (RuntimeError, ReferenceError):
                return False
            except Exception as e:
                show_warning(None, "InstanceRegistry.is_valid failed", exc=e)
                return False
        return True

    def _wrap(self, obj: Any) -> Any:
        try:
            return weakref.ref(obj)
        except TypeError:
            return obj

    def _unwrap(self, entry: Any) -> Any:
        if isinstance(entry, weakref.ReferenceType):
            return entry()
        return entry

    def register(self, name: str, instance: Any) -> None:
        if not name:
            raise ValueError("name is required")
        if instance is None:
            raise ValueError("instance is required")
        k = str(name)
        try:
            xs = self._by_name.get(k)
            if xs is None:
                xs = []
                self._by_name[k] = xs
            xs.append(self._wrap(instance))
        except Exception as e:
            show_warning(None, "InstanceRegistry.register failed", exc=e)

    def register_inferred(self, instance: Any) -> None:
        n = self.infer_name(instance)
        if n:
            self.register(n, instance)

    def has(self, name: str) -> bool:
        return bool(self.get_all(name))

    def get_all(self, name: str) -> List[Any]:
        if not name:
            return []
        k = str(name)
        xs = self._by_name.get(k)
        if not xs:
            return []
        out: List[Any] = []
        kept: List[Any] = []
        for entry in xs:
            v = self._unwrap(entry)
            if v is None:
                continue
            if not self.is_valid(v):
                continue
            out.append(v)
            kept.append(entry)
        if len(kept) != len(xs):
            self._by_name[k] = kept
        return out

    def get_one(self, name: str) -> Any:
        xs = self.get_all(name)
        return xs[0] if xs else None

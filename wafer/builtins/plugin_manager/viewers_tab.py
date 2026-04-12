from PySide6 import QtWidgets, QtCore
from ...utils.formatting import dpix
from ...core.lang.manager import t


class _ReorderList(QtWidgets.QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setMinimumHeight(dpix(80))

        hint_style = f"color: rgba(128,128,128,0.6); font-size: {dpix(10)}px; font-weight: bold; background: transparent;"
        self._high_hint = QtWidgets.QLabel("\u25b2 High", self)
        self._high_hint.setStyleSheet(hint_style)
        self._high_hint.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self._low_hint = QtWidgets.QLabel("\u25bc Low", self)
        self._low_hint.setStyleSheet(hint_style)
        self._low_hint.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        m = dpix(6)
        vp = self.viewport().geometry()
        self._high_hint.adjustSize()
        self._low_hint.adjustSize()
        self._high_hint.move(vp.right() - self._high_hint.width() - m, vp.top() + m)
        self._low_hint.move(vp.right() - self._low_hint.width() - m, vp.bottom() - self._low_hint.height() - m)

    def set_plugins(self, plugins: list[type]):
        self.clear()
        for cls in plugins:
            ext_str = ", ".join(cls.EXTENSIONS) if getattr(cls, "EXTENSIONS", None) else ""
            text = f"\u2261  {cls.NAME}"
            if ext_str:
                text += f"    {ext_str}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, cls.NAME)
            self.addItem(item)

    def get_order(self) -> list[str]:
        return [self.item(i).data(QtCore.Qt.UserRole) for i in range(self.count())]


REGISTRY_KEYS = ["grid", "viewer", "filter", "sort", "layout", "rename_source", "command"]

_PRIORITY_KEYS = frozenset({"grid", "viewer"})

REGISTRY_LABELS = {
    "viewer": "Viewer",
    "grid": "Grid",
    "filter": "Filter",
    "sort": "Sort",
    "layout": "Layout",
    "rename_source": "Rename Source",
    "command": "Command",
}


class OrderTab(QtWidgets.QWidget):
    @staticmethod
    def _dedup_by_name(plugins: list[type]) -> list[type]:
        seen: dict[str, type] = {}
        for cls in plugins:
            name = cls.NAME
            if name not in seen or cls.PRIORITY > seen[name].PRIORITY:
                seen[name] = cls
        return list(seen.values())

    def _prepare_plugins(self, key: str, plugins: list[type]) -> list[type]:
        if key == "command":
            deduped = self._dedup_by_name(plugins)
            return [c for c in deduped if c.NAME not in self._builtin_command_names]
        return plugins

    def __init__(self, registry_data: dict[str, list[type]], saved_orders: dict[str, list[str]], builtin_command_names: set[str] | None = None, parent=None):
        super().__init__(parent)
        self._builtin_command_names = builtin_command_names or set()
        self._lists: dict[str, _ReorderList] = {}
        self._labels: dict[str, QtWidgets.QLabel] = {}
        self._saved_orders: dict[str, list[str]] = {k: list(v) for k, v in saved_orders.items()}

        self._main_layout = QtWidgets.QVBoxLayout(self)
        self._main_layout.setSpacing(dpix(8))

        desc = QtWidgets.QLabel(t("Drag to reorder \u00b7 higher = preferred"))
        desc.setStyleSheet(f"color: #888; font-size: {dpix(10)}px;")
        self._main_layout.addWidget(desc)

        for key in REGISTRY_KEYS:
            self._add_section(key)
            plugins = self._prepare_plugins(key, registry_data.get(key, []))
            if not plugins:
                self._labels[key].hide()
                self._lists[key].hide()
                continue
            order = saved_orders.get(key, [])
            sorted_plugins = self._sorted_by_order(plugins, order)
            self._lists[key].set_plugins(sorted_plugins)

    def _add_section(self, key: str):
        suffix = "Priority" if key in _PRIORITY_KEYS else "Order"
        label = QtWidgets.QLabel(f"{REGISTRY_LABELS.get(key, key)} {suffix}")
        label.setObjectName("section_header")
        self._labels[key] = label
        self._main_layout.addWidget(label)
        reorder_list = _ReorderList()
        self._lists[key] = reorder_list
        self._main_layout.addWidget(reorder_list, 1)

    def _sorted_by_order(self, plugins: list[type], order: list[str]) -> list[type]:
        if not order:
            return list(plugins)
        order_map = {name: i for i, name in enumerate(order)}
        return sorted(
            plugins,
            key=lambda c: (0, order_map[c.NAME]) if c.NAME in order_map else (1, -c.PRIORITY),
        )

    def refresh(self, registry_data: dict[str, list[type]], builtin_command_names: set[str] | None = None):
        if builtin_command_names is not None:
            self._builtin_command_names = builtin_command_names
        for key in REGISTRY_KEYS:
            plugins = self._prepare_plugins(key, registry_data.get(key, []))
            reorder_list = self._lists[key]
            if not plugins:
                reorder_list.clear()
                reorder_list.hide()
                self._labels[key].hide()
                continue
            reorder_list.show()
            self._labels[key].show()
            incoming = {c.NAME for c in plugins}
            current = reorder_list.get_order()
            order = current if set(current) == incoming else self._saved_orders.get(key, [])
            sorted_plugins = self._sorted_by_order(plugins, order)
            reorder_list.set_plugins(sorted_plugins)

    def get_orders(self) -> dict[str, list[str]]:
        return {key: lst.get_order() for key, lst in self._lists.items()}

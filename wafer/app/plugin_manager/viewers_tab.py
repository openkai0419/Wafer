from PySide6 import QtWidgets, QtCore
from ...utils.formatting import dpix


class _ReorderList(QtWidgets.QListWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setMinimumHeight(dpix(80))

        hint_style = f'color: rgba(128,128,128,0.5); font-size: {dpix(9)}px; background: transparent;'
        self._high_hint = QtWidgets.QLabel('\u25b2 High', self)
        self._high_hint.setStyleSheet(hint_style)
        self._high_hint.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self._low_hint = QtWidgets.QLabel('\u25bc Low', self)
        self._low_hint.setStyleSheet(hint_style)
        self._low_hint.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        m = dpix(4)
        vp = self.viewport().geometry()
        self._high_hint.adjustSize()
        self._low_hint.adjustSize()
        self._high_hint.move(vp.right() - self._high_hint.width(), vp.top() + m)
        self._low_hint.move(vp.right() - self._low_hint.width(), vp.bottom() - self._low_hint.height())

    def set_plugins(self, plugins: list[type]):
        self.clear()
        for cls in plugins:
            ext_str = ', '.join(cls.EXTENSIONS) if cls.EXTENSIONS else ''
            text = f'{cls.NAME}  {ext_str}'.strip()
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, cls.NAME)
            self.addItem(item)

    def get_order(self) -> list[str]:
        return [
            self.item(i).data(QtCore.Qt.UserRole)
            for i in range(self.count())
        ]


class ViewersTab(QtWidgets.QWidget):

    def __init__(self, viewer_plugins: list[type], grid_plugins: list[type],
                 viewer_order: list[str], grid_order: list[str], parent=None):
        super().__init__(parent)

        self._viewer_list = _ReorderList()
        self._grid_list = _ReorderList()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(dpix(8))

        viewer_label = QtWidgets.QLabel('Viewer Priority (drag to reorder)')
        viewer_label.setStyleSheet(f'font-weight: bold; font-size: {dpix(12)}px;')
        layout.addWidget(viewer_label)
        layout.addWidget(self._viewer_list, 1)

        grid_label = QtWidgets.QLabel('Grid Priority (drag to reorder)')
        grid_label.setStyleSheet(f'font-weight: bold; font-size: {dpix(12)}px;')
        layout.addWidget(grid_label)
        layout.addWidget(self._grid_list, 1)

        self._populate(viewer_plugins, grid_plugins, viewer_order, grid_order)

    def _populate(self, viewer_plugins: list[type], grid_plugins: list[type],
                  viewer_order: list[str], grid_order: list[str]):
        viewer_sorted = self._sorted_by_order(viewer_plugins, viewer_order)
        grid_sorted = self._sorted_by_order(grid_plugins, grid_order)
        self._viewer_list.set_plugins(viewer_sorted)
        self._grid_list.set_plugins(grid_sorted)

    def _sorted_by_order(self, plugins: list[type], order: list[str]) -> list[type]:
        if not order:
            return list(plugins)
        order_map = {name: i for i, name in enumerate(order)}
        return sorted(
            plugins,
            key=lambda c: (0, order_map[c.NAME]) if c.NAME in order_map else (1, -c.PRIORITY),
        )

    def refresh(self, viewer_plugins: list[type], grid_plugins: list[type]):
        viewer_order = self._viewer_list.get_order()
        grid_order = self._grid_list.get_order()
        self._populate(viewer_plugins, grid_plugins, viewer_order, grid_order)

    def get_viewer_order(self) -> list[str]:
        return self._viewer_list.get_order()

    def get_grid_order(self) -> list[str]:
        return self._grid_list.get_order()

from PySide6 import QtWidgets, QtCore
from ...utils.formatting import dpix


class _ReorderList(QtWidgets.QListWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setMinimumHeight(dpix(80))

        hint_style = f'color: rgba(128,128,128,0.6); font-size: {dpix(10)}px; font-weight: bold; background: transparent;'
        self._high_hint = QtWidgets.QLabel('\u25b2 High', self)
        self._high_hint.setStyleSheet(hint_style)
        self._high_hint.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self._low_hint = QtWidgets.QLabel('\u25bc Low', self)
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
            ext_str = ', '.join(cls.EXTENSIONS) if cls.EXTENSIONS else ''
            text = f'\u2261  {cls.NAME}'
            if ext_str:
                text += f'    {ext_str}'
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
        self._saved_viewer_order = list(viewer_order)
        self._saved_grid_order = list(grid_order)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(dpix(8))

        viewer_label = QtWidgets.QLabel('Viewer Priority')
        viewer_label.setObjectName('section_header')
        viewer_desc = QtWidgets.QLabel('Drag to reorder \u00b7 higher = preferred')
        viewer_desc.setStyleSheet(f'color: #888; font-size: {dpix(10)}px;')
        layout.addWidget(viewer_label)
        layout.addWidget(viewer_desc)
        layout.addWidget(self._viewer_list, 1)

        grid_label = QtWidgets.QLabel('Grid Priority')
        grid_label.setObjectName('section_header')
        grid_desc = QtWidgets.QLabel('Drag to reorder \u00b7 higher = preferred')
        grid_desc.setStyleSheet(f'color: #888; font-size: {dpix(10)}px;')
        layout.addWidget(grid_label)
        layout.addWidget(grid_desc)
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
        incoming_viewers = {c.NAME for c in viewer_plugins}
        incoming_grids = {c.NAME for c in grid_plugins}
        current_viewer = self._viewer_list.get_order()
        current_grid = self._grid_list.get_order()
        viewer_order = current_viewer if set(current_viewer) == incoming_viewers else self._saved_viewer_order
        grid_order = current_grid if set(current_grid) == incoming_grids else self._saved_grid_order
        self._populate(viewer_plugins, grid_plugins, viewer_order, grid_order)

    def get_viewer_order(self) -> list[str]:
        return self._viewer_list.get_order()

    def get_grid_order(self) -> list[str]:
        return self._grid_list.get_order()

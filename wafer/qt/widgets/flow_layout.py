from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class FlowLayout(QtWidgets.QLayout):
    def __init__(self, parent: QtWidgets.QWidget | None = None, margin: int = 0, spacing: int = 0):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._spacing = spacing
        self._items: list[QtWidgets.QLayoutItem] = []

    def addItem(self, item):
        self._items.append(item)

    def insertWidget(self, index: int, widget: QtWidgets.QWidget) -> None:
        self.addWidget(widget)
        self._items.insert(index, self._items.pop())
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return QtCore.Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QtCore.QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self.visible_items():
            size = size.expandedTo(item.minimumSize())
        return size.grownBy(self.contentsMargins())

    def single_line_size(self) -> QtCore.QSize:
        items = self.visible_items()
        width = sum(item.sizeHint().width() for item in items) + self._spacing * max(len(items) - 1, 0)
        height = max((item.sizeHint().height() for item in items), default=0)
        return QtCore.QSize(width, height).grownBy(self.contentsMargins())

    def visible_items(self) -> list[QtWidgets.QLayoutItem]:
        return [item for item in self._items if not item.isEmpty()]

    def _do_layout(self, rect: QtCore.QRect, test_only: bool) -> int:
        area = rect.marginsRemoved(self.contentsMargins())
        x = area.x()
        y = area.y()
        line_height = 0
        for item in self.visible_items():
            hint = item.sizeHint()
            width = min(hint.width(), area.width()) if area.width() > 0 else hint.width()
            height = item.heightForWidth(width) if item.hasHeightForWidth() else hint.height()
            next_x = x + width + self._spacing
            if next_x - self._spacing > area.right() + 1 and line_height > 0:
                x = area.x()
                y += line_height + self._spacing
                next_x = x + width + self._spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QtCore.QRect(x, y, width, height))
            x = next_x
            line_height = max(line_height, height)
        margins = self.contentsMargins()
        return y + line_height - rect.y() + margins.bottom()

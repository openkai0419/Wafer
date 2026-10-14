from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.qt.common.dpi import dpix
from wafer.qt.common.geometry import screen_geometry_for
from wafer.qt.theme import ThemeManager

GAP = 12
FLIP_GAP = 16


class HoverPreview(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        palette = ThemeManager.instance().palette
        self.setStyleSheet(
            f"HoverPreview {{ background: {palette.bg_elevated}; border: 1px solid {palette.border_default}; }}QLabel {{ border: none; background: transparent; color: {palette.text_primary}; }}"
        )
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(4), dpix(4), dpix(4), dpix(4))
        layout.setSpacing(dpix(2))
        self.image = QtWidgets.QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.name = QtWidgets.QLabel()
        self.name.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.image)
        layout.addWidget(self.name)

    def show_image(self, pixmap: QtGui.QPixmap, name: str, cursor: QtCore.QPoint, size: int):
        side = dpix(size)
        self.image.setPixmap(pixmap.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation) if not pixmap.isNull() else QtGui.QPixmap())
        self.name.setText(self.name.fontMetrics().elidedText(name, Qt.ElideMiddle, side))
        self.adjustSize()
        self.place(cursor)
        self.show()
        self.raise_()

    def place(self, cursor: QtCore.QPoint):
        bounds = screen_geometry_for(cursor, self)
        width, height = self.width(), self.height()
        x = cursor.x() - width // 2
        y = cursor.y() - dpix(GAP) - height
        if bounds is not None:
            x = min(max(x, bounds.left()), bounds.right() - width + 1)
            if y < bounds.top():
                y = cursor.y() + dpix(GAP) + dpix(FLIP_GAP)
        self.move(x, y)

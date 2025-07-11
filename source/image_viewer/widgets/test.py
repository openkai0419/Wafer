from PySide6.QtWidgets import (
    QApplication, QAbstractScrollArea, QLabel, QWidget, QPushButton
)
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QPainter, Qt


class ContentWidget(QWidget):
    def __init__(self):
        super().__init__()
        QLabel("Negative", self).move(-150, -100)
        QLabel("Positive", self).move(300, 200)
        QPushButton("Far Negative", self).move(-300, -200)
        QPushButton("Far Positive", self).move(500, 400)

    def boundingRect(self):
        # 自分と子ウィジェットの矩形をすべて計算
        rect = QRect(0, 0, 0, 0)
        for child in self.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            r = child.geometry()
            if rect.isNull():
                rect = r
            else:
                rect = rect.united(r)
        return rect


class FlexibleScrollArea(QAbstractScrollArea):
    def __init__(self, content):
        super().__init__()
        self.content = content
        self.updateScrollbars()

    def updateScrollbars(self):
        br = self.content.boundingRect()

        self.min_x = br.left()
        self.min_y = br.top()
        self.max_x = br.right()
        self.max_y = br.bottom()

        vp_size = self.viewport().size()

        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()

        hbar.setRange(self.min_x, self.max_x - vp_size.width())
        hbar.setPageStep(vp_size.width())

        vbar.setRange(self.min_y, self.max_y - vp_size.height())
        vbar.setPageStep(vp_size.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateScrollbars()

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), Qt.white)

        x_offset = self.horizontalScrollBar().value()
        y_offset = self.verticalScrollBar().value()

        painter.translate(-x_offset, -y_offset)

        self.content.render(painter)

    def sizeHint(self):
        return QSize(400, 300)


if __name__ == "__main__":
    app = QApplication([])

    content = ContentWidget()
    viewer = FlexibleScrollArea(content)
    viewer.setWindowTitle("Flexible Scroll Area (Both Directions)")
    viewer.resize(600, 400)
    viewer.show()
    import sys
    sys.exit(app.exec())

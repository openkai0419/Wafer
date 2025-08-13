from PySide6 import QtCore, QtGui
from ..common.funcs import get_resource_path, uipx
from ..common.profiling import logger

class PixmapFactory:

    @staticmethod
    def generate():
        try:
            imgpath = get_resource_path() / 'fail_fetch_02.png'
            pixmap = QtGui.QPixmap(imgpath)
            if not pixmap.isNull():
                return pixmap
        except Exception as e:
            logger.warning(f'Failed to load error image: {e}')
        size = QtCore.QSize(64, 64)
        pixmap = QtGui.QPixmap(size)
        pixmap.fill(QtGui.QColor('#ccc'))
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(QtCore.Qt.red, 4)
        painter.setPen(pen)
        painter.drawLine(10, 10, 54, 54)
        painter.drawLine(10, 54, 54, 10)
        painter.end()
        PixmapFactory.draw_centered_text_with_background(pixmap, 'error')
        return pixmap

    @staticmethod
    def draw_centered_text_with_background(pixmap, text, font=None, padding=4, text_color=QtGui.QColor('#FFFFFF'), bg_color=QtGui.QColor('#3B80FF')):
        pixmap_copy = QtGui.QPixmap(pixmap)
        painter = QtGui.QPainter(pixmap_copy)
        if font is None:
            font = painter.font()
            font.setBold(True)
            font.setPointSize(uipx(12))
        painter.setFont(font)
        metrics = QtGui.QFontMetrics(font)
        text_rect = metrics.boundingRect(text)
        bg_width = text_rect.width() + padding * 2
        bg_height = text_rect.height() + padding * 2
        center_x = pixmap.width() // 2
        center_y = pixmap.height() // 2
        bg_x = center_x - bg_width // 2
        bg_y = center_y - bg_height // 2
        bg_rect = QtCore.QRect(bg_x, bg_y, bg_width, bg_height)
        painter.setBrush(bg_color)
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRect(bg_rect)
        text_x = bg_x + padding
        text_y = bg_y + padding + metrics.ascent()
        painter.setPen(text_color)
        painter.drawText(text_x, text_y, text)
        painter.end()
        return pixmap_copy

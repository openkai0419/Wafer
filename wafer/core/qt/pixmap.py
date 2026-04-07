from PySide6 import QtCore, QtGui
from ...utils.paths import get_resource_path
from ...utils.formatting import dpix
from ...utils.logs import AppLogger
from ..color.theme import ThemeManager


class PixmapFactory:
    @staticmethod
    def _load_resource_image(filename: str) -> QtGui.QPixmap | None:
        try:
            imgpath = get_resource_path() / filename
            pixmap = QtGui.QPixmap(imgpath)
            if not pixmap.isNull():
                return pixmap
        except Exception as e:
            AppLogger.warning(f"Failed to load resource image {filename}: {e}")
        return None

    @staticmethod
    def create_error_placeholder():
        pixmap = PixmapFactory._load_resource_image("fail_fetch_02.png")
        if pixmap is not None:
            return pixmap
        s = dpix(64)
        size = QtCore.QSize(s, s)
        pixmap = QtGui.QPixmap(size)
        pixmap.fill(QtGui.QColor(ThemeManager.instance().palette.text_primary))
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        m = dpix(10)
        pen = QtGui.QPen(QtCore.Qt.red, dpix(4))
        painter.setPen(pen)
        painter.drawLine(m, m, s - m, s - m)
        painter.drawLine(m, s - m, s - m, m)
        painter.end()
        pixmap = PixmapFactory.draw_centered_text_with_background(pixmap, "error")
        return pixmap

    @staticmethod
    def create_viewer_error_placeholder() -> QtGui.QImage:
        pixmap = PixmapFactory._load_resource_image("fail_fetch_01.png")
        if pixmap is not None:
            return pixmap.toImage()
        return PixmapFactory.create_error_placeholder().toImage()

    @staticmethod
    def draw_centered_text_with_background(pixmap, text, font=None, padding=None, text_color=QtGui.QColor("#FFFFFF"), bg_color=None):
        if bg_color is None:
            bg_color = QtGui.QColor(ThemeManager.instance().palette.accent)
        if padding is None:
            padding = dpix(4)
        pixmap_copy = QtGui.QPixmap(pixmap)
        painter = QtGui.QPainter(pixmap_copy)
        if font is None:
            font = painter.font()
            font.setBold(True)
            font.setPointSize(dpix(12))
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

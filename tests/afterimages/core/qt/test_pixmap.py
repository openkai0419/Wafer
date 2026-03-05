import py_compile
from PySide6 import QtGui, QtWidgets
import pytest


def test_compile():
    py_compile.compile('afterimages/core/qt/pixmap.py')


def test_error_placeholder_has_text(qtbot):
    from afterimages.core.qt.pixmap import PixmapFactory
    pixmap = PixmapFactory.create_error_placeholder()
    assert not pixmap.isNull()
    img = pixmap.toImage()
    center_color = img.pixelColor(img.width() // 2, img.height() // 2)
    assert center_color != QtGui.QColor('#ccc')


def test_draw_centered_text_returns_modified_copy(qtbot):
    from afterimages.core.qt.pixmap import PixmapFactory
    original = QtGui.QPixmap(100, 100)
    original.fill(QtGui.QColor('#ffffff'))
    result = PixmapFactory.draw_centered_text_with_background(original, 'test')
    assert result is not original
    assert not result.isNull()

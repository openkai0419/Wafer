import pytest
from PySide6 import QtCore, QtGui

from extensions.mapping.hover_preview import HoverPreview


@pytest.fixture()
def preview(qtbot):
    widget = HoverPreview()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


def available():
    return QtGui.QGuiApplication.primaryScreen().availableGeometry()


def test_preview_sits_above_cursor(preview):
    cursor = available().center()
    preview.show_image(QtGui.QPixmap(64, 64), "a.png", cursor, 128)
    assert preview.isVisible()
    assert preview.geometry().bottom() < cursor.y()
    assert abs(preview.geometry().center().x() - cursor.x()) <= 2


def test_preview_flips_below_near_top_edge(preview):
    screen = available()
    cursor = QtCore.QPoint(screen.center().x(), screen.top() + 5)
    preview.show_image(QtGui.QPixmap(64, 64), "a.png", cursor, 256)
    assert preview.geometry().top() > cursor.y()


def test_preview_stays_inside_screen_horizontally(preview):
    screen = available()
    cursor = QtCore.QPoint(screen.left() + 2, screen.center().y())
    preview.show_image(QtGui.QPixmap(64, 64), "a.png", cursor, 128)
    assert preview.geometry().left() >= screen.left()


def test_preview_never_takes_the_mouse(preview):
    assert preview.windowFlags() & QtCore.Qt.WindowTransparentForInput
    assert preview.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
    assert preview.testAttribute(QtCore.Qt.WA_StyledBackground)


def test_place_moves_without_rescaling(preview, monkeypatch):
    cursor = available().center()
    preview.show_image(QtGui.QPixmap(64, 64), "a.png", cursor, 128)
    monkeypatch.setattr(preview.image, "setPixmap", lambda *args: (_ for _ in ()).throw(AssertionError("rescaled")))
    before = preview.pos()
    preview.place(cursor + QtCore.QPoint(40, 0))
    assert preview.pos().x() == before.x() + 40

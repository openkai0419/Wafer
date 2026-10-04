import pytest
from unittest.mock import MagicMock, patch
from PySide6 import QtGui


class TestAnimatedCellWidget:
    @pytest.fixture
    def widget(self):
        from extensions.animated.widget import AnimatedCellWidget

        w = AnimatedCellWidget()
        yield w
        w.deleteLater()

    def test_suspend_resets_state(self, widget):
        widget._path = "test.gif"
        widget._frames = [MagicMock()]
        widget._delays = [100]
        widget._playing = True
        widget.suspend()
        assert widget._path == ""
        assert widget._frames == []
        assert widget._delays == []
        assert widget._thumbnail is None
        assert not widget._playing

    def test_suspend_disposes_uncached_frames(self, widget):
        from extensions.animated.widget import _disposer

        frames = [MagicMock()]
        widget._path = "uncached.gif"
        widget._frames = frames
        widget._delays = [100]
        with patch.object(_disposer, "schedule") as mock_schedule:
            widget.suspend()
            mock_schedule.assert_called_once_with(frames)

    def test_start_noop_single_frame(self, widget):
        widget._frames = [MagicMock()]
        widget._delays = [100]
        widget.start()
        assert not widget._playing

    def test_start_with_multiple_frames(self, widget):
        widget._frames = [MagicMock(), MagicMock()]
        widget._delays = [100, 100]
        widget.start()
        assert widget._playing
        widget.stop()

    def test_advance_cycles_frame_index(self, widget):
        widget._frames = [MagicMock(), MagicMock(), MagicMock()]
        widget._delays = [30, 30, 30]
        widget._playing = True
        widget._accumulated = 0
        widget.advance(33)
        assert widget._frame_index == 1
        widget.advance(33)
        assert widget._frame_index == 2

    def test_on_appeared_starts(self, widget):
        widget._frames = [MagicMock(), MagicMock()]
        widget._delays = [100, 100]
        widget.on_appeared()
        assert widget._playing
        widget.stop()

    def test_on_disappeared_stops(self, widget):
        widget._frames = [MagicMock(), MagicMock()]
        widget._delays = [100, 100]
        widget.start()
        widget.on_disappeared()
        assert not widget._playing

    def test_set_frames_sets_state(self, widget):
        frames = [MagicMock(), MagicMock()]
        delays = [100, 100]
        widget.set_frames("test.gif", frames, delays)
        assert widget._path == "test.gif"
        assert widget._frames is frames
        assert widget._delays is delays
        assert widget._thumbnail is frames[0]
        assert widget._frame_index == 0

    def test_set_thumbnail_sets_pixmap(self, widget):
        widget._path = "test.gif"
        image = QtGui.QImage(10, 10, QtGui.QImage.Format.Format_ARGB32)
        widget.set_thumbnail(image)
        assert widget._thumbnail is not None

    def test_set_thumbnail_skips_when_already_set(self, widget):
        widget._path = "test.gif"
        first = QtGui.QPixmap(10, 10)
        widget._thumbnail = first
        image = QtGui.QImage(10, 10, QtGui.QImage.Format.Format_ARGB32)
        widget.set_thumbnail(image)
        assert widget._thumbnail is first

    def test_paint_fills_cell_small_pixmap(self, widget, qtbot):
        pm = QtGui.QPixmap(50, 50)
        pm.fill(QtGui.QColor("red"))
        widget.set_frames("up.gif", [pm], [100])
        widget.resize(200, 200)
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)
        widget.repaint()
        grab = widget.grab()
        img = grab.toImage()
        center = img.pixelColor(100, 100)
        assert center.red() > 200

    def test_paint_fills_cell_large_pixmap(self, widget, qtbot):
        pm = QtGui.QPixmap(400, 200)
        pm.fill(QtGui.QColor("blue"))
        widget.set_frames("down.gif", [pm], [100])
        widget.setFixedSize(100, 100)
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        widget.repaint()
        grab = widget.grab()
        img = grab.toImage()
        corner = img.pixelColor(5, 5)
        center = img.pixelColor(50, 50)
        assert corner.blue() > 200
        assert center.blue() > 200

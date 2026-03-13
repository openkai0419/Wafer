import pytest
from unittest.mock import MagicMock, patch
from PySide6 import QtCore, QtGui


class TestFrameCache:

    def test_put_and_get(self):
        from extensions.animated.widget import FrameCache
        cache = FrameCache()
        frames = [MagicMock()]
        delays = [100]
        cache.put('a.gif', frames, delays)
        result = cache.get('a.gif')
        assert result == (frames, delays)

    def test_get_missing_returns_none(self):
        from extensions.animated.widget import FrameCache
        cache = FrameCache()
        assert cache.get('missing.gif') is None

    def test_lru_eviction(self):
        from extensions.animated.widget import FrameCache
        cache = FrameCache(max_entries=2)
        cache.put('a.gif', [MagicMock()], [100])
        cache.put('b.gif', [MagicMock()], [100])
        cache.put('c.gif', [MagicMock()], [100])
        assert cache.get('a.gif') is None
        assert cache.get('b.gif') is not None
        assert cache.get('c.gif') is not None

    def test_lru_access_refreshes_order(self):
        from extensions.animated.widget import FrameCache
        cache = FrameCache(max_entries=2)
        cache.put('a.gif', [MagicMock()], [100])
        cache.put('b.gif', [MagicMock()], [100])
        cache.get('a.gif')
        cache.put('c.gif', [MagicMock()], [100])
        assert cache.get('a.gif') is not None
        assert cache.get('b.gif') is None

    def test_clear(self):
        from extensions.animated.widget import FrameCache
        cache = FrameCache()
        cache.put('a.gif', [MagicMock()], [100])
        cache.clear()
        assert cache.get('a.gif') is None

    def test_remove(self):
        from extensions.animated.widget import FrameCache
        cache = FrameCache()
        cache.put('a.gif', [MagicMock()], [100])
        cache.remove('a.gif')
        assert cache.get('a.gif') is None

    def test_remove_missing_key_no_error(self):
        from extensions.animated.widget import FrameCache
        cache = FrameCache()
        cache.remove('nonexistent.gif')

    def test_overwrite_existing_entry(self):
        from extensions.animated.widget import FrameCache
        cache = FrameCache(max_entries=2)
        frames1 = [MagicMock()]
        frames2 = [MagicMock(), MagicMock()]
        cache.put('a.gif', frames1, [100])
        cache.put('a.gif', frames2, [50, 50])
        result = cache.get('a.gif')
        assert result == (frames2, [50, 50])

    def test_get_if_sufficient_returns_entry_when_large_enough(self):
        from extensions.animated.widget import FrameCache
        cache = FrameCache()
        pm = QtGui.QPixmap(200, 100)
        cache.put('a.gif', [pm], [100])
        result = cache.get_if_sufficient('a.gif', QtCore.QSize(200, 100))
        assert result is not None
        assert result[0][0].width() == 200

    def test_get_if_sufficient_evicts_undersized_entry(self):
        from extensions.animated.widget import FrameCache
        cache = FrameCache()
        pm = QtGui.QPixmap(50, 50)
        cache.put('a.gif', [pm], [100])
        result = cache.get_if_sufficient('a.gif', QtCore.QSize(200, 200))
        assert result is None
        assert cache.get('a.gif') is None

    def test_get_if_sufficient_returns_none_for_missing(self):
        from extensions.animated.widget import FrameCache
        cache = FrameCache()
        assert cache.get_if_sufficient('missing.gif', QtCore.QSize(10, 10)) is None

    def test_thread_safety_put_get(self):
        import threading
        from extensions.animated.widget import FrameCache
        cache = FrameCache(max_entries=64)
        errors = []

        def writer(start):
            try:
                for i in range(50):
                    cache.put(f'{start}_{i}.gif', [MagicMock()], [100])
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    cache.get('0_0.gif')
                    cache.get_if_sufficient('0_1.gif', QtCore.QSize(10, 10))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


class TestAnimationDriver:

    def test_register_starts_timer(self, qtbot):
        from extensions.animated.widget import AnimationDriver
        driver = AnimationDriver()
        cell = MagicMock()
        driver.register(cell)
        assert driver._timer.isActive()
        driver.unregister(cell)

    def test_unregister_stops_timer_when_empty(self, qtbot):
        from extensions.animated.widget import AnimationDriver
        driver = AnimationDriver()
        cell = MagicMock()
        driver.register(cell)
        driver.unregister(cell)
        assert not driver._timer.isActive()

    def test_unregister_keeps_timer_with_remaining_cells(self, qtbot):
        from extensions.animated.widget import AnimationDriver
        driver = AnimationDriver()
        cell1 = MagicMock()
        cell2 = MagicMock()
        driver.register(cell1)
        driver.register(cell2)
        driver.unregister(cell1)
        assert driver._timer.isActive()
        driver.unregister(cell2)

    def test_register_idempotent(self, qtbot):
        from extensions.animated.widget import AnimationDriver
        driver = AnimationDriver()
        cell = MagicMock()
        driver.register(cell)
        driver.register(cell)
        assert len(driver._cells) == 1
        driver.unregister(cell)

    def test_unregister_nonexistent_no_error(self):
        from extensions.animated.widget import AnimationDriver
        driver = AnimationDriver()
        driver.unregister(MagicMock())

    def test_tick_calls_advance_on_cells(self, qtbot):
        from extensions.animated.widget import AnimationDriver
        driver = AnimationDriver()
        cell = MagicMock()
        driver.register(cell)
        driver._tick()
        cell.advance.assert_called_once()
        driver.unregister(cell)


class TestAnimatedCellWidget:

    @pytest.fixture
    def widget(self):
        from extensions.animated.widget import AnimatedCellWidget
        w = AnimatedCellWidget()
        yield w
        w.deleteLater()

    def test_initial_state(self, widget):
        assert widget._path == ''
        assert widget._frames == []
        assert widget._delays == []
        assert widget._frame_index == 0
        assert not widget._playing

    def test_suspend_resets_state(self, widget):
        widget._path = 'test.gif'
        widget._frames = [MagicMock()]
        widget._delays = [100]
        widget._playing = True
        widget.suspend()
        assert widget._path == ''
        assert widget._frames == []
        assert widget._delays == []
        assert widget._thumbnail is None
        assert not widget._playing

    def test_suspend_disposes_uncached_frames(self, widget):
        from extensions.animated.widget import _disposer
        frames = [MagicMock()]
        widget._path = 'uncached.gif'
        widget._frames = frames
        widget._delays = [100]
        with patch.object(_disposer, 'schedule') as mock_schedule:
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

    def test_stop_when_not_playing(self, widget):
        widget.stop()
        assert not widget._playing

    def test_advance_cycles_frame_index(self, widget):
        widget._frames = [MagicMock(), MagicMock(), MagicMock()]
        widget._delays = [30, 30, 30]
        widget._playing = True
        widget._accumulated = 0
        widget.advance(33)
        widget.advance(66)
        assert widget._frame_index > 0 or widget._accumulated > 0

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
        widget.set_frames('test.gif', frames, delays)
        assert widget._path == 'test.gif'
        assert widget._frames is frames
        assert widget._delays is delays
        assert widget._thumbnail is frames[0]
        assert widget._frame_index == 0

    def test_set_frames_resets_previous(self, widget):
        widget.set_frames('a.gif', [MagicMock()], [100])
        new_frames = [MagicMock(), MagicMock()]
        widget.set_frames('b.gif', new_frames, [50, 50])
        assert widget._path == 'b.gif'
        assert widget._frames is new_frames
        assert widget._frame_index == 0

    def test_set_thumbnail_sets_pixmap(self, widget):
        widget._path = 'test.gif'
        image = QtGui.QImage(10, 10, QtGui.QImage.Format.Format_ARGB32)
        widget.set_thumbnail(image)
        assert widget._thumbnail is not None

    def test_set_thumbnail_skips_when_already_set(self, widget):
        widget._path = 'test.gif'
        first = QtGui.QPixmap(10, 10)
        widget._thumbnail = first
        image = QtGui.QImage(10, 10, QtGui.QImage.Format.Format_ARGB32)
        widget.set_thumbnail(image)
        assert widget._thumbnail is first

    def test_on_selected_deselected_noop(self, widget):
        widget.on_selected()
        widget.on_deselected()

    def test_paint_scales_up_small_pixmap(self, widget, qtbot):
        pm = QtGui.QPixmap(50, 50)
        pm.fill(QtGui.QColor('red'))
        widget.set_frames('up.gif', [pm], [100])
        widget.resize(200, 200)
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)
        widget.repaint()
        assert widget._scaled_pixmap is not None
        assert widget._scaled_pixmap.width() == 200
        assert widget._scaled_pixmap.height() == 200

    def test_paint_scales_down_large_pixmap(self, widget, qtbot):
        pm = QtGui.QPixmap(400, 200)
        pm.fill(QtGui.QColor('blue'))
        widget.set_frames('down.gif', [pm], [100])
        widget.resize(100, 100)
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)
        widget.repaint()
        assert widget._scaled_pixmap is not None
        assert widget._scaled_pixmap.width() == 100
        assert widget._scaled_pixmap.height() == 50

    def test_paint_uses_smooth_when_stopped(self, widget, qtbot):
        pm = QtGui.QPixmap(50, 50)
        pm.fill(QtGui.QColor('green'))
        widget.set_frames('smooth.gif', [pm], [100])
        widget._playing = False
        widget.resize(200, 200)
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)
        widget.repaint()
        assert widget._scaled_pixmap is not None

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


class TestDecodeRunner:

    def test_run_emits_ready(self, qtbot, tmp_path):
        from extensions.animated.widget import _DecodeRunner
        from PIL import Image
        gif_path = str(tmp_path / 'test.gif')
        frames = [Image.new('RGB', (10, 10), c) for c in ['red', 'blue']]
        frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
        runner = _DecodeRunner(gif_path, None)
        results = []
        runner.signals.ready.connect(lambda p, i, d: results.append((p, i, d)))
        runner.run()
        assert len(results) == 1
        assert results[0][0] == gif_path
        assert len(results[0][1]) == 2

    def test_cancel_before_run_prevents_emission(self, qtbot, tmp_path):
        from extensions.animated.widget import _DecodeRunner
        from PIL import Image
        gif_path = str(tmp_path / 'test.gif')
        frames = [Image.new('RGB', (10, 10), c) for c in ['red', 'blue']]
        frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
        runner = _DecodeRunner(gif_path, None)
        results = []
        runner.signals.ready.connect(lambda p, i, d: results.append((p, i, d)))
        runner.cancel()
        runner.run()
        assert len(results) == 0

    def test_run_with_scaled_size(self, qtbot, tmp_path):
        from extensions.animated.widget import _DecodeRunner
        from PIL import Image
        gif_path = str(tmp_path / 'test.gif')
        frames = [Image.new('RGB', (100, 100), c) for c in ['red', 'blue']]
        frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
        runner = _DecodeRunner(gif_path, QtCore.QSize(50, 50))
        results = []
        runner.signals.ready.connect(lambda p, i, d: results.append((p, i, d)))
        runner.run()
        assert len(results) == 1
        for img in results[0][1]:
            assert img.width() <= 50 and img.height() <= 50


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
        assert widget._decode_runner is None

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
        assert widget._decode_runner is None

    def test_suspend_cancels_runners(self, widget):
        from extensions.animated.widget import _DecodeRunner
        decode = _DecodeRunner('test.gif', None)
        widget._decode_runner = decode
        widget.suspend()
        assert decode._cancelled
        assert widget._decode_runner is None

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

    def test_on_disappeared_cancels_decode_runner(self, widget):
        from extensions.animated.widget import _DecodeRunner
        runner = _DecodeRunner('test.gif', None)
        widget._path = 'test.gif'
        widget._decode_runner = runner
        widget.on_disappeared()
        assert runner._cancelled
        assert widget._decode_runner is None

    def test_on_appeared_restarts_decode_when_no_frames(self, widget):
        widget._path = 'test.gif'
        widget._load_size = QtCore.QSize(100, 100)
        widget._frames = []
        widget.on_appeared()
        assert widget._decode_runner is not None
        widget._cancel_runners()

    def test_load_with_cache_hit(self, widget):
        from extensions.animated.widget import _frame_cache
        frames = [MagicMock(), MagicMock()]
        delays = [100, 100]
        _frame_cache.put('/cached.gif', frames, delays)
        widget.load('/cached.gif')
        assert widget._frames is frames
        assert widget._delays is delays
        assert widget._decode_runner is None
        _frame_cache.remove('/cached.gif')

    def test_load_cache_miss_starts_decode_runner(self, widget, tmp_path):
        from PIL import Image
        gif_path = str(tmp_path / 'bg.gif')
        frames = [Image.new('RGB', (10, 10), c) for c in ['red', 'blue']]
        frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
        widget.load(gif_path)
        assert widget._decode_runner is not None
        assert widget._frames == []
        assert widget._thumbnail is None
        widget._cancel_runners()

    def test_load_nonexistent_starts_decode_runner(self, widget):
        widget.load('/nonexistent/file.gif')
        assert widget._decode_runner is not None
        widget._cancel_runners()

    def test_load_cancels_previous_runner(self, widget):
        from extensions.animated.widget import _DecodeRunner, _frame_cache
        decode = _DecodeRunner('old.gif', None)
        widget._decode_runner = decode
        widget._path = 'old.gif'
        _frame_cache.put('/new.gif', [MagicMock()], [100])
        widget.load('/new.gif')
        assert decode._cancelled
        _frame_cache.remove('/new.gif')

    def test_on_decode_ready_sets_frames(self, widget, qtbot):
        widget._path = 'test.gif'
        pixmaps = [QtGui.QPixmap(10, 10)]
        delays = [100]
        widget._on_decode_ready('test.gif', pixmaps, delays)
        assert len(widget._frames) == 1
        assert widget._delays == [100]
        assert widget._thumbnail is not None

    def test_on_decode_ready_ignores_wrong_path(self, widget):
        widget._path = 'current.gif'
        widget._on_decode_ready('old.gif', [], [])
        assert widget._frames == []
        assert widget._thumbnail is None

    def test_decode_runner_emits_pixmaps(self, qtbot, tmp_path):
        from extensions.animated.widget import _DecodeRunner
        from PIL import Image
        gif_path = str(tmp_path / 'test.gif')
        frames = [Image.new('RGB', (10, 10), c) for c in ['red', 'blue']]
        frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
        runner = _DecodeRunner(gif_path, None)
        results = []
        runner.signals.ready.connect(lambda p, pxs, d: results.append((p, pxs, d)))
        runner.run()
        assert len(results) == 1
        for px in results[0][1]:
            assert isinstance(px, QtGui.QPixmap)

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

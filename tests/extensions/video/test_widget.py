import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from PySide6 import QtCore, QtGui, QtWidgets


mpv_mock = MagicMock()
mpv_mock.MpvGlGetProcAddressFn = MagicMock(return_value=MagicMock())


@pytest.fixture(autouse=True)
def _patch_mpv(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'mpv', mpv_mock)
    from extensions.video.widget import MpvGLOverlay
    monkeypatch.setattr(MpvGLOverlay, '_mpv', mpv_mock)
    monkeypatch.setattr(MpvGLOverlay, '_init_attempted', True)

@pytest.fixture(autouse=True)
def _reset_shared(monkeypatch):
    from extensions.video.widget import MpvCellWidget
    monkeypatch.setattr(MpvCellWidget, '_slot_manager', None)
    monkeypatch.setattr(MpvCellWidget, '_shared_initialized', False)
    yield


class TestMpvGLOverlay:
    def test_create_player(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        player = MpvGLOverlay._create_player()
        assert player is not None
        assert player.volume == 40

    def test_init_with_prewarmed_player(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        player = MagicMock()
        overlay = MpvGLOverlay(player=player)
        assert overlay.player is player
        player.register_event_callback.assert_called_once()

    def test_activate_deferred_play(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay.activate('/test.mp4')
        overlay.player.play.assert_not_called()
        assert overlay._path == '/test.mp4'
        assert overlay._awaiting_first_frame
        QtWidgets.QApplication.instance().processEvents()
        overlay.player.command_async.assert_called_once_with('loadfile', '/test.mp4')

    def test_activate_hidden_when_ctx_exists(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay._ctx = MagicMock()
        overlay.activate('/test.mp4')
        assert not overlay.isVisible()
        assert overlay._awaiting_first_frame

    def test_activate_shows_when_ctx_none(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay.activate('/test.mp4')
        assert overlay.isVisible()

    def test_first_frame_shows_overlay(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay._ctx = MagicMock()
        overlay.activate('/test.mp4')
        assert not overlay.isVisible()
        overlay._frame_generation = overlay._play_generation
        overlay._frame_ready = True
        overlay._request_update()
        assert not overlay.isVisible()
        overlay._playback_ready = True
        overlay._frame_ready = True
        overlay._frame_generation = overlay._play_generation
        overlay._request_update()
        QtWidgets.QApplication.instance().processEvents()
        assert overlay.isVisible()
        assert not overlay._awaiting_first_frame

    def test_deactivate_stops_and_hides(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay.activate('/test.mp4')
        QtWidgets.QApplication.instance().processEvents()
        overlay.deactivate()
        overlay.player.command_async.assert_called_with('stop')
        assert overlay._path is None
        assert not overlay.isVisible()

    def test_stale_deferred_play_ignored(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay.activate('/a.mp4')
        overlay.deactivate()
        QtWidgets.QApplication.instance().processEvents()
        overlay.player.play.assert_not_called()

    def test_paintgl_blocks_stale_render(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay._ctx = MagicMock()
        overlay._awaiting_first_frame = True
        overlay._frame_ready = False
        overlay._clear_gl = MagicMock()
        overlay.paintGL()
        overlay._ctx.render.assert_not_called()
        overlay._clear_gl.assert_called_once()

    def test_paintgl_clears_while_awaiting(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay._ctx = MagicMock()
        overlay._clear_gl = MagicMock()
        overlay._awaiting_first_frame = True
        overlay._frame_ready = True
        overlay.paintGL()
        overlay._ctx.render.assert_not_called()
        overlay._clear_gl.assert_called_once()

    def test_paintgl_renders_after_first_frame_shown(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay._ctx = MagicMock()
        overlay._awaiting_first_frame = False
        overlay._frame_ready = True
        overlay.paintGL()
        overlay._ctx.render.assert_called_once()

    def test_stale_callback_after_deactivate_no_show(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay._ctx = MagicMock()
        overlay.activate('/test.mp4')
        overlay.deactivate()
        overlay._frame_ready = True
        overlay._request_update()
        assert not overlay.isVisible()

    def test_cleanup_frees_resources(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        mock_ctx = MagicMock()
        overlay._ctx = mock_ctx
        overlay.player = MagicMock()
        overlay.cleanup()
        mock_ctx.free.assert_called_once()
        assert overlay._ctx is None
        assert overlay.player is None


class TestMpvCellWidget:
    def test_is_qwidget_not_opengl(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        from PySide6.QtOpenGLWidgets import QOpenGLWidget
        w = MpvCellWidget()
        assert isinstance(w, QtWidgets.QWidget)
        assert not isinstance(w, QOpenGLWidget)
        w.cleanup()

    def test_init_shared_creates_slot_manager(self, qtbot):
        from extensions.video.widget import MpvCellWidget, PlaybackSlotManager
        parent = QtWidgets.QWidget()
        w = MpvCellWidget(parent)
        assert isinstance(MpvCellWidget._slot_manager, PlaybackSlotManager)
        w.cleanup()

    def test_init_shared_syncs_default_checked_without_pending(self, qtbot, monkeypatch):
        from extensions.video.widget import MpvCellWidget
        from unittest.mock import MagicMock
        mock_cmd = MagicMock()
        monkeypatch.setattr('wafer.core.actions.bridge.Command.set_checked', mock_cmd)
        MpvCellWidget._pending_grid_state = None
        w = MpvCellWidget()
        synced = {c.args[0]: c.args[1] for c in mock_cmd.call_args_list}
        assert synced.get('vgrid.toggle_hover_autoplay') is True
        assert synced.get('vgrid.toggle_appear_autoplay') is True
        w.cleanup()

    def test_init_shared_skips_default_sync_when_pending(self, qtbot, monkeypatch):
        from extensions.video.widget import MpvCellWidget
        from unittest.mock import MagicMock
        mock_cmd = MagicMock()
        monkeypatch.setattr('wafer.core.actions.bridge.Command.set_checked', mock_cmd)
        MpvCellWidget._pending_grid_state = {'hover_autoplay': False, 'appear_autoplay': False, 'volume': 50}
        w = MpvCellWidget()
        synced = {c.args[0]: c.args[1] for c in mock_cmd.call_args_list}
        assert synced.get('vgrid.toggle_hover_autoplay') is False
        assert synced.get('vgrid.toggle_appear_autoplay') is False
        w.cleanup()

    def test_load_sets_path(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        w = MpvCellWidget()
        w.resize(200, 150)
        w.load('/test.mp4')
        assert w._path == '/test.mp4'
        w.cleanup()

    def test_set_thumbnail_sets_image(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        w = MpvCellWidget()
        w._path = '/test.mp4'
        image = QtGui.QImage(100, 100, QtGui.QImage.Format_ARGB32)
        w.set_thumbnail(image)
        assert w._thumbnail is image
        w.cleanup()

    def test_set_thumbnail_skips_when_already_set(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        w = MpvCellWidget()
        w._path = '/test.mp4'
        first = QtGui.QImage(10, 10, QtGui.QImage.Format_ARGB32)
        w._thumbnail = first
        second = QtGui.QImage(20, 20, QtGui.QImage.Format_ARGB32)
        w.set_thumbnail(second)
        assert w._thumbnail is first
        w.cleanup()

    def test_suspend_clears_state(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        w = MpvCellWidget()
        w._path = '/test.mp4'
        w._thumbnail = QtGui.QImage()
        w.suspend()
        assert w._path is None
        assert w._thumbnail is None
        w.cleanup()

    def test_resume_is_noop(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        w = MpvCellWidget()
        w.resume()
        w.cleanup()

    def test_suspend_releases_cell_from_slot_manager(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        parent = QtWidgets.QWidget()
        w = MpvCellWidget(parent)
        w._path = '/test.mp4'
        w.setGeometry(0, 0, 200, 150)
        sm = MpvCellWidget._slot_manager
        sm.activate_hover(w, '/test.mp4')
        sm._apply_hover()
        assert sm._hover_cell is w
        w.suspend()
        assert sm._hover_cell is None
        w.cleanup()

    def test_on_selected_activates_select(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        parent = QtWidgets.QWidget()
        w = MpvCellWidget(parent)
        w._path = '/test.mp4'
        w.setGeometry(0, 0, 200, 150)
        w.on_selected()
        assert MpvCellWidget._slot_manager.is_selected(w)
        w.cleanup()

    def test_on_deselected_deactivates_select(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        parent = QtWidgets.QWidget()
        w = MpvCellWidget(parent)
        w._path = '/test.mp4'
        w.setGeometry(0, 0, 200, 150)
        w.on_selected()
        w.on_deselected()
        assert not MpvCellWidget._slot_manager.is_selected(w)
        w.cleanup()

    def test_on_appeared_activates_appear(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        parent = QtWidgets.QWidget()
        w = MpvCellWidget(parent)
        w._path = '/test.mp4'
        w.setGeometry(0, 0, 200, 150)
        w.on_appeared()
        assert MpvCellWidget._slot_manager.is_appeared(w)
        QtWidgets.QApplication.instance().processEvents()
        assert w in MpvCellWidget._slot_manager._appeared
        w.cleanup()

    def test_on_disappeared_deactivates_appear(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        parent = QtWidgets.QWidget()
        w = MpvCellWidget(parent)
        w._path = '/test.mp4'
        w.setGeometry(0, 0, 200, 150)
        w.on_appeared()
        QtWidgets.QApplication.instance().processEvents()
        w.on_disappeared()
        assert not MpvCellWidget._slot_manager.is_appeared(w)
        w.cleanup()

    def test_deselect_keeps_playback_if_appeared(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        parent = QtWidgets.QWidget()
        w = MpvCellWidget(parent)
        w._path = '/test.mp4'
        w.setGeometry(0, 0, 200, 150)
        w.on_appeared()
        QtWidgets.QApplication.instance().processEvents()
        w.on_selected()
        overlay = MpvCellWidget._slot_manager._selected[w]
        w.on_deselected()
        assert not MpvCellWidget._slot_manager.is_selected(w)
        assert MpvCellWidget._slot_manager.is_appeared(w)
        assert MpvCellWidget._slot_manager._appeared[w] is overlay
        w.cleanup()

    def test_overlay_leave_deactivates_hover(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        parent = QtWidgets.QWidget()
        w = MpvCellWidget(parent)
        w._path = '/test.mp4'
        w.setGeometry(0, 0, 200, 150)
        sm = MpvCellWidget._slot_manager
        sm.activate_hover(w, '/test.mp4')
        sm._apply_hover()
        MpvCellWidget._on_overlay_leave(w)
        assert sm._hover_cell is None
        w.cleanup()

    def test_overlay_leave_keeps_selected(self, qtbot):
        from extensions.video.widget import MpvCellWidget
        parent = QtWidgets.QWidget()
        w = MpvCellWidget(parent)
        w._path = '/test.mp4'
        w.setGeometry(0, 0, 200, 150)
        sm = MpvCellWidget._slot_manager
        sm.activate_select(w, '/test.mp4')
        MpvCellWidget._on_overlay_leave(w)
        assert sm.is_selected(w)
        w.cleanup()


class TestStaleFramePrevention:
    def test_stale_generation_frame_rejected(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay._ctx = MagicMock()
        overlay.activate('/a.mp4')
        stale_gen = overlay._play_generation - 1
        overlay._frame_generation = stale_gen
        overlay._frame_ready = True
        overlay._request_update()
        assert not overlay.isVisible()
        assert not overlay._frame_ready

    def test_no_show_without_playback_ready(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay._ctx = MagicMock()
        overlay.activate('/a.mp4')
        overlay._frame_generation = overlay._play_generation
        overlay._frame_ready = True
        overlay._request_update()
        assert not overlay.isVisible()
        assert overlay._awaiting_first_frame

    def test_full_first_frame_flow(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay._ctx = MagicMock()
        overlay.activate('/a.mp4')
        assert not overlay.isVisible()
        overlay._handle_playback_ready(overlay._play_generation)
        assert overlay._playback_ready
        assert not overlay.isVisible()
        overlay._frame_generation = overlay._play_generation
        overlay._frame_ready = True
        overlay._request_update()
        QtWidgets.QApplication.instance().processEvents()
        assert overlay.isVisible()
        assert not overlay._awaiting_first_frame
        overlay._ctx.render.reset_mock()
        overlay._frame_ready = True
        overlay.paintGL()
        overlay._ctx.render.assert_called_once()

    def test_switch_deactivate_ignores_stale_frame_callback(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay._ctx = MagicMock()
        overlay.activate('/a.mp4')
        old_gen = overlay._play_generation
        overlay.deactivate()
        overlay._frame_generation = old_gen
        overlay._frame_ready = True
        overlay._request_update()
        assert not overlay.isVisible()

    def test_stale_playback_ready_ignored(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay._ctx = MagicMock()
        overlay.activate('/a.mp4')
        old_gen = overlay._play_generation
        overlay.deactivate()
        overlay.activate('/b.mp4')
        overlay._handle_playback_ready(old_gen)
        assert not overlay._playback_ready

    def test_playback_ready_before_frame_then_frame_shows(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay._ctx = MagicMock()
        overlay.activate('/a.mp4')
        overlay._handle_playback_ready(overlay._play_generation)
        assert not overlay.isVisible()
        overlay._frame_generation = overlay._play_generation
        overlay._frame_ready = True
        overlay._request_update()
        QtWidgets.QApplication.instance().processEvents()
        assert overlay.isVisible()

    def test_frame_before_playback_ready_then_playback_ready_shows(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay._ctx = MagicMock()
        overlay.activate('/a.mp4')
        overlay._frame_generation = overlay._play_generation
        overlay._frame_ready = True
        overlay._request_update()
        assert not overlay.isVisible()
        overlay._handle_playback_ready(overlay._play_generation)
        QtWidgets.QApplication.instance().processEvents()
        assert overlay.isVisible()

    def test_deferred_show_cancelled_by_deactivate(self, qtbot):
        from extensions.video.widget import MpvGLOverlay
        overlay = MpvGLOverlay()
        overlay.player = MagicMock()
        overlay._ctx = MagicMock()
        overlay.activate('/a.mp4')
        overlay._handle_playback_ready(overlay._play_generation)
        overlay._frame_generation = overlay._play_generation
        overlay._frame_ready = True
        overlay._request_update()
        assert not overlay._awaiting_first_frame
        overlay.deactivate()
        QtWidgets.QApplication.instance().processEvents()
        assert not overlay.isVisible()


class TestPlaybackSlotManager:
    @pytest.fixture
    def parent(self, qtbot):
        return QtWidgets.QWidget()

    @pytest.fixture
    def manager(self, parent):
        from extensions.video.widget import PlaybackSlotManager
        mgr = PlaybackSlotManager(parent, max_selected=2)
        yield mgr
        mgr.cleanup()

    def _make_cell(self, parent):
        from extensions.video.widget import MpvCellWidget
        w = MpvCellWidget(parent)
        w.setGeometry(0, 0, 200, 150)
        return w

    def test_activate_hover(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        assert manager._pending_hover_cell is cell
        manager._apply_hover()
        assert manager._hover_cell is cell
        assert manager._hover_overlay is not None
        cell.cleanup()

    def test_deactivate_hover(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        manager._apply_hover()
        overlay = manager._hover_overlay
        manager.deactivate_hover()
        assert manager._hover_cell is None
        assert manager._hover_overlay is None
        assert overlay.parentWidget() is parent
        cell.cleanup()

    def test_hover_noop_when_selected(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_select(cell, '/a.mp4')
        manager.activate_hover(cell, '/a.mp4')
        assert manager._hover_cell is None
        cell.cleanup()

    def test_hover_switches_from_previous(self, manager, parent):
        c1 = self._make_cell(parent)
        c2 = self._make_cell(parent)
        manager.activate_hover(c1, '/a.mp4')
        manager._apply_hover()
        first_overlay = manager._hover_overlay
        manager.activate_hover(c2, '/b.mp4')
        manager._apply_hover()
        assert manager._hover_cell is c2
        assert manager._hover_overlay is first_overlay
        assert len(manager._pool) == 0
        c1.cleanup()
        c2.cleanup()

    def test_activate_select(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_select(cell, '/a.mp4')
        assert manager.is_selected(cell)
        assert cell in manager._selected
        cell.cleanup()

    def test_deactivate_select(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_select(cell, '/a.mp4')
        overlay = manager._selected[cell]
        manager.deactivate_select(cell)
        assert not manager.is_selected(cell)
        assert overlay.parentWidget() is parent
        cell.cleanup()

    def test_select_promotes_hover(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        manager._apply_hover()
        hover_overlay = manager._hover_overlay
        manager.activate_select(cell, '/a.mp4')
        assert manager._hover_cell is None
        assert manager._hover_overlay is None
        assert manager._selected[cell] is hover_overlay
        cell.cleanup()

    def test_select_evicts_oldest(self, manager, parent):
        c1 = self._make_cell(parent)
        c2 = self._make_cell(parent)
        c3 = self._make_cell(parent)
        manager.activate_select(c1, '/a.mp4')
        manager.activate_select(c2, '/b.mp4')
        manager.activate_select(c3, '/c.mp4')
        assert not manager.is_selected(c1)
        assert manager.is_selected(c2)
        assert manager.is_selected(c3)
        c1.cleanup()
        c2.cleanup()
        c3.cleanup()

    def test_on_overlay_leave_deactivates_hover(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        manager._apply_hover()
        manager.on_overlay_leave(cell)
        assert manager._hover_cell is None
        cell.cleanup()

    def test_on_overlay_leave_keeps_selected(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_select(cell, '/a.mp4')
        manager.on_overlay_leave(cell)
        assert manager.is_selected(cell)
        cell.cleanup()

    def test_overlay_for_hover(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        manager._apply_hover()
        assert manager.overlay_for(cell) is manager._hover_overlay
        cell.cleanup()

    def test_overlay_for_selected(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_select(cell, '/a.mp4')
        assert manager.overlay_for(cell) is manager._selected[cell]
        cell.cleanup()

    def test_overlay_for_none(self, manager, parent):
        cell = self._make_cell(parent)
        assert manager.overlay_for(cell) is None
        cell.cleanup()

    def test_release_cell_clears_hover_and_selected(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_select(cell, '/a.mp4')
        manager.release_cell(cell)
        assert not manager.is_selected(cell)
        cell2 = self._make_cell(parent)
        manager.activate_hover(cell2, '/b.mp4')
        manager._apply_hover()
        manager.release_cell(cell2)
        assert manager._hover_cell is None
        cell.cleanup()
        cell2.cleanup()

    def test_resize_overlay(self, manager, parent):
        parent.show()
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        manager._apply_hover()
        overlay = manager._hover_overlay
        cell.setGeometry(0, 0, 300, 200)
        manager.resize_overlay(cell)
        assert overlay.geometry() == QtCore.QRect(0, 0, 300, 200)
        cell.cleanup()

    def test_cleanup_releases_all(self, manager, parent):
        c1 = self._make_cell(parent)
        c2 = self._make_cell(parent)
        manager.activate_hover(c1, '/a.mp4')
        manager._apply_hover()
        manager.activate_select(c2, '/b.mp4')
        manager.cleanup()
        assert manager._hover_cell is None
        assert len(manager._selected) == 0
        assert len(manager._pool) == 0
        c1.cleanup()
        c2.cleanup()

    def test_pool_reuses_overlays(self, manager, parent):
        c1 = self._make_cell(parent)
        c2 = self._make_cell(parent)
        manager.activate_hover(c1, '/a.mp4')
        manager._apply_hover()
        overlay = manager._hover_overlay
        manager.deactivate_hover()
        assert overlay in manager._pool
        manager.activate_hover(c2, '/b.mp4')
        manager._apply_hover()
        assert manager._hover_overlay is overlay
        assert overlay not in manager._pool
        c1.cleanup()
        c2.cleanup()

    def test_debounce_pending_cancelled_by_deactivate(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        assert manager._pending_hover_cell is cell
        manager.deactivate_hover()
        assert manager._pending_hover_cell is None
        assert manager._hover_cell is None
        cell.cleanup()

    def test_debounce_rapid_switch_only_activates_last(self, manager, parent):
        c1 = self._make_cell(parent)
        c2 = self._make_cell(parent)
        c3 = self._make_cell(parent)
        manager.activate_hover(c1, '/a.mp4')
        manager.activate_hover(c2, '/b.mp4')
        manager.activate_hover(c3, '/c.mp4')
        assert manager._pending_hover_cell is c3
        assert manager._hover_cell is None
        manager._apply_hover()
        assert manager._hover_cell is c3
        c1.cleanup()
        c2.cleanup()
        c3.cleanup()

    def test_debounce_pending_cancelled_by_release_cell(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        assert manager._pending_hover_cell is cell
        manager.release_cell(cell)
        assert manager._pending_hover_cell is None
        cell.cleanup()

    def test_select_cancels_pending_hover_for_same_cell(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        assert manager._pending_hover_cell is cell
        manager.activate_select(cell, '/a.mp4')
        assert manager._pending_hover_cell is None
        assert manager.is_selected(cell)
        cell.cleanup()

    def test_duplicate_pending_ignored(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        manager.activate_hover(cell, '/a.mp4')
        assert manager._pending_hover_cell is cell
        cell.cleanup()

    def test_is_hovering_pending(self, manager, parent):
        cell = self._make_cell(parent)
        assert not manager.is_hovering(cell)
        manager.activate_hover(cell, '/a.mp4')
        assert manager.is_hovering(cell)
        cell.cleanup()

    def test_is_hovering_active(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        manager._apply_hover()
        assert manager.is_hovering(cell)
        manager.deactivate_hover()
        assert not manager.is_hovering(cell)
        cell.cleanup()

    def test_promote_dead_overlay_reactivates(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        manager._apply_hover()
        overlay = manager._hover_overlay
        overlay.deactivate()
        manager.activate_select(cell, '/a.mp4')
        assert manager.is_selected(cell)
        assert manager._selected[cell] is overlay
        cell.cleanup()

    def test_deactivate_hover_reentrant_safe(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        manager._apply_hover()
        overlay = manager._hover_overlay
        manager.deactivate_hover()
        manager.deactivate_hover()
        assert manager._hover_cell is None
        assert overlay in manager._pool
        pool_count = sum(1 for o in manager._pool if o is overlay)
        assert pool_count == 1
        cell.cleanup()

    def test_acquire_uses_prewarmed_player(self, manager, parent):
        while manager._pool:
            manager._pool.pop()
        prewarmed = MagicMock()
        manager._player_pool.append(prewarmed)
        overlay = manager._acquire()
        assert overlay is not None
        assert overlay.player is prewarmed

    def test_cleanup_terminates_prewarmed_players(self, manager, parent):
        player1 = MagicMock()
        player2 = MagicMock()
        manager._player_pool.extend([player1, player2])
        manager.cleanup()
        player1.terminate.assert_called_once()
        player2.terminate.assert_called_once()
        assert len(manager._player_pool) == 0

    def test_appear_staggered_one_per_flush(self, manager, parent):
        c1 = self._make_cell(parent)
        c2 = self._make_cell(parent)
        manager.activate_appear(c1, '/a.mp4')
        manager.activate_appear(c2, '/b.mp4')
        assert manager.is_appeared(c1)
        assert manager.is_appeared(c2)
        assert c1 not in manager._appeared
        assert c2 not in manager._appeared
        assert len(manager._appear_queue) == 2
        manager._flush_appear_queue()
        assert c1 in manager._appeared
        assert c2 not in manager._appeared
        assert len(manager._appear_queue) == 1
        manager._flush_appear_queue()
        assert c2 in manager._appeared
        assert len(manager._appear_queue) == 0
        c1.cleanup()
        c2.cleanup()

    def test_appear_deactivate_removes_from_queue(self, manager, parent):
        c1 = self._make_cell(parent)
        c2 = self._make_cell(parent)
        manager.activate_appear(c1, '/a.mp4')
        manager.activate_appear(c2, '/b.mp4')
        manager.deactivate_appear(c1)
        assert len(manager._appear_queue) == 1
        assert manager._appear_queue[0][0] is c2
        c1.cleanup()
        c2.cleanup()

    def test_appear_flush_skips_deactivated(self, manager, parent):
        c1 = self._make_cell(parent)
        manager.activate_appear(c1, '/a.mp4')
        manager.deactivate_appear(c1)
        manager._flush_appear_queue()
        assert c1 not in manager._appeared
        c1.cleanup()

    def test_appear_cleanup_clears_queue(self, manager, parent):
        c1 = self._make_cell(parent)
        manager.activate_appear(c1, '/a.mp4')
        assert len(manager._appear_queue) == 1
        manager.cleanup()
        assert len(manager._appear_queue) == 0
        assert not manager._appear_flushing
        c1.cleanup()

    def test_appear_promotes_hover_on_flush(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_hover(cell, '/a.mp4')
        manager._apply_hover()
        hover_overlay = manager._hover_overlay
        manager.activate_appear(cell, '/a.mp4')
        manager._flush_appear_queue()
        assert manager._hover_cell is None
        assert manager._appeared[cell] is hover_overlay
        cell.cleanup()

    def test_appear_release_cell_removes_from_queue(self, manager, parent):
        cell = self._make_cell(parent)
        manager.activate_appear(cell, '/a.mp4')
        assert len(manager._appear_queue) == 1
        manager.release_cell(cell)
        assert len(manager._appear_queue) == 0
        cell.cleanup()


class TestThumbnailRunner:
    pass
